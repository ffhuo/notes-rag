// 问答流式传输抽象（T5.1 / 规范 §6.5）。
//
// 为什么要有这一层：小程序没有 EventSource，fetch 流式要换成 wx.request 的
// enableChunked 回调；RN 用的是另一套。页面只认「发起一次流 → 收到 token/sources/done」
// 这件事，端的差异全部关在这里。**接口形态在 Chat 页跑通后才定，不提前抽象**（§4.5）。
//
// 服务端事件格式（app/api/routes/chat.py 的 _sse）：
//   event: token    data: "文本片段"
//   event: sources  data: [{ note_id, file_path, title, content, score }]
//   event: done     data: { conversation_id }
//   event: error    data: "错误信息"
// 块分隔为 \n\n（Starlette 输出 LF）。
import { API_BASE, authHeaders } from '../api'

/**
 * 增量 SSE 解析器：网络分片任意切割，必须按「空行分块」缓存后再解析。
 * 返回每块的 { event, data }。
 */
function createSseParser(onEvent) {
  let buf = ''
  return {
    push(chunk) {
      buf += chunk
      let idx = buf.indexOf('\n\n')
      while (idx !== -1) {
        const block = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        parseBlock(block, onEvent)
        idx = buf.indexOf('\n\n')
      }
    },
    /** 流结束时把残留的尾块（无结尾空行）也解析掉。 */
    end() {
      if (buf.trim()) parseBlock(buf, onEvent)
      buf = ''
    },
  }
}

function parseBlock(block, onEvent) {
  let event = 'message'
  const dataLines = []
  for (const rawLine of block.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
  }
  if (!dataLines.length) return
  const raw = dataLines.join('\n')
  let data = raw
  try {
    data = JSON.parse(raw)
  } catch {
    // 非 JSON 原样透传：错误事件可能是纯文本
  }
  onEvent(event, data)
}

/** Web / H5 实现：fetch + ReadableStream。 */
async function streamViaFetch(payload, handlers, signal) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
    signal,
  })

  if (!res.ok) {
    // 建流前的错误（422 参数 / 404 vault / 409 未建索引）是普通 JSON 响应
    const raw = await res.text().catch(() => '')
    const err = new Error(`HTTP ${res.status} ${raw}`)
    err.status = res.status
    try {
      err.body = raw ? JSON.parse(raw) : null
    } catch {
      err.body = null
    }
    throw err
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const parser = createSseParser((event, data) => {
    if (event === 'token') handlers.onToken?.(String(data ?? ''))
    else if (event === 'sources') handlers.onSources?.(Array.isArray(data) ? data : [])
    else if (event === 'done') handlers.onDone?.(data || {})
    else if (event === 'error') handlers.onError?.(new Error(String(data ?? '生成失败')))
  })

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    parser.push(decoder.decode(value, { stream: true }))
  }
  parser.push(decoder.decode())
  parser.end()
}

/**
 * 发起一次问答流。
 *
 * @param {object} payload  { query, top_k, vault_id, llm_profile, conversation_id }
 * @param {object} handlers { onToken, onSources, onDone, onError, onAbort }
 * @returns {{ abort: () => void }} 调 abort() 立即停止读取（已生成内容保留在调用方）
 */
export function streamChat(payload, handlers = {}) {
  const controller = new AbortController()
  streamViaFetch(payload, handlers, controller.signal).catch((e) => {
    if (e?.name === 'AbortError') handlers.onAbort?.()
    else handlers.onError?.(e)
  })
  return { abort: () => controller.abort() }
}

/**
 * 传输层门面：页面只依赖它，换端时替换实现（小程序用 chunked，RN 用其自有流）。
 */
export const chatTransport = {
  stream: streamChat,
}
