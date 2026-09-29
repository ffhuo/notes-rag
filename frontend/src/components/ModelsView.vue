<script setup>
// 模型管理页（T3.3 / 规范 §5.5）—— LLM / Embedding 两张表 + 增删改与试连。
//
// 关键差异必须讲清楚（design.md §10 模块索引 M08）：
//   · LLM 无状态 —— 问答时随便换
//   · Embedding 与索引强绑定 —— 换模型必须对该 vault 重建索引，否则新旧向量混在同一 collection
// 因此删除被 vault 引用的 embedding **提前拦截**（按钮置灰 + 说明原因），
// 而不是等后端 409 再报错：用户点得下去却失败，是最差的一种反馈。
//
// 密钥只显示掩码（后端 api_key_masked），编辑时留空表示「不改动已存密钥」。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { modelsApi, vaultsApi } from '../api'
import { setTopbarActions, clearTopbarActions } from '../shell'
import { toast } from '../toast'
import AppButton from './AppButton.vue'
import AppConfirm from './AppConfirm.vue'
import AppEmptyState from './AppEmptyState.vue'
import AppField from './AppField.vue'
import AppIcon from './AppIcon.vue'
import AppInput from './AppInput.vue'
import AppModal from './AppModal.vue'
import AppSelect from './AppSelect.vue'
import AppTable from './AppTable.vue'

const TABS = [
  { value: 'llm', label: 'LLM 对话模型' },
  { value: 'embed', label: 'Embedding 向量模型' },
  { value: 'asr', label: '语音识别' },
]

const KIND_OPTIONS = [
  { value: 'llm', label: 'llm（对话 / 问答）' },
  { value: 'embed', label: 'embed（向量化）' },
  { value: 'asr', label: 'asr（语音转文字）' },
]

// asr 的调用协议：不同厂商的语音接口不是同一套（详见 app/api/routes/audio.py）。
// 它存进 params.protocol，缺省 = OpenAI ASR，故不新增字段也不需要迁移。
const ASR_PROTOCOL_OPTIONS = [
  { value: '', label: 'OpenAI ASR（/audio/transcriptions，默认）' },
  { value: 'dashscope_native', label: 'DashScope 原生（百炼 Qwen-Audio-3.x-ASR-Flash）' },
]

const columns = [
  { key: 'name', label: '名称', sortable: true },
  { key: 'model', label: '模型标识', mono: true },
  { key: 'base_url', label: '端点', mono: true },
  { key: 'api_key_masked', label: '密钥', mono: true },
  { key: 'is_default', label: '默认' },
]

const models = ref([])
const vaults = ref([])
const loading = ref(true)
const loadError = ref('')

const activeKind = ref('llm')
const filterText = ref('')

const editing = ref(false)
const saving = ref(false)
const formError = ref('')
const form = ref(blankForm())
const testingId = ref(null)

const confirmOpen = ref(false)
const confirmTarget = ref(null)
const confirmLoading = ref(false)

function blankForm() {
  return {
    id: null,
    kind: 'llm',
    name: '',
    model: '',
    base_url: '',
    api_key: '',
    set_default: false,
    protocol: '',   // 仅 asr 用：'' = OpenAI ASR，'dashscope_native' = 百炼原生协议
    multimodal: false,  // 仅 llm 用：是否支持图片输入（params.multimodal）
    params: {},     // 编辑时承接后端已有 params，保存时按类型增删对应键
  }
}

/* ---------- 加载 ---------- */

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    // vaults 一并拉取：删除 embedding 前的引用检查需要它（提前拦截，不等 409）
    const [ms, vs] = await Promise.all([modelsApi.list(), vaultsApi.list()])
    models.value = ms
    vaults.value = vs
  } catch (e) {
    loadError.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  setTopbarActions([
    {
      key: 'create',
      comp: AppButton,
      props: { variant: 'primary', icon: 'plus' },
      on: { click: () => openCreate() },
      text: '新建模型',
    },
    {
      key: 'refresh',
      comp: AppButton,
      props: { variant: 'secondary', icon: 'refresh' },
      on: { click: load },
      text: '刷新',
    },
  ])
  load()
})

onUnmounted(clearTopbarActions)

/* ---------- 筛选 ---------- */

const counts = computed(() => ({
  llm: models.value.filter((m) => m.kind === 'llm').length,
  embed: models.value.filter((m) => m.kind === 'embed').length,
  asr: models.value.filter((m) => m.kind === 'asr').length,
}))

const visible = computed(() => {
  const q = filterText.value.trim().toLowerCase()
  return models.value.filter((m) => {
    if (m.kind !== activeKind.value) return false
    if (q && !`${m.name} ${m.model} ${m.base_url}`.toLowerCase().includes(q)) return false
    return true
  })
})

const filtered = computed(() => filterText.value.trim() !== '')

/* ---------- 引用检查（embedding 与索引强绑定） ---------- */

/** model_id → 引用它的 vault 名称列表。 */
const referencedBy = computed(() => {
  const map = new Map()
  for (const v of vaults.value) {
    const ids = [v.embed_profile_id, ...(v.embed_indexed_profiles || [])]
    for (const id of new Set(ids.filter((x) => x !== null && x !== undefined))) {
      const names = map.get(id) || []
      names.push(v.name)
      map.set(id, names)
    }
  }
  return map
})

/** 非空 = 禁止删除，并说明该怎么做。 */
function blockReason(m) {
  const names = referencedBy.value.get(m.id) || []
  if (!names.length) return ''
  return `仍被 vault「${names.join('、')}」引用：请先为该 vault 换 embedding 并重建索引`
}

const blockedCount = computed(
  () => visible.value.filter((m) => blockReason(m)).length,
)

/* ---------- 新建 / 编辑 ---------- */

function openCreate() {
  form.value = { ...blankForm(), kind: activeKind.value }
  formError.value = ''
  editing.value = true
}

function openEdit(m) {
  form.value = {
    id: m.id,
    kind: m.kind,
    name: m.name,
    model: m.model,
    base_url: m.base_url || '',
    api_key: '',
    set_default: !!m.is_default,
    protocol: m.params?.protocol === 'dashscope_native' ? 'dashscope_native' : '',
    multimodal: !!m.params?.multimodal,
    params: { ...(m.params || {}) },
  }
  formError.value = ''
  editing.value = true
}

async function save() {
  formError.value = ''
  const f = form.value
  if (!f.name.trim()) {
    formError.value = '请填写名称'
    return
  }
  if (!f.model.trim()) {
    formError.value = '请填写模型标识'
    return
  }
  saving.value = true
  try {
    // 按类型把 UI 开关写进 params；其余 kind 不传 params，避免清空后端已有参数
    let params = null
    if (f.kind === 'asr') {
      params = { ...(f.params || {}) }
      if (f.protocol === 'dashscope_native') params.protocol = 'dashscope_native'
      else delete params.protocol
    } else if (f.kind === 'llm') {
      params = { ...(f.params || {}) }
      // 勾选 = 支持图片输入：索引时会调用该模型理解笔记里的图片
      if (f.multimodal) params.multimodal = true
      else delete params.multimodal
    }

    if (f.id) {
      const patch = {
        name: f.name.trim(),
        model: f.model.trim(),
        base_url: f.base_url.trim(),
        set_default: f.set_default,
      }
      if (params) patch.params = params
      // 留空 = 不传该字段，保留已存密钥（传空串会真的清空密钥）
      if (f.api_key) patch.api_key = f.api_key
      await modelsApi.update(f.id, patch)
    } else {
      await modelsApi.create({
        kind: f.kind,
        name: f.name.trim(),
        model: f.model.trim(),
        base_url: f.base_url.trim(),
        api_key: f.api_key,
        set_default: f.set_default,
        ...(params ? { params } : {}),
      })
    }
    editing.value = false
    toast.success(f.id ? '已保存模型配置' : '已新建模型配置')
    await load()
  } catch (e) {
    formError.value = e.status === 409 ? '同类型下已有同名配置，换个名称' : e.message
  } finally {
    saving.value = false
  }
}

/* ---------- 默认 / 试连 / 删除 ---------- */

async function makeDefault(m) {
  try {
    await modelsApi.setDefault(m.id)
    toast.success(`已把「${m.name}」设为默认`)
    await load()
  } catch (e) {
    toast.error(`设置默认失败：${e.message}`)
  }
}

async function testOne(m) {
  testingId.value = m.id
  try {
    const r = await modelsApi.test(m.id)
    if (r.ok) toast.success(`「${m.name}」连接正常${r.detail ? `：${r.detail}` : ''}`)
    else toast.error(`「${m.name}」连接失败：${r.error || '未知错误'}`)
  } catch (e) {
    toast.error(`「${m.name}」试连失败：${e.message}`)
  } finally {
    testingId.value = null
  }
}

function askRemove(m) {
  confirmTarget.value = m
  confirmOpen.value = true
}

async function doRemove() {
  const m = confirmTarget.value
  if (!m) return
  confirmLoading.value = true
  try {
    await modelsApi.remove(m.id)
    confirmOpen.value = false
    toast.success(`已删除「${m.name}」`)
    await load()
  } catch (e) {
    toast.error(e.status === 409 ? `无法删除：${e.message}` : `删除失败：${e.message}`)
  } finally {
    confirmLoading.value = false
  }
}
</script>

<template>
  <section class="models">
    <header class="models__intro">
      <h2 class="models__title">模型管理</h2>
      <p class="models__desc">
        LLM 无状态，问答时可随时换；<strong>Embedding 与索引强绑定</strong>，换模型后必须对相关
        vault 重建索引，否则新旧向量会混在一起。
      </p>
    </header>

    <!-- Tabs：两个 kind 各自一张表（规范 §5.5） -->
    <div class="models__tabs" role="tablist">
      <button
        v-for="t in TABS"
        :key="t.value"
        class="models__tab"
        :class="{ 'is-active': activeKind === t.value }"
        type="button"
        role="tab"
        :aria-selected="activeKind === t.value"
        @click="activeKind = t.value"
      >
        <span>{{ t.label }}</span>
        <span class="models__tab-count">{{ counts[t.value] }}</span>
      </button>
    </div>

    <div class="models__filters">
      <AppInput
        v-model="filterText"
        class="models__search"
        placeholder="搜索名称、模型标识或端点"
        aria-label="搜索模型配置"
      >
        <template #prefix><AppIcon name="search" :size="16" /></template>
      </AppInput>
      <span class="models__count">
        共 {{ visible.length }} 个{{ filtered ? ` / 全部 ${counts[activeKind]} 个` : '' }}
      </span>
    </div>

    <p v-if="loadError" class="models__alert">
      <AppIcon name="alert" :size="16" />
      <span>无法获取模型配置，请检查后端与鉴权设置。</span>
    </p>

    <p v-if="blockedCount" class="models__alert is-warn">
      <AppIcon name="alert" :size="16" />
      <span>
        {{ blockedCount }} 个配置仍被 vault 引用（见「默认」列旁说明），需先换 embedding 并重建索引才能删除。
      </span>
    </p>

    <AppTable
      :columns="columns"
      :rows="visible"
      :loading="loading && !models.length"
      row-key="id"
      sortable
      empty-text="暂无配置"
      empty-icon="models"
    >
      <template #cell-name="{ row }">
        <span class="models__name-cell">
          <span class="models__name">{{ row.name }}</span>
          <span v-if="row.kind === 'llm' && row.params?.multimodal" class="models__tag">
            支持图片
          </span>
        </span>
      </template>

      <template #cell-base_url="{ row }">
        <span class="models__muted">{{ row.base_url || '（OpenAI 官方端点）' }}</span>
      </template>

      <template #cell-api_key_masked="{ row }">
        <span class="models__muted">{{ row.api_key_masked || '（未设置）' }}</span>
      </template>

      <!-- 默认项：图标 + 文本双编码（不靠颜色单独表意） -->
      <template #cell-is_default="{ row }">
        <span v-if="row.is_default" class="models__default">
          <AppIcon name="star" :size="14" />
          <span>默认</span>
        </span>
        <AppButton
          v-else
          variant="ghost"
          size="sm"
          @click="makeDefault(row)"
        >
          设为默认
        </AppButton>
      </template>

      <template #empty>
        <AppEmptyState
          v-if="!counts[activeKind]"
          size="sm"
          icon="models"
          title="还没有这类模型"
          description="新建一个配置即可用于问答、索引或语音转写。"
          action-text="新建模型"
          action-icon="plus"
          @action="openCreate"
        />
        <AppEmptyState
          v-else
          size="sm"
          icon="search"
          title="没有匹配的模型"
          description="试试放宽筛选条件。"
        />
      </template>

      <template #row-actions="{ row }">
        <span class="models__row-actions">
          <AppButton
            variant="secondary"
            size="sm"
            :loading="testingId === row.id"
            @click="testOne(row)"
          >
            试连
          </AppButton>
          <AppButton variant="secondary" size="sm" @click="openEdit(row)">编辑</AppButton>
          <AppButton
            variant="danger"
            size="sm"
            icon="trash"
            :disabled="!!blockReason(row)"
            :title="blockReason(row) || '删除该配置'"
            @click="askRemove(row)"
          >
            删除
          </AppButton>
        </span>
      </template>
    </AppTable>

    <!-- 新建 / 编辑（kind 在编辑时不可改：后端 PATCH 不接受 kind） -->
    <AppModal v-model="editing" :title="form.id ? '编辑模型配置' : '新建模型配置'">
      <div class="models__form">
        <AppSelect
          v-model="form.kind"
          label="类型"
          :options="KIND_OPTIONS"
          :disabled="!!form.id"
          :hint="form.id ? '类型创建后不可更改' : ''"
        />
        <AppInput v-model="form.name" label="名称" required placeholder="例如 qwen-max / bge-m3-local" />
        <AppInput
          v-model="form.model"
          label="模型标识"
          required
          mono
          placeholder="gpt-4o-mini / text-embedding-3-small / whisper-1"
        />
        <AppInput
          v-model="form.base_url"
          label="端点 base_url"
          mono
          placeholder="https://api.openai.com/v1"
          hint="留空 = 用 OpenAI 官方端点；第三方服务请填自己的地址（如 https://api.siliconflow.cn/v1）"
        />
        <AppInput
          v-model="form.api_key"
          label="密钥 api_key"
          type="password"
          placeholder="sk-..."
          :hint="form.id ? '留空 = 不改动已存密钥；保存后只显示掩码' : '留空 = 不带鉴权（第三方服务通常必填）；保存后只显示掩码'"
        />
        <AppSelect
          v-if="form.kind === 'asr'"
          v-model="form.protocol"
          label="音频协议"
          :options="ASR_PROTOCOL_OPTIONS"
          hint="OpenAI ASR 走 multipart /audio/transcriptions；百炼 qwen3-asr-flash 是对话协议（音频走 Base64），选错会直接报错"
        />
        <AppField
          v-if="form.kind === 'llm'"
          hint="勾选后，索引会把笔记里的图片交给该模型理解并转成文字（外链直传 URL，本地图读取后转 Base64）；未勾选或没有此类模型时图片会被跳过。"
        >
          <label class="models__check">
            <input v-model="form.multimodal" type="checkbox" />
            <span>支持图片输入（多模态）</span>
          </label>
        </AppField>
        <AppField>
          <label class="models__check">
            <input v-model="form.set_default" type="checkbox" />
            <span>设为该类型的默认模型</span>
          </label>
        </AppField>
        <p v-if="formError" class="models__form-error">{{ formError }}</p>
      </div>

      <template #footer>
        <AppButton variant="secondary" :disabled="saving" @click="editing = false">取消</AppButton>
        <AppButton variant="primary" :loading="saving" @click="save">
          {{ form.id ? '保存' : '创建' }}
        </AppButton>
      </template>
    </AppModal>

    <AppConfirm
      v-model="confirmOpen"
      danger
      title="删除模型配置"
      :message="`删除「${confirmTarget?.name || ''}」？已建过索引的 vault 不会自动重建，删除后需自行换模型。`"
      confirm-text="删除"
      :loading="confirmLoading"
      @confirm="doRemove"
    />
  </section>
</template>

<style scoped>
.models {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.models__title {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-h1);
  line-height: var(--line-height-h1);
  font-weight: var(--font-weight-semibold);
}

.models__desc {
  margin: var(--space-1) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

/* ---------- Tabs ---------- */
.models__tabs {
  display: flex;
  gap: var(--space-1);
  border-bottom: var(--border-width) solid var(--color-border);
}

.models__tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--color-text-secondary);
  font-family: inherit;
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  font-weight: var(--font-weight-semibold);
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease-standard),
              border-color var(--duration-fast) var(--ease-standard);
}
.models__tab:hover {
  color: var(--color-text-primary);
}
.models__tab.is-active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.models__tab-count {
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  font-weight: var(--font-weight-regular);
  font-variant-numeric: tabular-nums;
}

/* ---------- 筛选 ---------- */
.models__filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.models__search {
  flex: 1 1 220px;
  min-width: 0;
}

.models__count {
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

/* ---------- 提示条 ---------- */
.models__alert {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: var(--border-width) solid var(--color-border);
  border-left-width: 3px;
  border-left-color: var(--color-danger);
  border-radius: var(--radius-md);
  background: var(--color-bg-surface);
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}
.models__alert.is-warn {
  border-left-color: var(--color-warning);
  color: var(--color-warning);
}

/* ---------- 单元格 ---------- */
.models__name-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  max-width: 100%;
}

.models__name {
  font-weight: var(--font-weight-semibold);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.models__tag {
  flex: none;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-primary-soft);
  color: var(--color-primary-on-soft);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

.models__muted {
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.models__default {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-primary-soft);
  color: var(--color-primary-on-soft);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

.models__row-actions {
  display: inline-flex;
  gap: var(--space-1);
}

/* ---------- 表单 ---------- */
.models__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.models__check {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 24px;
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  cursor: pointer;
}

.models__form-error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

@media (max-width: 767px) {
  .models__tabs {
    gap: 0;
  }
  .models__tab {
    flex: 1 1 0;
    justify-content: center;
    min-height: 44px;
  }
  .models__count {
    margin-left: 0;
  }
}
</style>
