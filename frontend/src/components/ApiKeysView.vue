<script setup>
// API Keys 管理页 —— 用户级 Key 的签发 / 列表 / 撤销（M06 §5.7）。
//
// 用途：给 WorkBuddy 等 agent 一把「以我身份访问知识库」的钥匙 ——
// 数据隔离与本人一致，泄露时单独撤销、不影响本人登录（JWT）与其它 agent。
//
// 本页最重要的一条契约：**明文 key 只在创建响应出现一次**（服务端只存 sha256）。
// 所以创建成功后必须用独立弹窗大字展示 + 复制按钮，用户确认「已保存」前绝不关闭；
// 列表里永远只有 key_prefix（前 11 字符），不存在「回头看明文」的入口。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { authApi } from '../api'
import { copyText } from '../clipboard'
import { setTopbarActions, clearTopbarActions } from '../shell'
import { toast } from '../toast'
import AppButton from './AppButton.vue'
import AppConfirm from './AppConfirm.vue'
import AppEmptyState from './AppEmptyState.vue'
import AppIcon from './AppIcon.vue'
import AppInput from './AppInput.vue'
import AppModal from './AppModal.vue'
import AppStatusBadge from './AppStatusBadge.vue'

const keys = ref([])
const loading = ref(true)
const loadError = ref('')

// 创建弹窗（输入备注）
const creating = ref(false)
const creatingName = ref('')
const creatingError = ref('')
const creatingBusy = ref(false)

// 创建成功弹窗（明文仅此一次）
const revealed = ref(null) // { key, prefix, name }
const revealOpen = ref(false) // AppModal 的 v-model 只接受布尔，数据与开关分离
const copied = ref(false)

// 撤销确认
const confirmOpen = ref(false)
const confirmTarget = ref(null)
const confirmBusy = ref(false)

const activeCount = computed(() => keys.value.filter((k) => !k.revoked_at).length)
const transport = ref('http')
const mcpConfig = computed(() => (
  transport.value === 'http'
    ? `{
  "mcpServers": {
    "notes-rag": {
      "url": "http://localhost:8000/mcp/",
      "headers": { "X-API-Key": "nr_粘贴你的key" }
    }
  }
}`
    : `{
  "mcpServers": {
    "notes-rag": {
      "command": "<仓库绝对路径>/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "env": { "NOTES_RAG_API_KEY": "nr_粘贴你的key" }
    }
  }
}`
))

/* ---------- 加载 ---------- */

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    keys.value = await authApi.listApiKeys()
  } catch (e) {
    loadError.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  setTopbarActions([
    {
      key: 'refresh',
      comp: AppButton,
      props: { variant: 'secondary', icon: 'refresh' },
      on: { click: load },
      text: '刷新',
    },
  ])
  load()
})

onUnmounted(clearTopbarActions)

/* ---------- 新建 ---------- */

function openCreate() {
  creatingName.value = ''
  creatingError.value = ''
  creating.value = true
}

async function submitCreate() {
  creatingError.value = ''
  creatingBusy.value = true
  try {
    const created = await authApi.createApiKey(creatingName.value.trim())
    creating.value = false
    copied.value = false
    revealed.value = created
    revealOpen.value = true
    await load()
  } catch (e) {
    creatingError.value = e.message
  } finally {
    creatingBusy.value = false
  }
}

async function copyRevealed() {
  const ok = await copyText(revealed.value?.key)
  if (!ok) {
    toast.error('复制失败：请手动选中并复制')
    return
  }
  copied.value = true
  toast.success('已复制到剪贴板')
}

function closeRevealed() {
  // 关闭即「永久失去明文」——二次确认的语义由按钮文案承担（「我已保存」），
  // 不再叠一层 confirm：弹窗 + 文案已足够强调，叠层只会训练用户无脑点确定。
  revealOpen.value = false
  revealed.value = null
}

/* ---------- 撤销 ---------- */

function askRevoke(k) {
  confirmTarget.value = k
  confirmOpen.value = true
}

async function doRevoke() {
  const k = confirmTarget.value
  if (!k) return
  confirmBusy.value = true
  try {
    await authApi.revokeApiKey(k.id)
    confirmOpen.value = false
    toast.success(`已撤销「${k.name || k.key_prefix}」，使用它的 agent 会立即失去访问权限`)
    await load()
  } catch (e) {
    toast.error(e.status === 404 ? '该 Key 不存在或已撤销' : `撤销失败：${e.message}`)
  } finally {
    confirmBusy.value = false
  }
}

/* ---------- 展示 ---------- */

function fmtTime(v) {
  if (!v) return '—'
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString()
}

async function copyConfig() {
  const ok = await copyText(mcpConfig.value)
  if (!ok) {
    toast.error('复制失败：请手动选中并复制')
    return
  }
  toast.success('MCP 配置已复制')
}
</script>

<template>
  <section class="keys">
    <header class="page-intro">
      <div>
        <div class="eyebrow"><span class="eyebrow__dot"></span> API ACCESS &amp; MCP</div>
        <h1>把一把可撤销的钥匙交给助手</h1>
        <p>API Key 以你的身份访问 Vault；创建后明文只显示一次。</p>
      </div>
      <AppButton variant="primary" icon="plus" @click="openCreate">新建 API Key</AppButton>
    </header>

    <p v-if="loadError" class="keys__alert">
      <AppIcon name="alert" :size="16" />
      <span>无法获取 API Key 列表，请检查后端与鉴权设置。</span>
    </p>

    <div class="keys-layout">
      <div class="keys-main">
        <section class="keys-summary">
          <div>
            <span class="keys-summary__icon"><AppIcon name="keys" :size="17" /></span>
            <span><small>使用中的 Key</small><strong>{{ activeCount }}</strong></span>
          </div>
          <span>每个助手可单独撤销授权</span>
        </section>

        <section class="panel keys-table">
          <header class="keys-table__heading"><h2>已签发的 API Keys</h2><span>{{ keys.length }} 条记录</span></header>
          <div v-if="loading && !keys.length" class="keys-list-state">正在加载 API Key…</div>
          <AppEmptyState
            v-else-if="!keys.length"
            size="sm"
            icon="keys"
            title="还没有 API Key"
            description="签发一个 Key 交给 AI 助手，它就能检索、问答你的知识库。"
            action-text="新建 Key"
            action-icon="plus"
            @action="openCreate"
          />
          <div v-else class="keys-table__rows">
            <article v-for="row in keys" :key="row.id" class="key-row">
              <span class="key-row__icon"><AppIcon name="keys" :size="16" /></span>
              <span class="key-row__name"><strong>{{ row.name || '（未命名）' }}</strong><small>创建于 {{ fmtTime(row.created_at) }}</small></span>
              <code class="key-row__prefix">{{ row.key_prefix }}…</code>
              <span class="key-row__used"><small>最近使用</small>{{ fmtTime(row.last_used_at) }}</span>
              <AppStatusBadge
                :status="row.revoked_at ? 'cancelled' : 'success'"
                :label="row.revoked_at ? '已撤销' : '使用中'"
                size="sm"
              />
              <AppButton
                variant="danger"
                size="sm"
                icon="trash"
                :disabled="!!row.revoked_at"
                :title="row.revoked_at ? '已撤销' : '撤销后使用该 Key 的 agent 立即失效'"
                @click="askRevoke(row)"
              >
                撤销
              </AppButton>
            </article>
          </div>
        </section>

        <section class="panel mcp-card">
          <header class="mcp-card__heading">
            <div><h2>MCP 客户端配置</h2><p>选择与助手部署位置相符的连接方式</p></div>
            <span class="mcp-readonly"><AppIcon name="info" :size="14" />只读工具</span>
          </header>
          <div class="transport-tabs" role="tablist">
            <button type="button" role="tab" :aria-selected="transport === 'http'" :class="{ 'is-active': transport === 'http' }" @click="transport = 'http'">
              <AppIcon name="link" :size="15" />HTTP 远程
            </button>
            <button type="button" role="tab" :aria-selected="transport === 'stdio'" :class="{ 'is-active': transport === 'stdio' }" @click="transport = 'stdio'">
              <AppIcon name="monitor" :size="15" />stdio 本机
            </button>
          </div>
          <div class="mcp-config">
            <div class="mcp-config__bar"><span>JSON · 使用占位符替换 API Key</span><button type="button" @click="copyConfig"><AppIcon name="copy" :size="13" />复制配置</button></div>
            <pre><code>{{ mcpConfig }}</code></pre>
          </div>
          <p v-if="transport === 'http'" class="mcp-note"><AppIcon name="alert" :size="14" /><span>HTTP 地址必须保留末尾斜杠 <code>/mcp/</code>，并通过 <code>X-API-Key</code> 传入刚签发的 Key。</span></p>
          <p v-else class="mcp-note"><AppIcon name="info" :size="14" /><span>stdio 通过 <code>NOTES_RAG_API_KEY</code> 设置身份；单用户本机模式在特定配置下可省略。</span></p>
          <div class="mcp-tools"><span>只读工具</span><code>search_notes</code><code>get_note</code><code>list_vaults</code><code>ask_notes</code></div>
        </section>
      </div>

      <aside class="keys-side">
        <section class="panel key-safety">
          <span class="key-safety__icon"><AppIcon name="info" :size="17" /></span>
          <h2>Key 安全须知</h2>
          <ul><li>完整 Key 只在创建后展示一次。</li><li>列表仅保留前缀，不可再次查看明文。</li><li>泄露或丢失时撤销并重新签发。</li><li>远程 HTTP 建议使用 HTTPS。</li></ul>
        </section>
        <section class="panel mcp-steps">
          <h2>接入步骤</h2>
          <div><span>1</span><p><strong>新建 API Key</strong><small>为每个助手使用独立备注。</small></p></div>
          <div><span>2</span><p><strong>复制 MCP 配置</strong><small>选择 stdio 或 HTTP 并粘贴 Key。</small></p></div>
          <div><span>3</span><p><strong>重启并验证</strong><small>让助手列出当前身份可见的 Vault。</small></p></div>
        </section>
      </aside>
    </div>

    <!-- 第 1 步：填写备注 -->
    <AppModal v-model="creating" title="新建 API Key">
      <div class="keys__form">
        <AppInput
          v-model="creatingName"
          label="备注"
          placeholder="例如 workbuddy / 我的笔记本"
          hint="仅用于在这里识别这把 Key，agent 那边看不到。"
        />
        <p class="keys__warn">
          <AppIcon name="info" :size="16" />
          <span>创建后会显示完整 Key（<code>nr_</code> 开头），<strong>只有这一次机会</strong>——请准备好粘贴的地方。</span>
        </p>
        <p v-if="creatingError" class="keys__form-error">{{ creatingError }}</p>
      </div>
      <template #footer>
        <AppButton variant="secondary" :disabled="creatingBusy" @click="creating = false">取消</AppButton>
        <AppButton variant="primary" :loading="creatingBusy" @click="submitCreate">创建</AppButton>
      </template>
    </AppModal>

    <!-- 第 2 步：展示明文（仅此一次，确认保存前绝不关闭） -->
    <AppModal v-model="revealOpen" title="请立即保存你的 Key">
      <div v-if="revealed" class="keys__reveal">
        <p class="keys__reveal-hint">
          以下就是完整 Key（{{ revealed.name || '未命名' }}）。<strong>关闭后无法再次查看</strong>，
          丢失只能撤销重建。
        </p>
        <div class="keys__reveal-box">
          <code class="keys__reveal-key">{{ revealed.key }}</code>
          <AppButton
            variant="secondary"
            size="sm"
            :icon="copied ? 'check' : 'copy'"
            @click="copyRevealed"
          >
            {{ copied ? '已复制' : '复制' }}
          </AppButton>
        </div>
        <p class="keys__reveal-usage">
          用法：填入 agent 的 MCP 配置（<code>env.NOTES_RAG_API_KEY</code>）或请求头
          <code>X-API-Key</code>，详见「MCP 接入使用说明」（docs/mcp-guide.md）。
        </p>
      </div>
      <template #footer>
        <AppButton variant="primary" @click="closeRevealed">我已保存，关闭</AppButton>
      </template>
    </AppModal>

    <AppConfirm
      v-model="confirmOpen"
      danger
      title="撤销 API Key"
      :message="`撤销「${confirmTarget?.name || confirmTarget?.key_prefix || ''}」？使用它的 agent（如 WorkBuddy）会立即失去访问权限；此操作不可恢复，需要时请重新签发。`"
      confirm-text="撤销"
      :loading="confirmBusy"
      @confirm="doRevoke"
    />
  </section>
</template>

<style scoped>
.keys {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.keys__title {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-h1);
  line-height: var(--line-height-h1);
  font-weight: var(--font-weight-semibold);
}

.keys__desc {
  margin: var(--space-1) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

.keys__alert {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--brand-accent-soft);
  color: var(--brand-accent-on);
  font-size: var(--font-size-body);
}

.keys__name {
  color: var(--color-text-primary);
}

.keys__prefix {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.keys__muted {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.keys__row-actions {
  display: inline-flex;
  gap: var(--space-2);
}

/* ---------- 创建弹窗 ---------- */

.keys__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.keys__warn {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--brand-accent-soft);
  color: var(--brand-accent-on);
  font-size: var(--font-size-sm);
  line-height: 1.6;
}

.keys__form-error {
  margin: 0;
  color: var(--brand-accent-hover);
  font-size: var(--font-size-sm);
}

/* ---------- 明文展示弹窗 ---------- */

.keys__reveal {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.keys__reveal-hint,
.keys__reveal-usage {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

.keys__reveal-box {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-subtle);
}

.keys__reveal-key {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
  font-family: var(--font-family-mono);
  font-size: var(--font-size-body);
  color: var(--color-text-primary);
  user-select: all;   /* 复制按钮之外兜底：整段点选即可复制 */
}

.keys-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(210px, 0.7fr);
  gap: 15px;
  align-items: start;
}

.keys-main,
.keys-side {
  display: grid;
  gap: 13px;
  min-width: 0;
}

.keys-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 13px 15px;
  background: var(--ui-primary-soft);
  border: 1px solid var(--ui-border);
  border-radius: 10px;
}

.keys-summary > div {
  display: flex;
  align-items: center;
  gap: 9px;
}

.keys-summary__icon {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  color: var(--ui-primary);
  background: var(--ui-surface);
  border-radius: 9px;
}

.keys-summary > div > span:last-child {
  display: grid;
  gap: 1px;
}

.keys-summary small {
  color: var(--ui-muted);
  font-size: 8px;
}

.keys-summary strong {
  color: var(--ui-ink);
  font-size: 17px;
}

.keys-summary > span:last-child {
  color: var(--ui-text);
  font-size: 8px;
}

.keys-table {
  overflow: hidden;
  padding: 0;
}

.keys-table__heading,
.mcp-card__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.keys-table__heading {
  min-height: 47px;
  padding: 12px 14px;
}

.keys-table__heading h2,
.key-safety h2,
.mcp-steps h2,
.mcp-card h2 {
  color: var(--ui-ink);
  font-size: 11px;
}

.keys-table__heading > span {
  color: var(--ui-muted);
  font-size: 8px;
}

.keys-list-state {
  padding: 22px 14px;
  color: var(--ui-muted);
  text-align: center;
  font-size: 9px;
}

.keys-table__rows {
  border-top: 1px solid var(--ui-border);
}

.key-row {
  min-height: 58px;
  display: grid;
  grid-template-columns: 26px minmax(110px, 1fr) minmax(95px, 0.8fr) minmax(120px, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  padding: 8px 13px;
  border-bottom: 1px solid var(--ui-border);
}

.key-row:last-child {
  border-bottom: 0;
}

.key-row__icon {
  width: 25px;
  height: 25px;
  display: grid;
  place-items: center;
  color: var(--ui-primary);
  background: var(--ui-primary-soft);
  border-radius: 7px;
}

.key-row__name {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.key-row__name strong {
  overflow: hidden;
  color: var(--ui-ink);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.key-row__name small,
.key-row__used,
.key-row__used small {
  color: var(--ui-muted);
  font-size: 8px;
}

.key-row__prefix {
  overflow: hidden;
  color: var(--ui-text);
  font-family: var(--font-family-mono);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.key-row__used {
  display: grid;
  gap: 3px;
}

.mcp-card {
  padding: 15px;
}

.mcp-card__heading p {
  margin-top: 3px;
  color: var(--ui-muted);
  font-size: 8px;
}

.mcp-readonly {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--ui-success);
  font-size: 8px;
}

.transport-tabs {
  display: flex;
  gap: 4px;
  margin-top: 12px;
}

.transport-tabs button {
  min-height: 30px;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 0 8px;
  color: var(--ui-muted);
  background: transparent;
  border: 0;
  border-radius: 6px;
  font-size: 8px;
  cursor: pointer;
}

.transport-tabs button.is-active {
  color: var(--ui-primary);
  background: var(--ui-primary-soft);
}

.mcp-config {
  overflow: hidden;
  margin-top: 7px;
  color: #dbe7f5;
  background: #182a42;
  border-radius: 8px;
}

.mcp-config__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 9px;
  color: #afc0d3;
  border-bottom: 1px solid rgb(255 255 255 / 10%);
  font-size: 8px;
}

.mcp-config__bar button {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #dce7f4;
  background: transparent;
  border: 0;
  font-size: 8px;
  cursor: pointer;
}

.mcp-config pre {
  overflow-x: auto;
  margin: 0;
  padding: 11px;
  font-family: var(--font-family-mono);
  font-size: 8px;
  line-height: 14px;
}

.mcp-note {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 9px;
  color: var(--ui-muted);
  font-size: 8px;
  line-height: 14px;
}

.mcp-note :deep(svg) {
  flex: none;
  color: var(--ui-warning);
}

.mcp-note code {
  color: var(--ui-ink);
  font-family: var(--font-family-mono);
}

.mcp-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  margin-top: 11px;
  padding-top: 10px;
  border-top: 1px solid var(--ui-border);
}

.mcp-tools > span {
  margin-right: 3px;
  color: var(--ui-muted);
  font-size: 8px;
}

.mcp-tools code {
  padding: 3px 5px;
  color: var(--ui-primary);
  background: var(--ui-primary-soft);
  border-radius: 4px;
  font-size: 7px;
}

.key-safety,
.mcp-steps {
  padding: 14px;
}

.key-safety__icon {
  width: 29px;
  height: 29px;
  display: grid;
  place-items: center;
  margin-bottom: 10px;
  color: var(--ui-warning);
  background: var(--ui-surface-soft);
  border-radius: 8px;
}

.key-safety ul {
  display: grid;
  gap: 8px;
  margin: 10px 0 0;
  padding-left: 14px;
  color: var(--ui-text);
  font-size: 8px;
  line-height: 13px;
}

.mcp-steps > div {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.mcp-steps > div > span {
  width: 20px;
  height: 20px;
  display: grid;
  flex: none;
  place-items: center;
  color: var(--ui-primary);
  background: var(--ui-primary-soft);
  border-radius: 50%;
  font-size: 8px;
  font-weight: 700;
}

.mcp-steps p {
  display: grid;
  gap: 3px;
}

.mcp-steps strong {
  color: var(--ui-ink);
  font-size: 8px;
}

.mcp-steps small {
  color: var(--ui-muted);
  font-size: 7px;
  line-height: 12px;
}

@media (max-width: 980px) {
  .keys-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .keys-side {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .keys-side {
    grid-template-columns: minmax(0, 1fr);
  }

  .keys-summary,
  .keys-table,
  .mcp-card {
    min-width: 0;
    max-width: 100%;
  }

  .keys-summary > span:last-child {
    max-width: 45%;
    text-align: right;
  }

  .key-row {
    grid-template-columns: 24px minmax(0, 1fr) auto;
    min-width: 0;
  }

  .key-row__icon {
    grid-column: 1;
    grid-row: 1;
  }

  .key-row__name {
    grid-column: 2;
    grid-row: 1;
  }

  .key-row__prefix {
    grid-column: 2;
    grid-row: 2;
  }

  .key-row__used {
    grid-column: 2;
    grid-row: 3;
  }

  .key-row > :deep(.app-status-badge) {
    grid-column: 3;
    grid-row: 1;
  }

  .key-row > :deep(button) {
    grid-column: 3;
    grid-row: 2 / span 2;
  }
}
</style>
