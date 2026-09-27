// 录音封装（MediaRecorder）—— 只负责「拿到一段音频」，不做转写（转写走 api.js 的 audioApi）。
//
// 三条必须自己处理的现实问题：
//  1) 格式协商：各浏览器支持的容器不同（Chrome/Firefox 给 webm/opus，Safari 只给 mp4/aac）。
//     写死 audio/webm 会让 Safari 直接抛 NotSupportedError，所以按候选表问一遍
//  2) 关麦：MediaRecorder 停了不等于麦克风释放，必须显式 stop() 各 track，
//     否则浏览器标签页上的录音红点一直亮着 —— 用户会以为还在被监听
//  3) 取消：录到一半反悔要能整段丢弃，而不是「停下来再让调用方忽略结果」
//
// 取消与停止都会停表并关麦，差别只在返回值：stop() 给音频，cancel() 给 null。

/** 容器候选，按「上游语音端点接受度 + 体积」排序优先 webm/opus。 */
const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
]

/** 扩展名映射：上游多半按文件名推断容器，扩展名给错会被判成格式不支持。 */
const EXT_BY_MIME = [
  ['audio/webm', 'webm'],
  ['audio/mp4', 'm4a'],
  ['audio/ogg', 'ogg'],
  ['audio/wav', 'wav'],
  ['audio/mpeg', 'mp3'],
]

export function isRecorderSupported() {
  return (
    typeof window !== 'undefined' &&
    typeof window.MediaRecorder !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia
  )
}

function pickMime() {
  if (typeof MediaRecorder.isTypeSupported !== 'function') return ''
  for (const t of MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(t)) return t
  }
  return ''
}

function extFor(mime) {
  const base = String(mime || '').split(';')[0].trim().toLowerCase()
  for (const [prefix, ext] of EXT_BY_MIME) {
    if (base === prefix) return ext
  }
  return 'webm'
}

/** 把 getUserMedia / MediaRecorder 的异常翻译成一句人能看懂的话。 */
export function describeRecorderError(err) {
  const name = err?.name || ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return '麦克风权限被拒绝，请在浏览器地址栏的权限设置里允许后重试'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return '没有找到可用的麦克风设备'
  if (name === 'NotReadableError') return '麦克风被其他程序占用，请关闭后重试'
  return err?.message || '无法开始录音'
}

/**
 * 开始录音。
 *
 * @returns {Promise<{stop: () => Promise<{blob: Blob, filename: string} | null>, cancel: () => void, mimeType: string}>}
 *   stop()：结束并返回音频（已取消则返回 null）；cancel()：结束并丢弃。
 *   两者都会释放麦克风，调用方不需要另外管 stream。
 */
export async function startRecording() {
  if (!isRecorderSupported()) throw new Error('当前浏览器不支持录音')

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const mimeType = pickMime()
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)

  const chunks = []
  let cancelled = false

  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size) chunks.push(e.data)
  }

  // stop 事件在部分浏览器里是异步到达的（最后一帧数据还没落地）：
  // 等它触发再取 chunks，否则会丢掉末尾那句
  const stopped = new Promise((resolve) => {
    recorder.onstop = () => resolve()
  })

  // 分片产出（1s）：整段只留一个 blob 时，长录音的最后一帧有概率丢；分片同时也更容易及时释放内存
  recorder.start(1000)

  const releaseMic = () => stream.getTracks().forEach((t) => t.stop())

  const done = () => {
    if (recorder.state !== 'inactive') recorder.stop()
    releaseMic()
  }

  return {
    mimeType: recorder.mimeType || mimeType || 'audio/webm',
    async stop() {
      done()
      await stopped
      if (cancelled) return null
      const type = recorder.mimeType || mimeType || 'audio/webm'
      return { blob: new Blob(chunks, { type }), filename: `clip.${extFor(type)}` }
    },
    cancel() {
      cancelled = true
      done()
    },
  }
}