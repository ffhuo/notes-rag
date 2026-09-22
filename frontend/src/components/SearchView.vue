<script setup>
// 检索页：输入 query → POST /api/v1/search → 展示命中片段与出处。
import { ref } from 'vue'
import { apiFetch } from '../api'

const query = ref('')
const topK = ref(5)
const hits = ref([])
const error = ref('')

async function search() {
  error.value = ''
  try {
    const res = await apiFetch('/search', {
      method: 'POST',
      body: JSON.stringify({ query: query.value, top_k: topK.value, threshold: 0.0 }),
    })
    hits.value = res.hits || []
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <section>
    <h2>Search</h2>
    <div class="form">
      <input v-model="query" placeholder="输入查询..." @keyup.enter="search" />
      <input v-model.number="topK" type="number" min="1" max="20" style="width: 64px" />
      <button @click="search">检索</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <article v-for="(h, i) in hits" :key="i" class="hit">
      <header>{{ h.title }} · {{ h.file_path }} · score={{ h.score.toFixed(3) }}</header>
      <p>{{ h.content }}</p>
    </article>
  </section>
</template>

<style scoped>
.form { display: flex; gap: 8px; }
.hit { border: 1px solid #eee; border-radius: 8px; padding: 8px 12px; margin: 8px 0; }
.hit header { color: #185fa5; font-size: 13px; }
.error { color: #a32d2d; }
</style>
