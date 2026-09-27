// 朗读封装（Web Speech API 的 speechSynthesis）—— 浏览器本地合成，不经过后端。
//
// 选它而不是后端 TTS 的理由：零配置、零费用、音频不出本机；代价是音色由系统决定
// （不同机器听到的不一样），且**只能用系统已有的语言包**。
//
// 三个必须处理的现实问题：
//  1) 整段塞给 speak() 会被浏览器截断（Chrome 对长 utterance 有 ~15s 上限），
//     所以按句切分、逐句排队 —— 上一句 onend 才排下一句
//  2) 取消后旧回调仍会到达（cancel() 会触发 onend/onerror），用递增的 runId 作废旧一轮，
//     否则「停止后再点朗读」会被上一次的收尾回调立刻打断
//  3) 语音列表是异步加载的（首次 getVoices() 常为空），要等 voiceschanged 再挑音色

/** 单次朗读的最大字符数：一篇长回答全念完要好几分钟，用户多半只是想听开头。 */
const MAX_TOTAL = 4000
/** 单条 utterance 的最大长度：没有标点的长段落要再切，否则会被浏览器截断。 */
const MAX_CHUNK = 180

/** 一轮朗读的序号：stop 或新的 speak 都会 +1，旧回调据此判断自己已过期。 */
let runId = 0
let cachedVoices = []
let voicesBound = false

export function isSpeechSupported() {
  return typeof window !== 'undefined' && !!window.speechSynthesis && !!window.SpeechSynthesisUtterance
}

/** 语音列表在部分浏览器里首帧为空，用一次性的 voiceschanged 事件把它补上。 */
function loadVoices() {
  if (!isSpeechSupported()) return []
  cachedVoices = window.speechSynthesis.getVoices() || []
  // 只挂一次监听：这个事件在部分浏览器里会反复触发
  if (!voicesBound) {
    voicesBound = true
    window.speechSynthesis.addEventListener('voiceschanged', () => {
      cachedVoices = window.speechSynthesis.getVoices() || []
    })
  }
  return cachedVoices
}

/** 挑一个与目标语言匹配的音色；找不到就交给浏览器默认（null）。 */
function pickVoice(lang) {
  const voices = loadVoices()
  if (!voices.length) return null
  const want = String(lang || '').toLowerCase()
  const primary = want.split('-')[0]
  return (
    voices.find((v) => v.lang?.toLowerCase() === want) ||
    voices.find((v) => v.lang?.toLowerCase().startsWith(primary)) ||
    null
  )
}

/** 按句切分：句末标点（中英）与换行都算一句话的结束。 */
function splitSentences(text) {
  const ENDERS = new Set(['。', '！', '？', '；', '!', '?', ';', '\n'])
  const out = []
  let buf = ''
  for (const ch of text) {
    buf += ch
    if (ENDERS.has(ch)) {
      const s = buf.trim()
      if (s) out.push(s)
      buf = ''
    }
  }
  const tail = buf.trim()
  if (tail) out.push(tail)
  return out.flatMap(splitLong)
}

/**
 * 没有标点的长段落（列表、代码残留）在次级停顿处再切一刀：
 * 先是逗号/顿号，仍超长则按长度硬切 —— 硬切比被浏览器整段吞掉好。
 */
function splitLong(sentence) {
  if (sentence.length <= MAX_CHUNK) return [sentence]
  const parts = []
  let buf = ''
  for (const ch of sentence) {
    buf += ch
    if ('，,、'.includes(ch) && buf.length >= MAX_CHUNK / 2) {
      parts.push(buf.trim())
      buf = ''
    }
  }
  if (buf.trim()) parts.push(buf.trim())
  return parts.flatMap((p) => {
    if (p.length <= MAX_CHUNK) return [p]
    const hard = []
    for (let i = 0; i < p.length; i += MAX_CHUNK) hard.push(p.slice(i, i + MAX_CHUNK))
    return hard
  })
}

/**
 * 开始朗读。
 *
 * @param {string} text 纯文本（Markdown 请先过 markdown.js 的 toPlainText —— 念出 `##`
 *                      和代码块毫无意义，那是渲染层的事，不在这里猜）
 * @param {{lang?: string, onEnd?: () => void}} options onEnd 在整段读完或出错时各触发一次；
 *        被 stopSpeaking() 取消时**不触发**（调用方自己知道是它停的）
 * @returns {boolean} 是否真的开始（不支持 / 文本为空 → false）
 */
export function speak(text, { lang = 'zh-CN', onEnd } = {}) {
  if (!isSpeechSupported()) return false
  const content = String(text ?? '').replace(/\s+/g, ' ').trim()
  if (!content) return false

  const synth = window.speechSynthesis
  const script = splitSentences(content.slice(0, MAX_TOTAL))

  // 上一轮还在念就直接顶掉（重新生成、切到下一条回答都走这里）
  const id = (runId += 1)
  synth.cancel()
  // Chrome 有一个「暂停态下 speak 无效」的坑：按了暂停的会话必须先 resume
  synth.resume()

  const voice = pickVoice(lang)
  let index = 0

  const next = () => {
    if (id !== runId) return
    if (index >= script.length) {
      onEnd?.()
      return
    }
    const u = new SpeechSynthesisUtterance(script[index])
    index += 1
    u.lang = lang
    if (voice) u.voice = voice
    u.onend = next
    // 出错也收尾：cancel 触发的 interrupted/canceled 已被上面的 runId 挡掉
    u.onerror = () => {
      if (id === runId) onEnd?.()
    }
    synth.speak(u)
  }

  next()
  return true
}

/** 停止朗读并清空队列（队列里排着的句子不清掉，点停止后还会继续念）。 */
export function stopSpeaking() {
  if (!isSpeechSupported()) return
  runId += 1
  window.speechSynthesis.cancel()
}