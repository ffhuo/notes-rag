<script setup>
// 问答页（T3.5 / 规范 §5.4）—— 检索增强问答，流式渲染 + 来源折叠。
//
// 布局走「文档流」：回答整宽（阅读宽度优先，Markdown 排版不被窄气泡挤压），
// 提问右对齐限宽白卡（保留「这是我问的」身份感）；来源折叠在回答内部。
//
// 三件事必须做对：
//  1) 流式：逐 token 追加渲染，生成中在文字尾部显示光标 —— 否则用户不知道它在动。
//     流式期间只能走纯文本（光标要贴在最后一个字符后面），流结束后才换 Markdown 渲染
//  2) 中断：请求可随时停止；**断流保留已生成的文字**并标注「生成已中断」，
//     把已经花掉的 token 和时间丢掉是最差的一种失败方式（§10.2 风险项）
//  3) 来源：检索命中在流结束后折叠展示，可逐条展开片段预览 —— 只给标题和路径，
//     用户没法判断引用是否真的支撑了这句话
//
// 顶部只有「当前对话 / 历史记录」两态（history 视图占主区），配置选择收进输入区左侧的
// 图标按钮里：选择器是低频操作，常驻顶部等于每屏都在替用户占位置。
//
// 语音（可选增强，浏览器不支持就不出现对应按钮）：
//  · 录入 = 录一段 → 后端 ASR 转写（recorder.js + audioApi）→ 文本填进输入框，**不自动发送**：
//    后端按 kind=asr 的模型配置转发，**没配就禁用麦克风**（未配置即不支持语音输入）
//    识别难免有错字，直接发出去等于替用户做了决定
//  · 播放 = 浏览器 speechSynthesis 本地合成（speech.js），音频不出本机
//
// 滚动遵循「跟随而不是抢夺」：只在用户本来就贴底时跟随新内容，上翻阅读时给回到底部的入口。
//
// 传输细节全部在 transport/chat.js（T5.1）：本页不认识 SSE 帧格式，换端只换那一个文件。
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { audioApi, conversationsApi, modelsApi, vaultsApi } from '../api'
import { copyText } from '../clipboard'
import { relativeTime } from '../jobs'
import { isMarkdownPath, toPlainText } from '../markdown'
import { describeRecorderError, isRecorderSupported, startRecording } from '../recorder'
import { isSpeechSupported, speak, stopSpeaking } from '../speech'
import { chatTransport } from '../transport/chat'
import { toast } from '../toast'
import AppButton from './AppButton.vue'
import AppEmptyState from './AppEmptyState.vue'
import AppIcon from './AppIcon.vue'
import AppMarkdown from './AppMarkdown.vue'
import AppSelect from './AppSelect.vue'
import AppTextarea from './AppTextarea.vue'

const TOPK_OPTIONS = [
  { value: '3', label: '检索 3 条' },
  { value: '5', label: '检索 5 条' },
  { value: '10', label: '检索 10 条' },
]

const input = ref('')
const messages = ref([])
const streaming = ref(false)
const llmProfile = ref('')
const vaultId = ref('')
const topK = ref('5')
const conversationId = ref('')
/** 来源分组展开态（「来源（N）」那一层）。 */
const sourcesOpen = ref({})
/** 来源单条展开态（看该条的片段预览）；key 是 `${消息id}:${序号}`。 */
const sourceOpen = ref({})
const scrollRef = ref(null)
/** 用户是否停在流底部：决定新内容要不要跟随（见 scrollToBottom）。 */
const atBottom = ref(true)

/** 主区显示哪一屏：chat = 当前对话，history = 历史记录列表。 */
const mode = ref('chat')
/** 输入区左侧配置条是否展开（默认收起，只留一个图标按钮）。 */
const toolbarOpen = ref(false)

const history = ref([])
const historyLoading = ref(false)
const loadingConv = ref(false)

/* ---------- 语音 ---------- */
// 能力探测只在挂载时做一次：不支持的浏览器直接不渲染对应按钮，好过点了才报「不支持」。
const recorderOk = isRecorderSupported()
const speechOk = isSpeechSupported()
/** 单段录音上限（秒）：超了自动收尾，避免用户忘停传上去几十 MB。 */
const MAX_RECORD_SECS = 120

const recording = ref(false)
const recordSecs = ref(0)
const transcribing = ref(false)
/** 正在朗读的回答 id（同一时刻只允许一条）。 */
const speakingId = ref(null)

let recorder = null
let recordTimer = null

/** 贴底容差：scrollHeight 与 clientHeight 有小数误差，不留容差会永远判成「没贴底」。 */
const BOTTOM_EPS = 24

const llmModels = ref([])
const vaults = ref([])
const asrModels = ref([])

/** 是否配置了语音识别模型（kind=asr）：没配就不支持语音输入。 */
const asrOk = computed(() => asrModels.value.length > 0)
/** 麦克风按钮的 title：未配置时给可操作指引，而不是让它看起来只是「点不动」。 */
const asrTitle = computed(() => {
  if (!asrOk.value) return '未配置语音识别模型：请到「模型」页新增一个 kind=asr 的配置'
  return recording.value ? '结束录音并转写' : '点一下开始录音'
})

let seq = 0
let current = null // 当前流的 { abort }

const llmOptions = computed(() =>
  llmModels.value.map((m) => ({ value: m.name, label: `${m.name}（${m.model}）` })),
)
const vaultOptions = computed(() => vaults.value.map((v) => ({ value: String(v.id), label: v.name })))

onMounted(async () => {
  try {
    const [models, vaultList, asrList] = await Promise.all([
      modelsApi.list('llm'),
      vaultsApi.list(),
      // asr 拿不到时按「未配置」处理，不拖垮整个页面的模型 / vault 加载
      modelsApi.list('asr').catch(() => []),
    ])
    llmModels.value = models
    vaults.value = vaultList
    asrModels.value = asrList
    const def = models.find((m) => m.is_default)
    if (def) llmProfile.value = def.name
    if (vaultList.length === 1) vaultId.value = String(vaultList[0].id)
  } catch {
    toast.error('无法获取模型 / vault 列表，请检查后端与鉴权设置')
  }
})

// 离开页面必须收拾干净：麦克风不关，浏览器标签上的录音标记会一直亮；
// 朗读不停，切到别的模块还会听见声音
onUnmounted(() => {
  cancelRecord(true)
  stopSpeaking()
})

/* ---------- 消息更新：整对象替换，保证深层变更也能触发渲染 ---------- */

function appendMessage(msg) {
  messages.value = [...messages.value, msg]
  return msg.id
}

function patchMessage(id, fields) {
  const i = messages.value.findIndex((m) => m.id === id)
  if (i === -1) return
  messages.value[i] = { ...messages.value[i], ...fields }
}

function appendToken(id, text) {
  const i = messages.value.findIndex((m) => m.id === id)
  if (i === -1) return
  messages.value[i] = { ...messages.value[i], content: messages.value[i].content + text }
  scrollToBottom()
}

function onStreamScroll() {
  const el = scrollRef.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_EPS
}

/**
 * 跟随到底部。
 *
 * 默认**只在用户本来就贴底时跟随**：原来的实现每收到一个 token 就无条件拉到底，
 * 用户上翻读上文时会被反复拽回来，等于没法读。
 * force=true 只用于两个必须到底的场景：自己刚发出提问、点了「回到底部」。
 */
function scrollToBottom(force = false) {
  if (!force && !atBottom.value) return
  requestAnimationFrame(() => {
    const el = scrollRef.value
    if (!el) return
    el.scrollTop = el.scrollHeight
    atBottom.value = true
  })
}

/* ---------- 发送 / 重新生成 / 停止 ---------- */

function onEnter(event) {
  // Shift+Enter 换行由输入框自己处理
  if (event?.shiftKey) return
  event?.preventDefault?.()
  send()
}

function send() {
  const q = input.value.trim()
  if (!q || streaming.value) return
  haltSpeaking() // 已经在念上一条了：继续念会让用户听不出哪句是新的

  appendMessage({
    id: (seq += 1),
    role: 'user',
    content: q,
    sources: [],
    streaming: false,
    interrupted: false,
    error: '',
    model: '',
  })

  // 参数快照挂在回答上：重新生成要用「当时」的模型/vault/topK，
  // 否则用户换过选择器后再点重新生成，会悄悄换一套参数。
  const params = {
    query: q,
    top_k: Number(topK.value),
    vault_id: vaultId.value || undefined,
    llm_profile: llmProfile.value || undefined,
  }
  const answerId = appendMessage({
    id: (seq += 1),
    role: 'assistant',
    content: '',
    sources: [],
    streaming: true,
    interrupted: false,
    error: '',
    model: llmProfile.value, // 快照当次使用的模型：中途换模型后，历史回答仍显示它当时是谁答的
    ...params,
  })
  input.value = ''
  ask(params, answerId)
}

/**
 * 发起一次流式回答。send 与 regenerate 共用：两者的差别只在
 * 「建新消息」还是「复用已有消息」，传输与回调完全一样。
 */
function ask(params, answerId) {
  streaming.value = true
  scrollToBottom(true)

  current = chatTransport.stream(
    { ...params, conversation_id: conversationId.value || undefined },
    {
      onSources: (items) => patchMessage(answerId, { sources: items }),
      onToken: (text) => appendToken(answerId, text),
      onDone: (data) => {
        if (data?.conversation_id) conversationId.value = String(data.conversation_id)
        finish(answerId, {})
      },
      onError: (e) => {
        const reason =
          e.status === 409
            ? '该 vault 还没有可检索的索引，请先到知识库页同步或重建索引。'
            : e.status === 404
              ? '所选 vault 不存在或不属于当前账号。'
              : e.message
        finish(answerId, { error: reason })
        toast.error('问答未能完成')
      },
      onAbort: () => finish(answerId, { interrupted: true }),
    },
  )
}

/**
 * 重新生成：用该条回答的快照参数重发，界面上**复用同一条**（清空重流）。
 *
 * 注意存储侧的差别：后端每次回答都会 append 一条 messages 记录，
 * 所以重新生成在库里是「多了一条 assistant」，不是覆盖。
 */
function regenerate(m) {
  if (streaming.value || !m.query) return
  haltSpeaking()
  sourceOpen.value = {}
  patchMessage(m.id, { content: '', sources: [], streaming: true, interrupted: false, error: '' })
  ask(
    { query: m.query, top_k: m.top_k, vault_id: m.vault_id, llm_profile: m.llm_profile },
    m.id,
  )
}

function finish(id, fields) {
  patchMessage(id, { streaming: false, ...fields })
  streaming.value = false
  current = null
  // 流结束后正文从纯文本换成 Markdown 渲染，高度会变 —— 贴底状态要跟着重算一次
  nextTick(() => scrollToBottom())
}

function stop() {
  if (!current) return
  current.abort()
}

/** 是否最后一条回答：重新生成只对它开放（改中间某轮等于让后续回答失去上下文）。 */
function isLastAssistant(m) {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    if (messages.value[i].role === 'assistant') return messages.value[i].id === m.id
  }
  return false
}

async function copyAnswer(m) {
  const ok = await copyText(m.content)
  if (ok) toast.success('已复制回答')
  else toast.error('复制失败，可手动选择文本')
}

/* ---------- 语音录入 ---------- */

function fmtSecs(n) {
  const m = Math.floor(n / 60)
  const s = n % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function clearRecordTimer() {
  if (recordTimer) clearInterval(recordTimer)
  recordTimer = null
}

async function startRecord() {
  if (recording.value || transcribing.value || streaming.value) return
  if (!asrOk.value) {
    // 按钮本身已 disable，这里再兜一层：配置可能是在本页挂载后被删掉的
    toast.error('未配置语音识别模型：请到「模型」页新增一个 kind=asr 的配置')
    return
  }
  haltSpeaking() // 边听自己的朗读边说话会互相干扰，先停掉
  try {
    recorder = await startRecording()
  } catch (e) {
    recorder = null
    toast.error(describeRecorderError(e))
    return
  }
  recording.value = true
  recordSecs.value = 0
  clearRecordTimer()
  recordTimer = setInterval(() => {
    recordSecs.value += 1
    if (recordSecs.value >= MAX_RECORD_SECS) {
      toast.info(`单段录音最多 ${MAX_RECORD_SECS} 秒，已自动结束`)
      stopAndTranscribe()
    }
  }, 1000)
}

/** 录音中转写：先结束录音拿到音频，再上传识别，结果追加进输入框。 */
async function stopAndTranscribe() {
  if (!recorder) return
  const rec = recorder
  recorder = null
  recording.value = false
  clearRecordTimer()

  const clip = await rec.stop()
  // stop() 返回 null = 这段已被取消（cancelRecord 先走一步），什么都不做
  if (!clip) return

  transcribing.value = true
  try {
    const r = await audioApi.transcribe(clip.blob, clip.filename)
    const text = (r?.text || '').trim()
    if (!text) {
      toast.info('没有识别到内容，靠近麦克风再说一次试试')
      return
    }
    // 追加而不是覆盖：用户可能先说一句、手打一句、再说一句
    const before = input.value.trim()
    input.value = before ? `${before} ${text}` : text
    toast.success('已转成文字，确认后发送')
  } catch (e) {
    toast.error(e.status === 409 ? e.message : `语音识别失败：${e.message}`)
  } finally {
    transcribing.value = false
  }
}

/** 丢弃这段录音（麦克风照样释放，只是不上传）；quiet 用于卸载时静默收尾。 */
function cancelRecord(quiet = false) {
  if (!recorder) return
  recorder.cancel()
  recorder = null
  recording.value = false
  clearRecordTimer()
  if (!quiet) toast.info('已取消这段录音')
}

/* ---------- 朗读 ---------- */

function haltSpeaking() {
  if (!speakingId.value) return
  stopSpeaking()
  speakingId.value = null
}

function toggleSpeak(m) {
  if (speakingId.value === m.id) {
    haltSpeaking()
    return
  }
  stopSpeaking()
  // 先转纯文本：Markdown 标记与代码块念出来只是噪音（见 markdown.js 的 toPlainText）
  const ok = speak(toPlainText(m.content), {
    onEnd: () => {
      if (speakingId.value === m.id) speakingId.value = null
    },
  })
  if (!ok) {
    toast.error('当前浏览器不支持朗读')
    return
  }
  speakingId.value = m.id
}

function newConversation() {
  if (streaming.value) stop()
  cancelRecord()
  haltSpeaking()
  messages.value = []
  sourcesOpen.value = {}
  sourceOpen.value = {}
  conversationId.value = ''
  atBottom.value = true
  mode.value = 'chat'
  toast.info('已开始新对话')
}

function toggleSources(id) {
  sourcesOpen.value = { ...sourcesOpen.value, [id]: !sourcesOpen.value[id] }
}

function isSourceOpen(msgId, index) {
  return !!sourceOpen.value[`${msgId}:${index}`]
}

function toggleSource(msgId, index) {
  const key = `${msgId}:${index}`
  sourceOpen.value = { ...sourceOpen.value, [key]: !sourceOpen.value[key] }
}

/* ---------- 历史记录 ---------- */

async function loadHistory() {
  historyLoading.value = true
  try {
    history.value = await conversationsApi.list()
  } catch {
    toast.error('无法获取历史对话')
  } finally {
    historyLoading.value = false
  }
}

function openHistory() {
  mode.value = 'history'
  loadHistory()
}

/** 打开一条历史会话：回填消息并切回对话视图，之后继续提问会追加到该会话。 */
async function openConversation(id) {
  if (loadingConv.value) return
  loadingConv.value = true
  try {
    const rows = await conversationsApi.messages(id)
    if (streaming.value) stop()
    cancelRecord()
    haltSpeaking()
    messages.value = rows.map((r) => ({
      // 历史消息 id 与本地自增 seq 分属两个空间，加前缀避免撞号
      id: `h-${r.id}`,
      role: r.role,
      content: r.content,
      sources: [], // messages 表不存来源，历史回看没有引用片段（已知边界）
      streaming: false,
      interrupted: false,
      error: '',
      model: '',
      historical: true,
    }))
    conversationId.value = String(id)
    sourcesOpen.value = {}
    sourceOpen.value = {}
    toolbarOpen.value = false
    atBottom.value = true
    mode.value = 'chat'
    nextTick(() => scrollToBottom(true))
  } catch {
    toast.error('无法打开该对话')
  } finally {
    loadingConv.value = false
  }
}
</script>

<template>
  <section class="chat">
    <!-- 顶部：主区在两屏之间切换（历史是独立一屏，不做常驻侧栏） -->
    <div class="chat__head">
      <div class="chat__seg">
        <button
          type="button"
          class="chat__seg-btn"
          :class="{ 'is-on': mode === 'chat' }"
          @click="mode = 'chat'"
        >
          <AppIcon name="chat" :size="16" />
          <span>对话</span>
        </button>
        <button
          type="button"
          class="chat__seg-btn"
          :class="{ 'is-on': mode === 'history' }"
          @click="openHistory"
        >
          <AppIcon name="clock" :size="16" />
          <span>历史记录</span>
        </button>
      </div>

      <AppButton variant="secondary" size="sm" icon="plus" @click="newConversation">新对话</AppButton>
    </div>

    <!-- ===== 历史记录 ===== -->
    <div v-if="mode === 'history'" class="chat__history">
      <p v-if="historyLoading" class="chat__history-hint">正在加载…</p>

      <AppEmptyState
        v-else-if="!history.length"
        icon="clock"
        title="还没有历史对话"
        description="每次提问都会自动保存，之后可以在这里回看并接着追问。"
      />

      <ul v-else class="chat__history-list">
        <li v-for="c in history" :key="c.id">
          <button
            type="button"
            class="chat__history-item"
            :disabled="loadingConv"
            @click="openConversation(c.id)"
          >
            <span class="chat__history-item-title" :title="c.title">{{ c.title }}</span>
            <span class="chat__history-item-meta">
              <AppIcon name="clock" :size="14" />
              <span>{{ relativeTime(c.created_at) }}</span>
              <span class="chat__dot">·</span>
              <span>{{ c.message_count }} 条消息</span>
            </span>
          </button>
        </li>
      </ul>
    </div>

    <!-- ===== 对话 ===== -->
    <template v-else>
      <div class="chat__stream-wrap">
        <div ref="scrollRef" class="chat__stream" @scroll="onStreamScroll">
          <AppEmptyState
            v-if="!messages.length"
            icon="chat"
            title="开始提问"
            description="回答会先在你的 vault 里检索相关资料，再据此生成；来源在回答下方可展开查看。"
          />

          <div
            v-for="m in messages"
            :key="m.id"
            class="chat__row"
            :class="`is-${m.role}`"
          >
            <div class="chat__bubble" :class="`is-${m.role}`">
              <span v-if="m.role === 'user'" class="chat__who">你</span>

              <div v-if="m.role === 'assistant'" class="chat__meta">
                <span class="chat__tag">AI 回答</span>
                <span class="chat__model">
                  {{ m.model || (m.historical ? '模型未记录' : '默认模型') }}
                </span>
              </div>

              <p v-if="m.role === 'user'" class="chat__text">{{ m.content }}</p>

              <template v-else>
                <!-- 流式期间只能走纯文本（光标要贴在最后一个字符后面），结束后换 Markdown 渲染 -->
                <AppMarkdown v-if="!m.streaming && m.content" :source="m.content" />
                <p v-else-if="m.streaming" class="chat__text">
                  <template v-if="m.content">{{ m.content }}</template><span class="chat__caret"></span>
                </p>
              </template>

              <p v-if="m.interrupted" class="chat__note is-warn">
                <AppIcon name="alert" :size="16" />
                <span>生成已中断，以上为已生成的内容。</span>
              </p>
              <p v-if="m.error" class="chat__note is-danger">
                <AppIcon name="alert" :size="16" />
                <span>{{ m.error }}</span>
              </p>

              <!-- 回答工具条：默认隐去，鼠标移入或键盘聚焦时出现（触屏常显） -->
              <div v-if="m.role === 'assistant' && !m.streaming && m.content" class="chat__actions">
                <button
                  v-if="speechOk"
                  type="button"
                  class="chat__action"
                  :class="{ 'is-on': speakingId === m.id }"
                  :title="speakingId === m.id ? '停止朗读' : '朗读这条回答'"
                  @click="toggleSpeak(m)"
                >
                  <AppIcon :name="speakingId === m.id ? 'volume-x' : 'volume'" :size="16" />
                  <span>{{ speakingId === m.id ? '停止' : '朗读' }}</span>
                </button>
                <button type="button" class="chat__action" title="复制回答" @click="copyAnswer(m)">
                  <AppIcon name="copy" :size="16" />
                  <span>复制</span>
                </button>
                <button
                  v-if="isLastAssistant(m) && m.query"
                  type="button"
                  class="chat__action"
                  :disabled="streaming"
                  title="用同样的参数重新回答"
                  @click="regenerate(m)"
                >
                  <AppIcon name="refresh" :size="16" />
                  <span>重新生成</span>
                </button>
              </div>

              <!-- 来源：流结束后折叠展示，展开后可逐条看片段预览 -->
              <div v-if="m.role === 'assistant' && m.sources.length" class="chat__sources">
                <AppButton
                  variant="ghost"
                  size="sm"
                  :icon="sourcesOpen[m.id] ? 'chevron-down' : 'chevron-right'"
                  @click="toggleSources(m.id)"
                >
                  来源（{{ m.sources.length }}）
                </AppButton>

                <ol v-if="sourcesOpen[m.id]" class="chat__source-list">
                  <li v-for="(s, si) in m.sources" :key="`${s.note_id}-${si}`" class="chat__source">
                    <span class="chat__source-no">{{ si + 1 }}</span>
                    <div class="chat__source-body">
                      <button
                        type="button"
                        class="chat__source-toggle"
                        :aria-expanded="isSourceOpen(m.id, si)"
                        @click="toggleSource(m.id, si)"
                      >
                        <span class="chat__source-title" :title="s.title">{{ s.title || '（无标题）' }}</span>
                        <span class="chat__score">{{ s.score.toFixed(3) }}</span>
                        <AppIcon :name="isSourceOpen(m.id, si) ? 'chevron-down' : 'chevron-right'" :size="16" />
                      </button>
                      <div class="chat__source-path" :title="s.file_path">{{ s.file_path }}</div>
                      <div
                        v-if="isSourceOpen(m.id, si)"
                        class="chat__source-excerpt"
                        :class="{ 'chat__source-excerpt--plain': !isMarkdownPath(s.file_path) }"
                      >
                        <AppMarkdown v-if="isMarkdownPath(s.file_path)" :source="s.content" />
                        <template v-else>{{ s.content }}</template>
                      </div>
                    </div>
                  </li>
                </ol>
              </div>
            </div>
          </div>
        </div>

        <!-- 上翻阅读时不再被拽回底部，改为显式给一个入口 -->
        <AppButton
          v-if="!atBottom && messages.length"
          class="chat__jump"
          variant="secondary"
          size="sm"
          icon="chevron-down"
          @click="scrollToBottom(true)"
        >
          回到底部
        </AppButton>
      </div>

      <!-- 输入区贴底：Enter 发送 / Shift+Enter 换行；生成中「发送」转「停止」 -->
      <div class="chat__composer-wrap">
        <!--
          整块一张卡（composer）：文本框、工具图标、发送按钮同处一个圆角容器，
          而不是「输入框 + 按钮」两个并列方块 —— 后者看起来像表单而不是对话输入。
        -->
        <div class="chat__box">
          <!-- 配置条：默认收起，点左下角图标展开；不做浮层，省掉「点外部关闭」那套状态 -->
          <div v-if="toolbarOpen" class="chat__config">
            <AppSelect
              v-model="llmProfile"
              class="chat__select"
              empty-label="默认 LLM"
              :options="llmOptions"
              aria-label="选择 LLM"
            />
            <AppSelect
              v-model="vaultId"
              class="chat__select"
              empty-label="不限定 vault"
              :options="vaultOptions"
              aria-label="选择 vault"
            />
            <AppSelect
              v-model="topK"
              class="chat__topk"
              :options="TOPK_OPTIONS"
              aria-label="检索条数"
            />
          </div>

          <AppTextarea
            v-model="input"
            class="chat__input"
            :rows="2"
            :resize="false"
            placeholder="给笔记提问…（Enter 发送，Shift+Enter 换行）"
            aria-label="提问内容"
            @enter="onEnter"
          />

          <div class="chat__box-bar">
            <div class="chat__tools">
              <button
                type="button"
                class="chat__tool"
                :class="{ 'is-on': toolbarOpen }"
                :aria-expanded="toolbarOpen"
                title="模型与检索范围"
                aria-label="模型与检索范围"
                @click="toolbarOpen = !toolbarOpen"
              >
                <AppIcon name="models" :size="16" />
              </button>

              <!-- 录音：一次点击开始、再点一下结束并转写（三态：待录 / 录音中 / 识别中） -->
              <button
                v-if="recorderOk"
                type="button"
                class="chat__tool chat__mic"
                :class="{ 'is-rec': recording }"
                :disabled="!recording && (streaming || transcribing || !asrOk)"
                :title="asrTitle"
                aria-label="语音输入"
                @click="recording ? stopAndTranscribe() : startRecord()"
              >
                <AppIcon :name="recording ? 'stop' : 'mic'" :size="16" />
              </button>

              <span v-if="recording" class="chat__rec-time">
                <span class="chat__rec-dot"></span>
                {{ fmtSecs(recordSecs) }}
              </span>
              <span v-else-if="transcribing" class="chat__rec-time">正在识别…</span>
            </div>

            <!-- 录音中：右侧换成「取消」，避免手滑把半句话发出去 -->
            <div v-if="recording" class="chat__rec-actions">
              <button type="button" class="chat__action" @click="cancelRecord()">取消</button>
            </div>
            <button
              v-else-if="streaming"
              type="button"
              class="chat__send is-stop"
              title="停止生成"
              aria-label="停止生成"
              @click="stop"
            >
              <AppIcon name="stop" :size="18" />
            </button>
            <button
              v-else
              type="button"
              class="chat__send"
              :disabled="!input.trim() || transcribing"
              title="发送"
              aria-label="发送"
              @click="send"
            >
              <AppIcon name="send" :size="18" />
            </button>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
/* 页面占满「顶栏以下视口」，输入区才能真正贴底（不留半屏空白等输入框）
   高度扣减用令牌换算，sm 断点内容内边距更小，单独一档 */
.chat {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: calc(100vh - var(--topbar-height) - var(--space-12));
  min-width: 0;
}

/* ---------- 顶部：主区切换 ---------- */
.chat__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex: none;
}

/* 分段控件：两屏互斥，做成一整块而不是两个独立按钮，一眼看出是「切换视图」 */
.chat__seg {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1);
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-subtle);
}

.chat__seg-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 30px;
  padding: 0 var(--space-3);
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: inherit;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  font-weight: var(--font-weight-semibold);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard),
              color var(--duration-fast) var(--ease-standard);
}
.chat__seg-btn:hover {
  color: var(--color-text-primary);
}
.chat__seg-btn.is-on {
  background: var(--color-bg-surface);
  border-color: var(--color-border);
  color: var(--color-text-primary);
}

/* ---------- 历史记录 ---------- */
.chat__history {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
}

.chat__history-hint {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.chat__history-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.chat__history-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-3) var(--space-4);
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-standard),
              box-shadow var(--duration-fast) var(--ease-standard);
}
.chat__history-item:hover:not(:disabled) {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-sm);
}
.chat__history-item:disabled {
  cursor: default;
  opacity: .6;
}

.chat__history-item-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  font-weight: var(--font-weight-semibold);
}

.chat__history-item-meta {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.chat__dot {
  color: var(--color-text-muted);
}

/* ---------- 消息流 ----------
   wrap 专门承载「回到底部」浮层：直接挂在滚动容器里会跟着内容一起滚走 */
.chat__stream-wrap {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
}

.chat__stream {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-1);
}

.chat__jump {
  position: absolute;
  right: var(--space-3);
  bottom: var(--space-3);
}

.chat__row {
  display: flex;
  min-width: 0;
}
.chat__row.is-user {
  justify-content: flex-end;
}
.chat__row.is-assistant {
  justify-content: flex-start;
}

/* 文档流：提问限宽右对齐（保留「这是我问的」身份感），回答整宽（阅读宽度优先）。
   两边都用中性白卡，靠对齐与宽度区分，不再用主色浅底做气泡填充。 */
.chat__bubble {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-4);
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-xl);
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}
.chat__bubble.is-user {
  max-width: 76%;
}
/* 回答是主内容，靠阴影而不是主色边框来「浮起来」—— 多轮对话下端到端的彩色边框太吵 */
.chat__bubble.is-assistant {
  flex: 1 1 auto;
  box-shadow: var(--shadow-sm);
}

.chat__who {
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  font-weight: var(--font-weight-semibold);
}

/* 回答元信息：谁答的 + 用了哪个模型（模型在发送时快照，不随输入区选择器变化） */
.chat__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.chat__tag {
  padding: 0 var(--space-2);
  border-radius: var(--radius-full);
  background: var(--color-primary-soft);
  color: var(--color-primary-on-soft);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  font-weight: var(--font-weight-semibold);
}

.chat__model {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.chat__text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 生成中光标：只闪 opacity，不引起布局位移 */
.chat__caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  background: currentColor;
  vertical-align: text-bottom;
  animation: chat-caret 1s steps(2, start) infinite;
}
@keyframes chat-caret {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.chat__note {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}
.chat__note.is-warn {
  color: var(--color-warning);
}
.chat__note.is-danger {
  color: var(--color-danger);
}

/* ---------- 回答工具条 ----------
   默认隐去（复制/重新生成是低频动作，常显会跟正文抢注意力）；
   hover 或键盘聚焦出现，触屏设备没有 hover，一律常显。
   opacity 不改可点击性，键盘 Tab 过来时 :focus-within 也会让它显形。 */
.chat__actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  opacity: 0;
  transition: opacity var(--duration-fast) var(--ease-standard);
}
.chat__bubble:hover .chat__actions,
.chat__actions:focus-within {
  opacity: 1;
}
@media (hover: none) {
  .chat__actions {
    opacity: 1;
  }
}

.chat__action {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  font-family: inherit;
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  cursor: pointer;
}
.chat__action:hover:not(:disabled) {
  border-color: var(--color-border);
  background: var(--color-bg-subtle);
  color: var(--color-text-primary);
}
/* 正在朗读：按钮保持显形并标出「就是我」 */
.chat__action.is-on {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.chat__action:disabled {
  cursor: default;
  opacity: .55;
}

/* ---------- 来源 ---------- */
.chat__sources {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  align-items: flex-start;
  border-top: var(--border-width) solid var(--color-border);
  padding-top: var(--space-3);
}

.chat__source-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  align-self: stretch;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* 一条来源：序号 + 正文（标题/路径/片段预览），序号让「引用了哪几条」可数 */
.chat__source {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  min-width: 0;
  padding: var(--space-3);
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-surface);
  box-shadow: var(--shadow-xs);
}

.chat__source-no {
  flex: none;
  color: var(--color-text-muted);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-code);
  line-height: var(--line-height-code);
}

.chat__source-body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.chat__source-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.chat__source-title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  font-weight: var(--font-weight-semibold);
}

.chat__score {
  flex: none;
  color: var(--color-primary);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-code);
  line-height: var(--line-height-code);
  font-variant-numeric: tabular-nums;
}

.chat__source-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

/* 片段预览：展开才显示（默认只给标题与路径），按文件格式渲染
   —— markdown 笔记直接显示原文的话，`##`、`**` 会糊在卡片上 */
.chat__source-excerpt {
  margin-top: var(--space-1);
  padding-top: var(--space-2);
  border-top: var(--border-width) solid var(--color-border);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}
.chat__source-excerpt--plain {
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---------- 输入区 ----------
   整块一张卡：文本框、工具图标、发送按钮都在同一个容器里，
   焦点落在容器上（focus-within）而不是各自为战 —— 视觉上「一整块 vs 一堆方块」是这里的关键 */
.chat__composer-wrap {
  flex: none;
  padding-top: var(--space-2);
}

.chat__box {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: var(--border-width) solid var(--color-border-strong);
  border-radius: var(--radius-xl);
  background: var(--color-bg-surface);
  box-shadow: var(--shadow-sm);
  transition: border-color var(--duration-fast) var(--ease-standard),
              box-shadow var(--duration-fast) var(--ease-standard);
}
.chat__box:focus-within {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

/* 容器内的文本框：边框与背景交给容器，自身只保留文字排版。
   hover/focus 一起覆盖，否则 AppTextarea 自带的主色描边会在聚焦时顶出来 */
.chat__box :deep(.app-textarea),
.chat__box :deep(.app-textarea:hover),
.chat__box :deep(.app-textarea:focus) {
  padding: var(--space-1) var(--space-2) 0;
  border-color: transparent;
  background: transparent;
  outline: none;
}

.chat__config {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding-bottom: var(--space-2);
  border-bottom: var(--border-width) solid var(--color-border);
}

/* 底部动作行：工具图标在左，发送在右（和 ChatGPT 一样，主按钮收在角落） */
.chat__box-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

/* 左侧工具组：配置入口 + 录音入口 + 录音状态（计时 / 识别中） */
.chat__tools {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
}

/* 工具图标按钮：无文字标签，展开/录音中用软底标出「它开着」 */
.chat__tool {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 32px;
  height: 32px;
  padding: 0;
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard),
              color var(--duration-fast) var(--ease-standard);
}
.chat__tool:hover:not(:disabled) {
  background: var(--color-bg-subtle);
  color: var(--color-text-primary);
}
.chat__tool.is-on {
  background: var(--color-primary-soft);
  color: var(--color-primary-on-soft);
}
.chat__tool:disabled {
  cursor: default;
  opacity: .45;
}

/* 录音中：整颗按钮转成危险色，加上呼吸感（静态红容易和「报错」混淆，动起来才像「正在发生」） */
.chat__mic.is-rec {
  background: var(--color-danger);
  color: var(--color-danger-contrast);
  animation: chat-rec 1.6s ease-in-out infinite;
}
@keyframes chat-rec {
  0%, 100% { opacity: 1; }
  50% { opacity: .62; }
}

.chat__rec-time {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding-left: var(--space-1);
  color: var(--color-text-muted);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  font-variant-numeric: tabular-nums;
}

.chat__rec-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--color-danger);
  animation: chat-rec 1.6s ease-in-out infinite;
}

.chat__rec-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

/* 发送：圆形图标按钮（无文字标签），禁用时退成中性灰而不是半透明主色 */
.chat__send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 32px;
  height: 32px;
  padding: 0;
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-full);
  background: var(--color-accent);
  color: var(--color-accent-on);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard),
              color var(--duration-fast) var(--ease-standard);
}
.chat__send:hover:not(:disabled) {
  background: var(--color-accent-hover);
}
.chat__send:disabled {
  background: var(--color-bg-subtle);
  color: var(--color-text-muted);
  cursor: default;
}
.chat__send.is-stop {
  background: var(--color-danger);
  color: var(--color-danger-contrast);
}

.chat__select {
  width: 220px;
}

.chat__topk {
  width: 130px;
}

@media (max-width: 767px) {
  .chat {
    min-height: calc(100vh - var(--topbar-height) - var(--space-8));
  }
  /* 触控目标 ≥44px：圆形按钮在窄屏要撑开，否则手指点不准 */
  .chat__tool,
  .chat__send {
    width: 44px;
    height: 44px;
  }
  .chat__select {
    flex: 1 1 0;
    width: auto;
  }
  .chat__topk {
    flex: 1 1 0;
    width: auto;
  }
  .chat__bubble.is-user {
    max-width: 88%;
  }
}
</style>