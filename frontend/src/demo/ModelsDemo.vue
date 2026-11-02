<script setup>
import { computed, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'

const emit = defineEmits(['notify'])
const kinds = [
  { id: 'llm', label: 'LLM 对话模型' },
  { id: 'embed', label: 'Embedding 向量模型' },
  { id: 'asr', label: '语音识别' },
]
const models = ref([
  { id: 1, kind: 'llm', name: 'Qwen Plus', model: 'qwen-plus', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', key: 'sk-••••••••', isDefault: true, extra: '支持图片输入' },
  { id: 2, kind: 'llm', name: 'GPT 4o mini', model: 'gpt-4o-mini', baseUrl: 'https://api.openai.com/v1', key: 'sk-••••••••', isDefault: false, extra: '' },
  { id: 3, kind: 'embed', name: 'BGE M3', model: 'BAAI/bge-m3', baseUrl: 'https://api.siliconflow.cn/v1', key: 'sk-••••••••', isDefault: true, extra: '2 个 Vault 使用' },
  { id: 4, kind: 'asr', name: 'Whisper', model: 'whisper-1', baseUrl: 'https://api.openai.com/v1', key: '（未设置）', isDefault: true, extra: 'OpenAI ASR' },
])

const activeKind = ref('llm')
const query = ref('')
const editorOpen = ref(false)
const deleteTarget = ref(null)
const formError = ref('')
const draft = ref(blankModel())
const editId = ref(null)

const visibleModels = computed(() => {
  const term = query.value.trim().toLowerCase()
  return models.value.filter((model) => model.kind === activeKind.value && (!term || `${model.name} ${model.model} ${model.baseUrl}`.toLowerCase().includes(term)))
})

function blankModel() {
  return { kind: 'llm', name: '', model: '', baseUrl: '', apiKey: '', setDefault: false, multimodal: false }
}

function openCreate() {
  editId.value = null
  draft.value = { ...blankModel(), kind: activeKind.value }
  formError.value = ''
  editorOpen.value = true
}

function openEdit(model) {
  editId.value = model.id
  draft.value = { kind: model.kind, name: model.name, model: model.model, baseUrl: model.baseUrl, apiKey: '', setDefault: model.isDefault, multimodal: model.extra === '支持图片输入' }
  formError.value = ''
  editorOpen.value = true
}

function saveModel() {
  if (!draft.value.name.trim() || !draft.value.model.trim()) {
    formError.value = '请填写名称和模型标识。'
    return
  }
  const saved = {
    id: editId.value || Math.max(...models.value.map((model) => model.id), 0) + 1,
    kind: draft.value.kind,
    name: draft.value.name.trim(),
    model: draft.value.model.trim(),
    baseUrl: draft.value.baseUrl.trim() || 'OpenAI 官方端点',
    key: draft.value.apiKey ? '••••••••' : editId.value ? models.value.find((model) => model.id === editId.value)?.key : '（未设置）',
    isDefault: draft.value.setDefault,
    extra: draft.value.kind === 'llm' && draft.value.multimodal ? '支持图片输入' : '',
  }
  if (saved.isDefault) {
    models.value = models.value.map((model) => model.kind === saved.kind ? { ...model, isDefault: false } : model)
  }
  if (editId.value) models.value = models.value.map((model) => model.id === editId.value ? saved : model)
  else models.value.push(saved)
  editorOpen.value = false
  emit('notify', editId.value ? '演示模型配置已保存' : '演示模型配置已添加')
}

function setDefault(model) {
  models.value = models.value.map((item) => item.kind === model.kind ? { ...item, isDefault: item.id === model.id } : item)
  emit('notify', `已将「${model.name}」设为演示默认模型`)
}

function confirmDelete() {
  models.value = models.value.filter((model) => model.id !== deleteTarget.value.id)
  emit('notify', `已从演示列表移除「${deleteTarget.value.name}」`)
  deleteTarget.value = null
}
</script>

<template>
  <div class="page-intro">
    <div><div class="eyebrow"><span class="eyebrow__dot"></span> MODEL CONFIGURATION</div><h1>为每类任务选择合适模型</h1><p>LLM 可随问答切换；Embedding 与已有索引绑定；ASR 用于语音转写。</p></div>
    <button class="button button--primary" type="button" @click="openCreate"><AppIcon name="plus" :size="16" />新建模型</button>
  </div>

  <div class="model-warning"><AppIcon name="info" :size="15" /><span><strong>Embedding 提醒：</strong>更换向量模型后，相关 Vault 需要重建索引。</span></div>
  <div class="model-tabs" role="tablist">
    <button v-for="kind in kinds" :key="kind.id" type="button" role="tab" :aria-selected="activeKind === kind.id" :class="{ 'is-active': activeKind === kind.id }" @click="activeKind = kind.id">
      {{ kind.label }} <span>{{ models.filter((model) => model.kind === kind.id).length }}</span>
    </button>
  </div>
  <section class="panel model-list">
    <div class="model-list__toolbar"><label><AppIcon name="search" :size="15" /><input v-model="query" aria-label="搜索模型" placeholder="搜索名称、模型标识或端点" /></label><span>{{ visibleModels.length }} 个配置</span></div>
    <div v-if="visibleModels.length" class="model-rows">
      <article v-for="model in visibleModels" :key="model.id" class="model-row">
        <span class="model-row__icon"><AppIcon name="models" :size="17" /></span>
        <span class="model-row__name"><strong>{{ model.name }} <span v-if="model.extra" class="model-tag">{{ model.extra }}</span></strong><code>{{ model.model }}</code></span>
        <span class="model-row__endpoint">{{ model.baseUrl }}</span>
        <span class="model-row__key">{{ model.key }}</span>
        <span v-if="model.isDefault" class="model-default"><AppIcon name="star" :size="13" />默认</span>
        <button v-else class="model-action model-action--default" type="button" @click="setDefault(model)">设为默认</button>
        <div class="model-row__actions">
          <button class="model-action" type="button" @click="emit('notify', '试连是模拟状态，不会请求模型服务')">试连</button>
          <button class="model-action" type="button" @click="openEdit(model)">编辑</button>
          <button class="model-action model-action--danger" type="button" aria-label="删除模型" @click="deleteTarget = model"><AppIcon name="trash" :size="14" /></button>
        </div>
      </article>
    </div>
    <div v-else class="model-empty"><AppIcon name="models" :size="22" /><strong>暂无{{ kinds.find((kind) => kind.id === activeKind)?.label }}</strong><button class="button button--secondary" type="button" @click="openCreate">添加一个配置</button></div>
  </section>

  <div class="model-demo-note"><AppIcon name="info" :size="14" />此页的模型增删、设默认与测试结果仅更新演示界面，不会保存配置或发出网络请求。</div>

  <div v-if="editorOpen" class="dialog-backdrop" @click.self="editorOpen = false">
    <section class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="model-dialog-title" @keydown.esc.prevent="editorOpen = false">
      <div class="dialog-card__heading"><span class="section-icon"><AppIcon name="models" :size="18" /></span><button class="demo-icon-button" type="button" aria-label="关闭" @click="editorOpen = false"><AppIcon name="close" :size="18" /></button></div>
      <h2 id="model-dialog-title">{{ editId ? '编辑模型配置' : '新建模型配置' }}</h2>
      <label class="form-field"><span>类型</span><select v-model="draft.kind" :disabled="!!editId"><option value="llm">LLM 对话模型</option><option value="embed">Embedding 向量模型</option><option value="asr">ASR 语音识别</option></select></label>
      <label class="form-field"><span>名称</span><input v-model="draft.name" placeholder="例如 qwen-max" /></label>
      <label class="form-field"><span>模型标识</span><input v-model="draft.model" placeholder="例如 gpt-4o-mini" /></label>
      <label class="form-field"><span>端点 base_url</span><input v-model="draft.baseUrl" placeholder="https://api.openai.com/v1" /></label>
      <label class="form-field"><span>密钥 api_key</span><input v-model="draft.apiKey" type="password" placeholder="留空表示不修改" /><small>保存后仅显示掩码；演示不会保存或发送此内容。</small></label>
      <label v-if="draft.kind === 'llm'" class="model-check"><input v-model="draft.multimodal" type="checkbox" />支持图片输入（多模态）</label>
      <label class="model-check"><input v-model="draft.setDefault" type="checkbox" />设为该类型默认模型</label>
      <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
      <div class="dialog-card__actions"><button class="button button--secondary" type="button" @click="editorOpen = false">取消</button><button class="button button--primary" type="button" @click="saveModel">保存演示配置</button></div>
    </section>
  </div>

  <div v-if="deleteTarget" class="dialog-backdrop" @click.self="deleteTarget = null">
    <section class="dialog-card dialog-card--compact" role="alertdialog" aria-modal="true" aria-labelledby="delete-model-title">
      <h2 id="delete-model-title">移除「{{ deleteTarget.name }}」？</h2><p class="dialog-card__desc">只会从演示列表移除，不会影响真实模型配置。</p>
      <div class="dialog-card__actions"><button class="button button--secondary" type="button" @click="deleteTarget = null">取消</button><button class="button button--danger" type="button" @click="confirmDelete">移除配置</button></div>
    </section>
  </div>
</template>

<style scoped>
.button { min-height: 38px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 12px; border: 1px solid var(--ui-border); border-radius: 8px; font-size: 10px; font-weight: 600; cursor: pointer; }
.button--primary { color: var(--color-primary-contrast); background: var(--ui-primary); border-color: var(--ui-primary); }
.button--secondary { color: var(--ui-text); background: var(--ui-surface); }
.button--danger { color: var(--color-danger-contrast); background: var(--ui-danger); }
.model-warning, .model-demo-note { display: flex; align-items: flex-start; gap: 7px; color: var(--ui-text); font-size: 9px; line-height: 15px; }
.model-warning { padding: 10px 12px; background: var(--ui-primary-soft); border: 1px solid var(--ui-border); border-radius: 8px; }
.model-warning :deep(svg), .model-demo-note :deep(svg) { flex: none; color: var(--ui-primary); }
.model-tabs { display: flex; gap: 3px; overflow-x: auto; margin-top: 18px; border-bottom: 1px solid var(--ui-border); }
.model-tabs button { min-height: 40px; display: flex; align-items: center; gap: 7px; padding: 0 12px; color: var(--ui-muted); background: transparent; border: 0; border-bottom: 2px solid transparent; font-size: 10px; white-space: nowrap; cursor: pointer; }
.model-tabs button.is-active { color: var(--ui-primary); border-bottom-color: var(--ui-primary); font-weight: 700; }
.model-tabs button span { min-width: 17px; padding: 1px 5px; color: var(--ui-muted); background: var(--ui-surface-soft); border-radius: 999px; text-align: center; font-size: 8px; }
.model-list { overflow: hidden; margin-top: 12px; padding: 0; }
.model-list__toolbar { min-height: 48px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 14px; border-bottom: 1px solid var(--ui-border); }
.model-list__toolbar label { display: flex; align-items: center; gap: 7px; color: var(--ui-muted); }
.model-list__toolbar input { width: min(340px, 55vw); color: var(--ui-ink); background: transparent; border: 0; outline: 0; font-size: 10px; }
.model-list__toolbar > span { color: var(--ui-muted); font-size: 9px; }
.model-row { min-height: 65px; display: grid; grid-template-columns: 30px minmax(130px, 1fr) minmax(130px, 1fr) minmax(80px, .6fr) 65px auto; align-items: center; gap: 10px; padding: 9px 14px; border-bottom: 1px solid var(--ui-border); }
.model-row:last-child { border-bottom: 0; }
.model-row__icon { width: 28px; height: 28px; display: grid; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 8px; }
.model-row__name { display: grid; gap: 3px; min-width: 0; }
.model-row__name strong { overflow: hidden; color: var(--ui-ink); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.model-row__name code, .model-row__endpoint, .model-row__key { overflow: hidden; color: var(--ui-muted); font-family: var(--ui-font-mono); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.model-tag { margin-left: 4px; padding: 2px 4px; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 4px; font-size: 7px; font-weight: 500; }
.model-default { display: flex; align-items: center; gap: 4px; color: var(--ui-warning); font-size: 8px; }
.model-action { display: inline-flex; align-items: center; justify-content: center; min-height: 27px; padding: 0 6px; color: var(--ui-text); background: transparent; border: 1px solid var(--ui-border); border-radius: 6px; font-size: 8px; white-space: nowrap; cursor: pointer; }
.model-action--default { color: var(--ui-primary); }
.model-action--danger { color: var(--ui-danger); }
.model-row__actions { display: flex; gap: 4px; }
.model-empty { min-height: 180px; display: grid; justify-items: center; align-content: center; gap: 9px; color: var(--ui-muted); }
.model-empty strong { color: var(--ui-ink); font-size: 11px; }
.model-demo-note { margin-top: 12px; color: var(--ui-muted); }
.dialog-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; overflow-y: auto; padding: 20px; background: rgba(15, 35, 60, .4); }
.dialog-card { width: min(100%, 480px); max-height: 90vh; overflow-y: auto; padding: 20px; background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 14px; box-shadow: var(--shadow-lg); }
.dialog-card--compact { width: min(100%, 400px); }
.dialog-card__heading { display: flex; justify-content: space-between; }
.section-icon { width: 34px; height: 34px; display: grid; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 10px; }
.demo-icon-button { width: 32px; height: 32px; display: grid; place-items: center; color: var(--ui-muted); background: transparent; border: 0; cursor: pointer; }
.dialog-card h2 { margin: 12px 0; color: var(--ui-ink); font-size: 16px; }
.dialog-card__desc { color: var(--ui-muted); font-size: 10px; }
.form-field { display: grid; gap: 5px; margin-top: 11px; }
.form-field > span { color: var(--ui-ink); font-size: 9px; font-weight: 600; }
.form-field input, .form-field select { min-height: 36px; padding: 0 9px; color: var(--ui-text); background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 7px; font-size: 10px; }
.form-field small { color: var(--ui-muted); font-size: 8px; }
.model-check { display: flex; align-items: center; gap: 7px; margin-top: 10px; color: var(--ui-text); font-size: 9px; }
.model-check input { accent-color: var(--ui-primary); }
.form-error { color: var(--ui-danger); font-size: 9px; }
.dialog-card__actions { display: flex; justify-content: flex-end; gap: 7px; margin-top: 16px; }
@media (max-width: 900px) { .model-row { grid-template-columns: 28px minmax(120px, 1fr) minmax(100px, 1fr) auto; } .model-row__key, .model-default, .model-action--default { display: none; } }
@media (max-width: 600px) { .model-row { grid-template-columns: 28px minmax(0, 1fr) auto; gap: 7px; } .model-row__endpoint { grid-column: 2; } .model-row__actions { grid-column: 3; grid-row: 1 / span 2; flex-direction: column; } }
</style>
