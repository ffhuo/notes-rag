<script setup>
// 问答页：输入 query → POST /api/v1/chat（SSE 流式）→ 逐 token 渲染 + 展示来源。
// SSE 用 fetch 读 ReadableStream（EventSource 仅支持 GET，这里用 POST 故手动解析 text/event-stream）。
import { onMounted, ref } from 'vue'
import { modelsApi } from '../api'

const query = ref('')
const answer = ref('')
const sources = ref([])
const error = ref('')
// 本次问答用哪个 LLM：留空 = 用默认配置（见 docs/design.md §18.2）
const llmModels = ref([])
const llmProfile = ref('')
const vaultId = ref('')

onMounted(async () => {
  llmModels.value = await modelsApi.list('llm')
  const d = llmModels.value.find((m) => m.is_default)
  if (d) llmProfile.value = d.name
})

async function ask() {
  error.value = ''
  answer.value = ''
  sources.value = []
  try {
    const res = await fetch('/api/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query.value, top_k: 5 }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // 按 SSE 事件分帧：每行 "data: {...}"
      const lines = buf.split('\n')
      buf = lines.pop()
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const payload = JSON.parse(line.slice(5).trim())
        if (payload.type === 'token') answer.value += payload.text
        else if (payload.type === 'sources') sources.value = payload.items
      }
    }
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <section>
    <h2>Chat</h2>
    <div class="form">
      <select v-model="llmProfile" title="选择本次用哪个 LLM">
        <option value="">默认 LLM</option>
        <option v-for="m in llmModels" :key="m.id" :value="m.name">{{ m.name }}（{{ m.model }}）</option>
      </select>
      <input v-model="query" placeholder="问点什么..." @keyup.enter="ask" />
      <button @click="ask">问答</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="answer">{{ answer }}</div>
    <div v-if="sources.length" class="sources">
      <h3>来源</h3>
      <ul>
        <li v-for="(s, i) in sources" :key="i">{{ s.title }} · {{ s.file_path }} · {{ s.score }}</li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.form { display: flex; gap: 8px; }
.answer { white-space: pre-wrap; margin-top: 12px; line-height: 1.6; }
.sources { margin-top: 12px; color: #888; }
.error { color: #a32d2d; }
</style>
