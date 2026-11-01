<script setup>
import { computed, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'

const emit = defineEmits(['notify'])
const keys = ref([
  { id: 1, name: 'WorkBuddy', prefix: 'nr_4c8f21a…', created: '2026-06-18 10:22', lastUsed: '今天 10:46', revoked: false },
  { id: 2, name: '本地开发助手', prefix: 'nr_9a20d13…', created: '2026-06-12 16:05', lastUsed: '昨天 21:14', revoked: false },
  { id: 3, name: '旧设备', prefix: 'nr_31d71bf…', created: '2026-05-30 09:11', lastUsed: '—', revoked: true },
])

const activeCount = computed(() => keys.value.filter((key) => !key.revoked).length)
const createOpen = ref(false)
const name = ref('')
const nameError = ref('')
const revealedKey = ref('')
const revealName = ref('')
const copied = ref(false)
const revokeTarget = ref(null)
const transport = ref('http')

const config = computed(() => transport.value === 'http'
  ? `{\n  "mcpServers": {\n    "notes-rag": {\n      "url": "http://localhost:8000/mcp/",\n      "headers": { "X-API-Key": "nr_粘贴你的key" }\n    }\n  }\n}`
  : `{\n  "mcpServers": {\n    "notes-rag": {\n      "command": "<仓库绝对路径>/.venv/bin/python",\n      "args": ["-m", "app.mcp.server"],\n      "env": { "NOTES_RAG_API_KEY": "nr_粘贴你的key" }\n    }\n  }\n}`)

function createKey() {
  const trimmedName = name.value.trim()
  if (!trimmedName) {
    nameError.value = '请填写备注名称。'
    return
  }
  const suffix = Date.now().toString(36).slice(-7)
  const key = `demo-only-${suffix}-not-valid`
  keys.value.unshift({
    id: Math.max(...keys.value.map((item) => item.id), 0) + 1,
    name: trimmedName,
    prefix: `demo-${suffix}…`,
    created: '刚刚',
    lastUsed: '—',
    revoked: false,
  })
  revealName.value = trimmedName
  revealedKey.value = key
  copied.value = false
  name.value = ''
  nameError.value = ''
  createOpen.value = false
}

async function copyText(text, successMessage) {
  if (!navigator.clipboard?.writeText) {
    emit('notify', '浏览器不支持剪贴板，请手动选中内容')
    return false
  }
  try {
    await navigator.clipboard.writeText(text)
    emit('notify', successMessage)
    return true
  } catch {
    emit('notify', '复制失败，请检查浏览器剪贴板权限')
    return false
  }
}

async function copyRevealedKey() {
  copied.value = await copyText(revealedKey.value, '演示 Key 已复制')
}

async function copyConfig() {
  await copyText(config.value, 'MCP 示例配置已复制')
}

function closeReveal() {
  revealedKey.value = ''
  revealName.value = ''
  copied.value = false
}

function revokeKey() {
  keys.value = keys.value.map((key) => key.id === revokeTarget.value.id ? { ...key, revoked: true } : key)
  emit('notify', `已撤销演示 Key「${revokeTarget.value.name}」`)
  revokeTarget.value = null
}
</script>

<template>
  <div class="page-intro">
    <div><div class="eyebrow"><span class="eyebrow__dot"></span> API ACCESS & MCP</div><h1>把一把可撤销的钥匙交给助手</h1><p>API Key 以你的身份访问 Vault；创建后明文只显示一次。</p></div>
    <button class="button button--primary" type="button" @click="createOpen = true; nameError = ''"><AppIcon name="plus" :size="16" />新建 API Key</button>
  </div>

  <div class="keys-layout">
    <div class="keys-main">
      <div class="keys-summary"><div><span class="keys-summary__icon"><AppIcon name="keys" :size="17" /></span><span><small>使用中的 Key</small><strong>{{ activeCount }}</strong></span></div><span>每个助手可单独撤销授权</span></div>
      <section class="panel keys-table">
        <div class="keys-table__heading"><h2>已签发的 API Keys</h2><span>{{ keys.length }} 条记录</span></div>
        <div class="keys-table__head"><span>备注</span><span>Key 前缀</span><span>最近使用</span><span>状态</span><span></span></div>
        <article v-for="key in keys" :key="key.id" class="key-row">
          <span class="key-row__name"><strong>{{ key.name }}</strong><small>创建于 {{ key.created }}</small></span>
          <code>{{ key.prefix }}</code>
          <span class="key-row__used">{{ key.lastUsed }}</span>
          <span class="key-state" :class="{ 'is-revoked': key.revoked }"><span></span>{{ key.revoked ? '已撤销' : '使用中' }}</span>
          <button class="key-revoke" type="button" :disabled="key.revoked" :aria-label="`撤销 ${key.name}`" @click="revokeTarget = key"><AppIcon name="trash" :size="14" />撤销</button>
        </article>
      </section>

      <section class="panel mcp-card">
        <div class="mcp-card__heading"><div><h2>MCP 客户端配置</h2><p>选择与助手部署位置相符的连接方式</p></div><span class="mcp-readonly"><AppIcon name="info" :size="14" />只读工具</span></div>
        <div class="transport-tabs" role="tablist">
          <button type="button" role="tab" :aria-selected="transport === 'http'" :class="{ 'is-active': transport === 'http' }" @click="transport = 'http'"><AppIcon name="link" :size="15" />HTTP 远程</button>
          <button type="button" role="tab" :aria-selected="transport === 'stdio'" :class="{ 'is-active': transport === 'stdio' }" @click="transport = 'stdio'"><AppIcon name="monitor" :size="15" />stdio 本机</button>
        </div>
        <div class="mcp-config">
          <div class="mcp-config__bar"><span>JSON</span><button type="button" @click="copyConfig"><AppIcon name="copy" :size="13" />复制配置</button></div>
          <pre><code>{{ config }}</code></pre>
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
      <section class="panel mcp-steps"><h2>接入步骤</h2><div><span>1</span><p><strong>新建 API Key</strong><small>为每个助手使用独立备注。</small></p></div><div><span>2</span><p><strong>复制 MCP 配置</strong><small>选择 stdio 或 HTTP 并粘贴 Key。</small></p></div><div><span>3</span><p><strong>重启并验证</strong><small>让助手列出当前身份可见的 Vault。</small></p></div></section>
    </aside>
  </div>

  <div v-if="createOpen" class="dialog-backdrop" @click.self="createOpen = false">
    <section class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="create-key-title" @keydown.esc.prevent="createOpen = false">
      <div class="dialog-card__heading"><span class="key-modal-icon"><AppIcon name="keys" :size="18" /></span><button class="demo-icon-button" type="button" aria-label="关闭" @click="createOpen = false"><AppIcon name="close" :size="17" /></button></div>
      <h2 id="create-key-title">新建 API Key</h2><p class="dialog-card__desc">备注只用于你在列表中识别这把 Key。</p>
      <label class="form-field"><span>备注</span><input v-model="name" autofocus placeholder="例如 workbuddy / 我的笔记本" @input="nameError = ''" /></label>
      <p v-if="nameError" class="form-error" role="alert">{{ nameError }}</p>
      <div class="key-warning"><AppIcon name="alert" :size="15" /><span>创建后完整 Key 只展示一次，请准备好安全保存的位置。</span></div>
      <div class="dialog-card__actions"><button class="button button--secondary" type="button" @click="createOpen = false">取消</button><button class="button button--primary" type="button" @click="createKey">创建演示 Key</button></div>
    </section>
  </div>

  <div v-if="revealedKey" class="dialog-backdrop">
    <section class="dialog-card reveal-card" role="dialog" aria-modal="true" aria-labelledby="reveal-key-title">
      <span class="reveal-card__badge"><AppIcon name="check" :size="14" />已创建演示 Key</span>
      <h2 id="reveal-key-title">请立即保存你的 Key</h2>
      <p class="dialog-card__desc">{{ revealName }} 的完整 Key 只在这里显示一次。关闭后无法再次查看。</p>
      <div class="revealed-key"><code>{{ revealedKey }}</code><button class="button button--secondary" type="button" @click="copyRevealedKey"><AppIcon :name="copied ? 'check' : 'copy'" :size="14" />{{ copied ? '已复制' : '复制' }}</button></div>
      <p class="demo-key-warning">此值以 <code>demo-only</code> 开头，仅用于演示，不能用于真实鉴权。</p>
      <div class="dialog-card__actions"><button class="button button--primary" type="button" @click="closeReveal">我已保存，关闭</button></div>
    </section>
  </div>

  <div v-if="revokeTarget" class="dialog-backdrop" @click.self="revokeTarget = null">
    <section class="dialog-card dialog-card--compact" role="alertdialog" aria-modal="true" aria-labelledby="revoke-key-title">
      <h2 id="revoke-key-title">撤销「{{ revokeTarget.name }}」？</h2><p class="dialog-card__desc">撤销后，使用这把 Key 的助手会失去访问权限。此操作不可恢复。</p>
      <div class="dialog-card__actions"><button class="button button--secondary" type="button" @click="revokeTarget = null">取消</button><button class="button button--danger" type="button" @click="revokeKey">确认撤销</button></div>
    </section>
  </div>
</template>

<style scoped>
.button { min-height: 37px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 0 11px; border: 1px solid var(--ui-border); border-radius: 8px; font-size: 9px; font-weight: 600; cursor: pointer; }
.button--primary { color: var(--color-primary-contrast); background: var(--ui-primary); border-color: var(--ui-primary); }
.button--secondary { color: var(--ui-text); background: var(--ui-surface); }
.button--danger { color: var(--color-danger-contrast); background: var(--ui-danger); border-color: var(--ui-danger); }
.keys-layout { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(210px, .7fr); gap: 15px; align-items: start; }
.keys-main, .keys-side { display: grid; grid-template-columns: minmax(0, 1fr); gap: 13px; min-width: 0; }
.keys-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 13px 15px; background: var(--ui-primary-soft); border: 1px solid var(--ui-border); border-radius: 10px; }
.keys-summary > div { display: flex; align-items: center; gap: 9px; }
.keys-summary__icon, .key-modal-icon { width: 32px; height: 32px; display: grid; place-items: center; color: var(--ui-primary); background: var(--ui-surface); border-radius: 9px; }
.keys-summary > div > span:last-child { display: grid; gap: 1px; }
.keys-summary small { color: var(--ui-muted); font-size: 8px; }
.keys-summary strong { color: var(--ui-ink); font-size: 17px; }
.keys-summary > span:last-child { color: var(--ui-text); font-size: 8px; }
.keys-table { overflow: hidden; padding: 0; }
.keys-table__heading { display: flex; align-items: center; justify-content: space-between; padding: 13px 14px; }
.keys-table__heading h2, .key-safety h2, .mcp-steps h2, .mcp-card h2 { color: var(--ui-ink); font-size: 11px; }
.keys-table__heading > span { color: var(--ui-muted); font-size: 8px; }
.keys-table__head, .key-row { display: grid; grid-template-columns: minmax(90px, 1.1fr) minmax(100px, .9fr) minmax(100px, .9fr) 72px 52px; align-items: center; gap: 8px; }
.keys-table__head { min-height: 32px; padding: 0 13px; color: var(--ui-muted); background: var(--ui-surface-soft); border-top: 1px solid var(--ui-border); border-bottom: 1px solid var(--ui-border); font-size: 8px; }
.key-row { min-height: 55px; padding: 7px 13px; border-bottom: 1px solid var(--ui-border); }
.key-row:last-child { border-bottom: 0; }
.key-row__name { display: grid; gap: 3px; }
.key-row__name strong { overflow: hidden; color: var(--ui-ink); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.key-row__name small, .key-row__used { color: var(--ui-muted); font-size: 8px; }
.key-row code { overflow: hidden; color: var(--ui-text); font-family: var(--ui-font-mono); font-size: 8px; text-overflow: ellipsis; }
.key-state { display: flex; align-items: center; gap: 5px; color: var(--ui-success); font-size: 8px; }
.key-state > span { width: 5px; height: 5px; background: currentColor; border-radius: 50%; }
.key-state.is-revoked { color: var(--ui-muted); }
.key-revoke { display: flex; align-items: center; justify-content: center; gap: 3px; min-height: 26px; padding: 0 5px; color: var(--ui-danger); background: transparent; border: 1px solid var(--ui-border); border-radius: 6px; font-size: 8px; cursor: pointer; }
.key-revoke:disabled { color: var(--ui-muted); cursor: not-allowed; }
.mcp-card { padding: 15px; }
.mcp-card__heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.mcp-card__heading p { margin-top: 3px; color: var(--ui-muted); font-size: 8px; }
.mcp-readonly { display: flex; align-items: center; gap: 4px; color: var(--ui-success); font-size: 8px; }
.transport-tabs { display: flex; gap: 4px; margin-top: 12px; }
.transport-tabs button { min-height: 30px; display: flex; align-items: center; gap: 5px; padding: 0 8px; color: var(--ui-muted); background: transparent; border: 0; border-radius: 6px; font-size: 8px; cursor: pointer; }
.transport-tabs button.is-active { color: var(--ui-primary); background: var(--ui-primary-soft); }
.mcp-config { overflow: hidden; margin-top: 7px; color: #DBE7F5; background: #182A42; border-radius: 8px; }
.mcp-config__bar { display: flex; align-items: center; justify-content: space-between; padding: 7px 9px; color: #AFC0D3; border-bottom: 1px solid rgba(255,255,255,.1); font-size: 8px; }
.mcp-config__bar button { display: flex; align-items: center; gap: 4px; color: #DCE7F4; background: transparent; border: 0; font-size: 8px; cursor: pointer; }
.mcp-config pre { overflow-x: auto; margin: 0; padding: 11px; font-family: var(--ui-font-mono); font-size: 8px; line-height: 14px; }
.mcp-note { display: flex; align-items: flex-start; gap: 6px; margin-top: 9px; color: var(--ui-muted); font-size: 8px; line-height: 14px; }
.mcp-note :deep(svg) { flex: none; color: var(--ui-warning); }
.mcp-note code { color: var(--ui-ink); font-family: var(--ui-font-mono); }
.mcp-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 11px; padding-top: 10px; border-top: 1px solid var(--ui-border); }
.mcp-tools > span { margin-right: 3px; color: var(--ui-muted); font-size: 8px; }
.mcp-tools code { padding: 3px 5px; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 4px; font-size: 7px; }
.key-safety, .mcp-steps { padding: 14px; }
.key-safety__icon { width: 29px; height: 29px; display: grid; place-items: center; margin-bottom: 10px; color: var(--ui-warning); background: var(--ui-surface-soft); border-radius: 8px; }
.key-safety ul { display: grid; gap: 8px; margin: 10px 0 0; padding-left: 14px; color: var(--ui-text); font-size: 8px; line-height: 13px; }
.mcp-steps > div { display: flex; gap: 8px; margin-top: 12px; }
.mcp-steps > div > span { width: 20px; height: 20px; display: grid; flex: none; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 50%; font-size: 8px; font-weight: 700; }
.mcp-steps p { display: grid; gap: 3px; }
.mcp-steps strong { color: var(--ui-ink); font-size: 8px; }
.mcp-steps small { color: var(--ui-muted); font-size: 7px; line-height: 12px; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; overflow-y: auto; padding: 20px; background: rgba(15, 35, 60, .4); }
.dialog-card { width: min(100%, 420px); padding: 20px; background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 14px; box-shadow: var(--shadow-lg); }
.dialog-card--compact { width: min(100%, 390px); }
.dialog-card__heading { display: flex; justify-content: space-between; }
.demo-icon-button { width: 32px; height: 32px; display: grid; place-items: center; color: var(--ui-muted); background: transparent; border: 0; cursor: pointer; }
.dialog-card h2 { margin: 13px 0 5px; color: var(--ui-ink); font-size: 16px; }
.dialog-card__desc { color: var(--ui-muted); font-size: 9px; line-height: 15px; }
.form-field { display: grid; gap: 5px; margin-top: 15px; }
.form-field > span { color: var(--ui-ink); font-size: 9px; font-weight: 600; }
.form-field input { min-height: 36px; padding: 0 9px; color: var(--ui-text); background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 7px; font-size: 10px; }
.form-error { color: var(--ui-danger); font-size: 9px; }
.key-warning { display: flex; gap: 7px; margin-top: 12px; padding: 9px; color: var(--ui-warning); background: var(--ui-surface-soft); border-radius: 7px; font-size: 8px; line-height: 13px; }
.key-warning :deep(svg) { flex: none; }
.dialog-card__actions { display: flex; justify-content: flex-end; gap: 7px; margin-top: 16px; }
.reveal-card { width: min(100%, 510px); }
.reveal-card__badge { display: inline-flex; align-items: center; gap: 5px; padding: 5px 8px; color: var(--ui-success); background: var(--ui-surface-soft); border-radius: 999px; font-size: 8px; }
.revealed-key { display: flex; align-items: center; gap: 8px; margin-top: 14px; padding: 9px; background: var(--ui-surface-soft); border: 1px solid var(--ui-border); border-radius: 8px; }
.revealed-key code { flex: 1; overflow-wrap: anywhere; color: var(--ui-ink); font-family: var(--ui-font-mono); font-size: 10px; user-select: all; }
.demo-key-warning { margin-top: 10px; color: var(--ui-danger); font-size: 8px; }
.demo-key-warning code { font-family: var(--ui-font-mono); }
@media (max-width: 850px) { .keys-layout { grid-template-columns: minmax(0, 1fr); } .keys-side { grid-template-columns: 1fr 1fr; } }
@media (max-width: 620px) {
  .keys-table__head { display: none; }
  .key-row { grid-template-columns: minmax(0, 1fr) auto; gap: 5px; }
  .key-row code, .key-row__used { grid-column: 1; }
  .key-state, .key-revoke { grid-column: 2; }
  .key-state { grid-row: 1; }
  .key-revoke { grid-row: 2 / span 2; }
  .keys-side { grid-template-columns: 1fr; }
}
</style>
