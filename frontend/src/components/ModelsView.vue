<!--
  模型管理页 —— 多个 LLM / 多个 Embedding 的增删改与选择（见 docs/design.md §18）

  能力：
  - 分 LLM / Embedding 两组列出 model_profiles（密钥只显示掩码，永不回显明文）
  - 新建 / 编辑 / 删除 / 设为默认 / 连通性测试
  - 明确提示关键差异：LLM 每次请求可换；Embedding 与索引绑定，换模型需重建索引

  业务实现留白：本页只做展示与调用 api.js，实际 CRUD 由后端 routes/models.py 提供。
-->
<template>
  <section>
    <h2>模型管理</h2>
    <p class="hint">
      LLM 无状态，问答时随便换；<b>Embedding 与索引强绑定</b>，换模型必须对该 vault 重建索引（§18.2）。
    </p>

    <div class="toolbar">
      <button @click="activeKind = 'llm'" :class="{ active: activeKind === 'llm' }">LLM</button>
      <button @click="activeKind = 'embed'" :class="{ active: activeKind === 'embed' }">Embedding</button>
      <button class="primary" @click="openCreate">+ 新建</button>
      <button @click="load">刷新</button>
    </div>

    <!-- 新建 / 编辑表单 -->
    <div v-if="editing" class="card">
      <h3>{{ form.id ? '编辑模型' : '新建模型' }}</h3>
      <div class="field">
        <label>类型 kind</label>
        <select v-model="form.kind">
          <option value="llm">llm（对话 / 问答）</option>
          <option value="embed">embed（向量化）</option>
        </select>
      </div>
      <div class="field">
        <label>名称 name（选择时用，如 qwen-max / bge-m3-local）</label>
        <input v-model="form.name" placeholder="qwen-max" />
      </div>
      <div class="field">
        <label>模型标识 model</label>
        <input v-model="form.model" placeholder="gpt-4o-mini / text-embedding-3-small" />
      </div>
      <div class="field">
        <label>base_url（留空 = 回退 .env 的 LLM_BASE_URL / EMBED_BASE_URL）</label>
        <input v-model="form.base_url" placeholder="https://api.openai.com/v1" />
      </div>
      <div class="field">
        <label>api_key（留空同上；保存后不再回显，只显示掩码）</label>
        <input v-model="form.api_key" type="password" placeholder="sk-..." />
      </div>
      <label class="checkbox">
        <input type="checkbox" v-model="form.set_default" /> 设为该类型的默认模型
      </label>
      <div class="toolbar">
        <button class="primary" @click="save">保存</button>
        <button @click="testUnsaved">试连</button>
        <button @click="editing = false">取消</button>
      </div>
      <p v-if="testResult" class="hint">{{ testResult }}</p>
    </div>

    <!-- 列表 -->
    <div class="card" style="padding: 0">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>模型</th>
            <th>端点</th>
            <th>密钥</th>
            <th>默认</th>
            <th>来源</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in filtered" :key="m.id">
            <td><b>{{ m.name }}</b></td>
            <td>{{ m.model }}</td>
            <td class="mono">{{ m.base_url || '（回退 .env）' }}</td>
            <td class="mono">{{ m.api_key_masked || '（回退 .env）' }}</td>
            <td>
              <span v-if="m.is_default" class="tag ok">默认</span>
              <button v-else @click="makeDefault(m)">设为默认</button>
            </td>
            <td>{{ m.origin === 'env' ? 'env 种子' : '前端' }}</td>
            <td class="nowrap">
              <button @click="openEdit(m)">编辑</button>
              <button @click="testOne(m)">试连</button>
              <button @click="remove(m)">删除</button>
            </td>
          </tr>
          <tr v-if="!filtered.length">
            <td colspan="7" class="hint">暂无配置 —— 首次启动会由 .env 注入 llm / embed 各一个 default 种子。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { modelsApi } from '../api'

const list = ref([])
const activeKind = ref('llm')
const editing = ref(false)
const testResult = ref('')
const form = ref(blankForm())

function blankForm() {
  return { id: null, kind: 'llm', name: '', model: '', base_url: '', api_key: '', set_default: false }
}

const filtered = computed(() => list.value.filter((m) => m.kind === activeKind.value))

async function load() {
  list.value = await modelsApi.list()
}
onMounted(load)

function openCreate() {
  form.value = { ...blankForm(), kind: activeKind.value }
  testResult.value = ''
  editing.value = true
}
function openEdit(m) {
  form.value = { ...m, api_key: '', set_default: m.is_default }
  testResult.value = ''
  editing.value = true
}

async function save() {
  const payload = { ...form.value }
  delete payload.id
  if (form.value.id) await modelsApi.update(form.value.id, payload)
  else await modelsApi.create(payload)
  editing.value = false
  await load()
}

async function remove(m) {
  // 被 vault 引用时后端返回 409 —— 提示先换 embedding 重建索引
  await modelsApi.remove(m.id)
  await load()
}

async function makeDefault(m) {
  await modelsApi.setDefault(m.id)
  await load()
}

async function testOne(m) {
  const r = await modelsApi.test(m.id)
  testResult.value = `${m.name}: ${r.ok ? '连通 ✓' : '失败 ✗ ' + r.error} ${r.detail}`
}

async function testUnsaved() {
  const r = await modelsApi.testUnsaved(form.value)
  testResult.value = r.ok ? `连通 ✓ ${r.detail}` : `失败 ✗ ${r.error}`
}
</script>
