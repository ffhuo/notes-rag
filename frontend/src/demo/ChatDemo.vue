<script setup>
import { nextTick, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'

const props = defineProps({
  vaults: { type: Array, required: true },
  selectedVaultId: { type: Number, required: true },
})

const emit = defineEmits(['notify'])
const historyMode = ref(false)
const showSettings = ref(false)
const question = ref('')
const streamRef = ref(null)
const selectedVault = ref(String(props.selectedVaultId))
const selectedModel = ref('qwen-plus')
const topK = ref('5')
const openSources = ref({})
const messages = ref([
  { id: 1, role: 'user', content: '帮我找讲 WAL 的笔记', time: '10:46' },
  {
    id: 2,
    role: 'assistant',
    time: '10:46',
    content: 'WAL（Write-Ahead Logging，预写日志）是一种保证数据安全写入的机制：先把变更写入日志，再更新实际数据页。这样即使进程意外退出，也能通过重放日志恢复到一致状态。',
    bullets: [
      ['先记日志', '写操作先追加到 WAL，日志持久化成功后才确认事务。'],
      ['再落数据', '后台将日志中的变更写入数据文件，之后通过检查点回收旧日志。'],
      ['崩溃可恢复', '重启时回放未完成的日志，避免随机写中断造成数据不一致。'],
    ],
    sources: [
      { name: '存储基础.md', path: '工程笔记 / 数据库', color: 'blue', excerpt: 'WAL（Write-Ahead Logging，预写日志）是一种持久化方案，核心规则是先写日志，再落盘数据。系统崩溃后可以通过日志回放恢复状态。' },
      { name: '向量库设计.md', path: '工程笔记 / RAG', color: 'teal', excerpt: '索引写入成功后推进检查点；服务重启时从日志恢复尚未落盘的操作。' },
    ],
  },
])
const walAnswer = messages.value[1]

const history = [
  { id: 'wal', title: 'WAL 日志与落盘机制', date: '今天 10:46', count: '2 条消息' },
  { id: 'embed', title: 'Embedding 模型如何选择', date: '昨天 16:12', count: '6 条消息' },
  { id: 'chunk', title: 'Markdown 分块策略', date: '6 月 18 日', count: '4 条消息' },
]

function openHistory(item) {
  historyMode.value = false
  openSources.value = {}
  messages.value = item.id === 'wal'
    ? [
        { id: 1, role: 'user', content: '帮我找讲 WAL 的笔记', time: '10:46' },
        { ...walAnswer, id: 2 },
      ]
    : [
        { id: 1, role: 'user', content: item.title, time: item.date },
        { id: 2, role: 'assistant', time: item.date, content: '这是一条历史对话示例。正式版本会载入已保存的消息，并可继续追问。', bullets: [], sources: [] },
      ]
  emit('notify', `已打开「${item.title}」的演示记录`)
}

function toggleSource(id) {
  openSources.value = { ...openSources.value, [id]: !openSources.value[id] }
}

async function sendQuestion() {
  const text = question.value.trim()
  if (!text) return
  const timestamp = Date.now()
  const isWalQuestion = text.toLowerCase().includes('wal') || text.includes('预写日志')
  const answer = isWalQuestion
    ? { ...walAnswer, id: timestamp + 1, time: '刚刚' }
    : {
        id: timestamp + 1,
        role: 'assistant',
        time: '刚刚',
        content: '这个问题没有预置回答。演示没有连接真实模型服务，因此不会生成模型答案。',
        bullets: [],
        sources: [],
      }
  messages.value = [...messages.value, { id: timestamp, role: 'user', content: text, time: '刚刚' }, answer]
  question.value = ''
  await nextTick()
  if (streamRef.value) streamRef.value.scrollTop = streamRef.value.scrollHeight
  emit('notify', isWalQuestion ? '已展示 WAL 预置回答' : '未连接真实模型，展示演示提示')
}

function newConversation() {
  messages.value = []
  historyMode.value = false
  openSources.value = {}
  emit('notify', '已开始一个空白演示对话')
}

async function copyAnswer(content) {
  if (!navigator.clipboard?.writeText) {
    emit('notify', '浏览器不支持剪贴板，请手动选中回答内容')
    return
  }
  try {
    await navigator.clipboard.writeText(content)
    emit('notify', '回答已复制')
  } catch {
    emit('notify', '复制失败，请检查浏览器剪贴板权限')
  }
}
</script>

<template>
  <div class="chat-page">
    <header class="chat-page__head">
      <div class="chat-page__tabs" role="tablist">
        <button type="button" role="tab" :aria-selected="!historyMode" :class="{ 'is-active': !historyMode }" @click="historyMode = false"><AppIcon name="chat" :size="15" />对话</button>
        <button type="button" role="tab" :aria-selected="historyMode" :class="{ 'is-active': historyMode }" @click="historyMode = true"><AppIcon name="clock" :size="15" />历史记录</button>
      </div>
      <button class="button button--secondary" type="button" @click="newConversation"><AppIcon name="plus" :size="15" />新对话</button>
    </header>

    <section v-if="historyMode" class="chat-history">
      <div class="chat-history__heading"><h1>历史对话</h1><p>选择一段对话，继续查看笔记与引用。</p></div>
      <button v-for="item in history" :key="item.id" class="chat-history__row" type="button" @click="openHistory(item)">
        <span class="chat-history__icon"><AppIcon name="chat" :size="17" /></span>
        <span class="chat-history__copy"><strong>{{ item.title }}</strong><small>{{ item.date }} · {{ item.count }}</small></span>
        <AppIcon name="chevron-right" :size="16" />
      </button>
    </section>

    <section v-else class="chat-layout">
      <aside class="chat-context">
        <div class="chat-context__label">当前对话范围</div>
        <label class="context-field"><span>知识库</span><select v-model="selectedVault"><option v-for="vault in vaults" :key="vault.id" :value="String(vault.id)">{{ vault.name }}</option></select></label>
        <div class="chat-context__meta"><span><AppIcon name="file-text" :size="14" />{{ vaults.find((vault) => String(vault.id) === selectedVault)?.fileCount || 0 }} 个文件</span><span><AppIcon name="inbox" :size="14" />已索引内容</span></div>
        <div class="chat-context__tip"><AppIcon name="info" :size="14" /><p>回答基于选定 Vault 的索引，并在下方标出来源。</p></div>
      </aside>

      <div class="chat-conversation">
        <div ref="streamRef" class="chat-stream" aria-label="对话消息">
          <div v-if="!messages.length" class="chat-empty"><span><AppIcon name="chat" :size="22" /></span><strong>开始一段新对话</strong><p>输入问题，演示中可查看预置 WAL 回答与来源引用。</p></div>
          <template v-for="message in messages" :key="message.id">
            <div v-if="message.role === 'user'" class="chat-message chat-message--user">
              <div class="chat-message__body"><div class="chat-message__meta"><strong>你</strong><time>{{ message.time }}</time></div><div class="chat-user-bubble">{{ message.content }}</div></div>
              <span class="chat-avatar chat-avatar--user">G</span>
            </div>
            <div v-else class="chat-message chat-message--assistant">
              <span class="chat-avatar chat-avatar--assistant"><AppIcon name="chat" :size="16" /></span>
              <div class="chat-message__body">
                <div class="chat-message__meta"><strong>notes-rag</strong><span v-if="message.sources?.length" class="chat-answer-tag">基于 {{ message.sources.length }} 条笔记</span><time>{{ message.time }}</time></div>
                <article class="chat-answer">
                  <p>{{ message.content }}</p>
                  <div v-if="message.bullets?.length" class="chat-answer__bullets">
                    <div v-for="(bullet, index) in message.bullets" :key="bullet[0]"><span>{{ String(index + 1).padStart(2, '0') }}</span><p><strong>{{ bullet[0] }}</strong>：{{ bullet[1] }}</p></div>
                  </div>
                  <div v-if="message.sources?.length" class="chat-answer__note"><AppIcon name="zap" :size="14" />常见于数据库事务、本地向量库和需要崩溃恢复的存储系统。</div>
                  <section v-if="message.sources?.length" class="chat-sources">
                    <div class="chat-sources__title"><span><AppIcon name="file-text" :size="15" />引用来源</span><small>{{ message.sources.length }} 个片段</small></div>
                    <article v-for="(source, index) in message.sources" :key="source.name" class="citation" :class="`citation--${source.color}`">
                      <button class="citation__row" type="button" :aria-expanded="!!openSources[source.name]" @click="toggleSource(source.name)">
                        <span class="citation__index">{{ String(index + 1).padStart(2, '0') }}</span>
                        <span class="citation__file"><strong>{{ source.name }}</strong><small>{{ source.path }}</small></span>
                        <span class="citation__relevance">{{ index === 0 ? '高相关' : '相关' }}</span>
                        <AppIcon :name="openSources[source.name] ? 'chevron-up' : 'chevron-down'" :size="14" />
                      </button>
                      <p v-if="openSources[source.name]" class="citation__excerpt">“{{ source.excerpt }}”</p>
                    </article>
                  </section>
                  <div class="chat-answer__actions"><button type="button" @click="copyAnswer(message.content)"><AppIcon name="copy" :size="14" />复制</button><button type="button" @click="emit('notify', '演示中不会启动语音合成')"><AppIcon name="volume" :size="14" />朗读</button><span v-if="message.sources?.length"><AppIcon name="check" :size="13" />答案引用自 Vault</span></div>
                </article>
              </div>
            </div>
          </template>
        </div>

        <div class="chat-composer">
          <div v-if="showSettings" class="chat-settings">
            <label><span>模型</span><select v-model="selectedModel"><option value="qwen-plus">qwen-plus · LLM</option><option value="gpt-4o-mini">gpt-4o-mini · LLM</option></select></label>
            <label><span>Vault</span><select v-model="selectedVault"><option v-for="vault in vaults" :key="vault.id" :value="String(vault.id)">{{ vault.name }}</option></select></label>
            <label><span>检索条数</span><select v-model="topK"><option>3</option><option>5</option><option>10</option></select></label>
          </div>
          <form @submit.prevent="sendQuestion">
            <textarea v-model="question" rows="2" aria-label="提问内容" placeholder="给笔记提问…（Enter 发送，Shift+Enter 换行）" @keydown.enter.exact.prevent="sendQuestion"></textarea>
            <div class="chat-composer__bar">
              <div><button class="chat-tool" type="button" :aria-expanded="showSettings" aria-label="模型与检索范围" @click="showSettings = !showSettings"><AppIcon name="models" :size="16" /></button><button class="chat-tool" type="button" aria-label="语音输入" title="演示不会启动麦克风" @click="emit('notify', '演示模式不会请求麦克风；真实语音转写由 ASR 配置提供')"><AppIcon name="mic" :size="16" /></button><span class="chat-composer__hint">仅展示示例内容，不会请求真实模型</span></div>
              <button class="button button--primary chat-send" type="submit" :disabled="!question.trim()"><AppIcon name="send" :size="15" />发送</button>
            </div>
          </form>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.chat-page { height: 100%; min-height: 0; display: flex; flex-direction: column; }
.chat-page__head { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--ui-border); }
.chat-page__tabs { display: flex; gap: 5px; }
.chat-page__tabs button { min-height: 34px; display: flex; align-items: center; gap: 6px; padding: 0 10px; color: var(--ui-muted); background: transparent; border: 0; border-radius: 7px; font-size: 10px; cursor: pointer; }
.chat-page__tabs button.is-active { color: var(--ui-primary); background: var(--ui-primary-soft); font-weight: 700; }
.button { min-height: 36px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 0 11px; color: var(--ui-text); background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 8px; font-size: 10px; font-weight: 600; cursor: pointer; }
.button:hover { background: var(--ui-surface-soft); }
.chat-layout { min-height: 0; flex: 1; display: grid; grid-template-columns: 190px minmax(0, 1fr); gap: 17px; padding-top: 15px; }
.chat-context { align-self: start; padding: 13px; background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 11px; }
.chat-context__label { margin-bottom: 12px; color: var(--ui-muted); font-size: 9px; font-weight: 700; }
.context-field { display: grid; gap: 5px; }
.context-field > span, .chat-settings label > span { color: var(--ui-muted); font-size: 9px; }
.context-field select, .chat-settings select { min-width: 0; height: 34px; padding: 0 7px; color: var(--ui-ink); background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 7px; font-size: 9px; }
.chat-context__meta { display: grid; gap: 8px; margin-top: 12px; padding-top: 11px; border-top: 1px solid var(--ui-border); }
.chat-context__meta span { display: flex; align-items: center; gap: 6px; color: var(--ui-muted); font-size: 9px; }
.chat-context__tip { display: flex; align-items: flex-start; gap: 6px; margin-top: 14px; padding: 8px; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 7px; }
.chat-context__tip p { color: var(--ui-text); font-size: 8px; line-height: 13px; }
.chat-conversation { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.chat-stream { min-height: 0; flex: 1; overflow-y: auto; padding: 3px 8px 15px; overscroll-behavior: contain; }
.chat-message { display: flex; align-items: flex-start; gap: 9px; margin-bottom: 17px; }
.chat-message--user { justify-content: flex-end; }
.chat-message__body { width: min(100%, 680px); min-width: 0; }
.chat-message--user .chat-message__body { display: flex; align-items: flex-end; flex-direction: column; }
.chat-message__meta { display: flex; align-items: center; gap: 8px; min-height: 23px; margin-bottom: 5px; }
.chat-message--user .chat-message__meta { justify-content: flex-end; }
.chat-message__meta strong { color: var(--ui-ink); font-size: 10px; }
.chat-message__meta time { color: var(--ui-muted); font-size: 8px; }
.chat-answer-tag { padding: 3px 6px; color: var(--ui-success); background: var(--ui-surface-soft); border-radius: 999px; font-size: 8px; }
.chat-avatar { width: 27px; height: 27px; display: grid; flex: none; place-items: center; border-radius: 9px; }
.chat-avatar--user { color: var(--ui-primary); background: var(--ui-primary-soft); font-size: 10px; font-weight: 700; }
.chat-avatar--assistant { color: var(--color-primary-contrast); background: var(--ui-primary); }
.chat-user-bubble { max-width: min(100%, 390px); padding: 10px 13px; color: var(--ui-ink); background: var(--ui-primary-soft); border: 1px solid var(--ui-border); border-radius: 12px 12px 3px 12px; font-size: 11px; }
.chat-answer { padding: 14px 16px; background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 3px 12px 12px; }
.chat-answer > p { color: var(--ui-text); font-size: 11px; line-height: 19px; }
.chat-answer__bullets { display: grid; gap: 7px; margin-top: 11px; }
.chat-answer__bullets > div { display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 7px; }
.chat-answer__bullets > div > span { color: var(--ui-primary); font-size: 8px; font-weight: 700; }
.chat-answer__bullets p { color: var(--ui-text); font-size: 10px; line-height: 16px; }
.chat-answer__bullets strong { color: var(--ui-ink); }
.chat-answer__note { display: flex; align-items: center; gap: 6px; margin-top: 11px; padding: 8px; color: var(--ui-warning); background: var(--ui-surface-soft); border-radius: 7px; font-size: 9px; }
.chat-sources { margin-top: 12px; border-top: 1px solid var(--ui-border); }
.chat-sources__title { display: flex; align-items: center; justify-content: space-between; padding: 10px 0 7px; }
.chat-sources__title > span { display: flex; align-items: center; gap: 6px; color: var(--ui-ink); font-size: 9px; font-weight: 700; }
.chat-sources__title small { color: var(--ui-muted); font-size: 8px; }
.citation { margin-top: 6px; padding: 7px 9px; border-left: 3px solid var(--ui-primary); border-radius: 0 8px 8px 0; background: var(--ui-primary-soft); }
.citation--teal { border-color: var(--ui-success); background: var(--color-success-soft); }
.citation__row { width: 100%; min-height: 30px; display: flex; align-items: center; gap: 8px; padding: 0; text-align: left; color: var(--ui-muted); background: transparent; border: 0; cursor: pointer; }
.citation__index { color: var(--ui-primary); font-size: 8px; font-weight: 700; }
.citation--teal .citation__index, .citation--teal .citation__relevance { color: var(--ui-success); }
.citation__file { display: grid; flex: 1; gap: 2px; min-width: 0; }
.citation__file strong { overflow: hidden; color: var(--ui-ink); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.citation__file small { overflow: hidden; color: var(--ui-muted); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.citation__relevance { color: var(--ui-primary); font-size: 8px; white-space: nowrap; }
.citation__excerpt { margin: 5px 0 2px 21px; color: var(--ui-text); font-size: 9px; line-height: 15px; }
.chat-answer__actions { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.chat-answer__actions button, .chat-answer__actions > span { display: inline-flex; align-items: center; gap: 4px; padding: 0; color: var(--ui-muted); background: transparent; border: 0; font-size: 8px; cursor: pointer; }
.chat-answer__actions > span { margin-left: auto; color: var(--ui-success); cursor: default; }
.chat-empty { display: grid; justify-items: center; align-content: center; height: 100%; color: var(--ui-muted); text-align: center; }
.chat-empty > span { width: 42px; height: 42px; display: grid; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 14px; }
.chat-empty strong { margin-top: 10px; color: var(--ui-ink); font-size: 12px; }
.chat-empty p { margin-top: 5px; font-size: 9px; }
.chat-composer { flex: none; padding: 10px 12px; background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 12px; box-shadow: var(--shadow-sm); }
.chat-settings { display: grid; grid-template-columns: 1fr 1.3fr .7fr; gap: 8px; padding-bottom: 9px; border-bottom: 1px solid var(--ui-border); }
.chat-settings label { display: grid; gap: 4px; min-width: 0; }
.chat-settings select { width: 100%; }
.chat-composer textarea { width: 100%; min-height: 40px; resize: none; padding: 5px 2px; color: var(--ui-ink); background: transparent; border: 0; outline: 0; font-size: 10px; line-height: 16px; }
.chat-composer textarea::placeholder { color: var(--ui-muted); }
.chat-composer__bar, .chat-composer__bar > div { display: flex; align-items: center; }
.chat-composer__bar { justify-content: space-between; gap: 8px; padding-top: 7px; border-top: 1px solid var(--ui-border); }
.chat-composer__bar > div { gap: 5px; }
.chat-tool { width: 29px; height: 29px; display: grid; place-items: center; color: var(--ui-muted); background: transparent; border: 0; border-radius: 7px; cursor: pointer; }
.chat-tool:hover, .chat-tool[aria-expanded="true"] { color: var(--ui-primary); background: var(--ui-primary-soft); }
.chat-composer__hint { color: var(--ui-muted); font-size: 8px; }
.button--primary { color: var(--color-primary-contrast); background: var(--ui-primary); border: 0; }
.chat-send { min-height: 32px; }
.chat-send:disabled { opacity: .5; cursor: not-allowed; }
.chat-history { max-width: 760px; margin: 22px auto 0; }
.chat-history__heading { margin-bottom: 13px; }
.chat-history__heading h1 { color: var(--ui-ink); font-size: 18px; }
.chat-history__heading p { margin-top: 4px; color: var(--ui-muted); font-size: 10px; }
.chat-history__row { width: 100%; min-height: 62px; display: flex; align-items: center; gap: 10px; padding: 9px 12px; text-align: left; color: var(--ui-muted); background: var(--ui-surface); border: 1px solid var(--ui-border); border-bottom: 0; cursor: pointer; }
.chat-history__row:first-of-type { border-radius: 10px 10px 0 0; }
.chat-history__row:last-child { border-bottom: 1px solid var(--ui-border); border-radius: 0 0 10px 10px; }
.chat-history__row:hover { background: var(--ui-surface-soft); }
.chat-history__icon { width: 30px; height: 30px; display: grid; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 8px; }
.chat-history__copy { display: grid; flex: 1; gap: 3px; }
.chat-history__copy strong { color: var(--ui-ink); font-size: 10px; }
.chat-history__copy small { color: var(--ui-muted); font-size: 8px; }
@media (max-width: 800px) {
  .chat-layout { grid-template-columns: minmax(0, 1fr); gap: 9px; }
  .chat-context { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 7px 9px; }
  .chat-context__label { width: 100%; margin: 0; }
  .context-field { min-width: min(230px, 100%); flex: 1; grid-template-columns: auto minmax(0, 1fr); align-items: center; }
  .chat-context__meta, .chat-context__tip { display: none; }
  .chat-stream { padding-right: 1px; padding-left: 1px; }
}
@media (max-width: 480px) {
  .chat-page__head { padding-bottom: 8px; }
  .chat-layout { padding-top: 8px; }
  .chat-message__body { width: min(100%, 92%); }
  .chat-answer { padding: 10px; }
  .chat-settings { grid-template-columns: 1fr; }
  .chat-settings label { grid-template-columns: 55px minmax(0, 1fr); align-items: center; }
  .chat-composer__hint { display: none; }
}
</style>
