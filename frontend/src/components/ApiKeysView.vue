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
import AppTable from './AppTable.vue'

const columns = [
  { key: 'name', label: '备注', sortable: true },
  { key: 'key_prefix', label: 'Key', mono: true },
  { key: 'created_at', label: '创建时间' },
  { key: 'last_used_at', label: '最近使用' },
  { key: 'status', label: '状态' },
]

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
      key: 'create',
      comp: AppButton,
      props: { variant: 'primary', icon: 'plus' },
      on: { click: () => openCreate() },
      text: '新建 Key',
    },
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
</script>

<template>
  <section class="keys">
    <header class="keys__intro">
      <h2 class="keys__title">API Keys</h2>
      <p class="keys__desc">
        给 AI 助手（WorkBuddy 等）签发一把「以你身份访问知识库」的钥匙：数据隔离与你完全一致，
        泄露时单独撤销即可。<strong>明文只在创建时显示一次</strong>，请保存好后再关闭弹窗。
      </p>
    </header>

    <p v-if="loadError" class="keys__alert">
      <AppIcon name="alert" :size="16" />
      <span>无法获取 API Key 列表，请检查后端与鉴权设置。</span>
    </p>

    <AppTable
      :columns="columns"
      :rows="keys"
      :loading="loading && !keys.length"
      row-key="id"
      sortable
      empty-text="还没有 API Key"
      empty-icon="keys"
    >
      <template #cell-name="{ row }">
        <span class="keys__name">{{ row.name || '（未命名）' }}</span>
      </template>

      <template #cell-key_prefix="{ row }">
        <code class="keys__prefix">{{ row.key_prefix }}…</code>
      </template>

      <template #cell-created_at="{ row }">
        <span class="keys__muted">{{ fmtTime(row.created_at) }}</span>
      </template>

      <template #cell-last_used_at="{ row }">
        <span class="keys__muted">{{ fmtTime(row.last_used_at) }}</span>
      </template>

      <template #cell-status="{ row }">
        <!-- 颜色 + 文本双编码；色值复用作业七态的那套（statusStyles），不另起炉灶 -->
        <AppStatusBadge
          :status="row.revoked_at ? 'cancelled' : 'success'"
          :label="row.revoked_at ? '已撤销' : '使用中'"
          size="sm"
        />
      </template>

      <template #empty>
        <AppEmptyState
          size="sm"
          icon="keys"
          title="还没有 API Key"
          description="签发一个 Key 交给 AI 助手，它就能检索、问答你的知识库。"
          action-text="新建 Key"
          action-icon="plus"
          @action="openCreate"
        />
      </template>

      <template #row-actions="{ row }">
        <span class="keys__row-actions">
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
        </span>
      </template>
    </AppTable>

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
</style>
