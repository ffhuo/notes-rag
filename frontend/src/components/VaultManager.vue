<script setup>
// Vault 管理页：列出当前用户的 vault；两种添加方式：
//  1) 本地目录：填 name + 绝对路径 → POST /api/v1/vaults（JSON）
//  2) 上传 vault：选 .zip → POST /api/v1/vaults（multipart，source_type=uploaded）
// 每个 vault 支持「重建索引」与「删除」。
import { ref, onMounted } from 'vue'
import { apiFetch } from '../api'

const vaults = ref([])
const newName = ref('')
const newPath = ref('')
const uploadFile = ref(null)
const error = ref('')

async function load() {
  // TODO: 调 GET /api/v1/vaults；单用户需先 setApiKey（设置页填一次）
  vaults.value = await apiFetch('/vaults')
}

async function addLocal() {
  error.value = ''
  try {
    await apiFetch('/vaults', {
      method: 'POST',
      body: JSON.stringify({ name: newName.value, source_type: 'local', source_value: newPath.value }),
    })
    newName.value = ''
    newPath.value = ''
    await load()
  } catch (e) {
    error.value = e.message
  }
}

async function addUpload() {
  error.value = ''
  const fd = new FormData()
  fd.append('name', newName.value)
  if (uploadFile.value) fd.append('file', uploadFile.value)
  try {
    await fetch('/api/v1/vaults/upload', { method: 'POST', body: fd }) // multipart 由浏览器设 Content-Type
    newName.value = ''
    uploadFile.value = null
    await load()
  } catch (e) {
    error.value = e.message
  }
}

async function reindex(id) {
  await apiFetch(`/vaults/${id}/reindex`, { method: 'POST', body: JSON.stringify({ rebuild: true }) })
  await load()
}

async function remove(id) {
  await apiFetch(`/vaults/${id}`, { method: 'DELETE' })
  await load()
}

onMounted(load)
</script>

<template>
  <section>
    <h2>Vaults</h2>
    <p class="hint">添加本地目录（填绝对路径）或上传 vault 压缩包（.zip）。</p>

    <div class="form">
      <input v-model="newName" placeholder="vault 名称" />
      <input v-model="newPath" placeholder="本地目录绝对路径（local 模式）" />
      <button @click="addLocal">添加本地目录</button>
    </div>

    <div class="form">
      <input v-model="newName" placeholder="vault 名称" />
      <input type="file" accept=".zip" @change="e => (uploadFile = e.target.files[0])" />
      <button @click="addUpload">上传 vault</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <ul>
      <li v-for="v in vaults" :key="v.id">
        <span>{{ v.name }} · {{ v.source_type }} · {{ v.source_value }}</span>
        <button @click="reindex(v.id)">重建索引</button>
        <button @click="remove(v.id)">删除</button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.form { display: flex; gap: 8px; margin: 8px 0; }
.hint { color: #888; font-size: 13px; }
.error { color: #a32d2d; }
</style>
