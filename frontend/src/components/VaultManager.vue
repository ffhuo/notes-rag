<script setup>
// Vault 管理页（T3.2 / 规范 §5.1）：卡片网格 + 筛选 + 空态 + 添加/上传。
//
// 两种添加方式（「本地」一律指浏览器的机器，服务端那台一律叫「服务器」，别混）：
//  1) 服务器目录：填 name + **服务器上**的绝对路径 → POST /vaults（JSON，source_type=local）
//  2) 上传本机文件夹：选文件夹 → 本机打包成 zip → POST /vaults/upload（source_type=uploaded）
//
// 文件过滤（§16.3）：只配「不索引什么」—— 排除规则一份清单（exclude）加单文件大小上限。
// 不做包含/扩展名白名单：没被排除的就是要索引的，多一层白名单会让「某文件为何没进库」
// 变成两道推理。排除清单的唯一定义处是 VaultFilters，目录树勾选只往它追加。
// 服务器目录填好路径即可浏览目录；上传则在**选好文件夹后**就能浏览 —— 所选文件夹的
// webkitRelativePath 已经带了完整层级，不必等解压（见 dirTreeOf）。因此上传是「一次点击」
// 建库：过滤随后的 PATCH 一并落库，不再有「上传完再点一次保存过滤」这一步。
// 建库后随时可通过卡片上的「过滤设置」改（PATCH /vaults/{id}，改动下次同步生效）。
//
// 建库成功即**自动提交首个索引作业**并跳任务页（一个 vault 一次执行 = 一个任务）：
// 用户不用再猜「建完了为什么没动静」。提交失败不回滚 vault（库已建好），提示手动点「同步」重试。
//
// 索引类按钮**不再同步等待**（后端一律 202，M03 §5.13）：
//   · 同步      增量对账（日常用，通常数秒）
//   · 预览变更  dry_run 作业，停在 stage=plan_ready，先在任务页看计划再决定
//   · 重建索引  全量重算（换 embedding / 分块参数 / 索引疑似损坏时才用，分钟级）
// 提交后跳转 /tasks?run_id=…，让用户立刻看到进度，而不是盯着一个没有反馈的按钮。
//
// 作业数据来自公共件 useRunsPolling（与侧栏作业状态、Tasks 页共用一份请求）。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { vaultsApi } from '../api'
import { useRunsPolling } from '../composables/useRunsPolling'
import { isTerminal, relativeTime } from '../jobs'
import { setTopbarActions, clearTopbarActions } from '../shell'
import { toast } from '../toast'
import { PACK_LIMITS, formatBytes, summarize } from '../transport/zip'
import { uploadVault } from '../transport/upload'
import AppButton from './AppButton.vue'
import AppCard from './AppCard.vue'
import AppConfirm from './AppConfirm.vue'
import AppEmptyState from './AppEmptyState.vue'
import AppField from './AppField.vue'
import AppIcon from './AppIcon.vue'
import AppInput from './AppInput.vue'
import AppModal from './AppModal.vue'
import AppProgress from './AppProgress.vue'
import AppSelect from './AppSelect.vue'
import AppStatusBadge from './AppStatusBadge.vue'
import VaultFilters from './VaultFilters.vue'

const router = useRouter()
const { vaults, runs, loading, error, refresh } = useRunsPolling()

/**
 * 默认排除项（Obsidian / 通用笔记库都不该入库的东西）。
 *
 * 与后端 settings.ingest_exclude_dirs（.env 的 INGEST_EXCLUDE_DIRS）对齐：那边是
 * 「目录名」语义、始终生效；这边写成 `<目录>/**` 的相对路径 glob，落在 vault.filters.exclude
 * 上。两处都留着同一份清单看起来重复，但目的不同 —— 服务端那份是不可改的兜底，
 * 前端这份让用户**看得见**当前排除范围，并能按库调整（例如 Obsidian 的 .trash 关掉了回收站）。
 *
 * 必须声明在组件状态之前：下面 addForm 初始化时就要用它（const 有暂时性死区）。
 */
const DEFAULT_EXCLUDES = [
  '.obsidian/**',
  '.trash/**',
  '.git/**',
  'node_modules/**',
  '__pycache__/**',
  '.venv/**',
]

const filterText = ref('')
const filterSource = ref('')
const filterState = ref('')

const addOpen = ref(false)
const addSaving = ref(false)
const addForm = ref({ type: 'local', name: '', path: '', filters: emptyFilters() })
/** 所选文件夹的文件列表（webkitdirectory 给的是 FileList，条目带 webkitRelativePath）。 */
const folderFiles = ref(null)
/** 打包进度，按文件数计；total=0 表示未开始。 */
const packProgress = ref({ done: 0, total: 0 })
/** 体积/数量超阈值时先确认再打包（整目录要读进内存压缩）。 */
const packConfirmOpen = ref(false)
const packSummary = ref(null)
const folderInput = ref(null)

const editOpen = ref(false)
const editSaving = ref(false)
const editTarget = ref(null)
const editForm = ref({ name: '', filters: emptyFilters() })

const confirmOpen = ref(false)
const confirmTarget = ref(null)
const confirmLoading = ref(false)

const actionError = ref('')

/* ---------- 过滤表单 ↔ API 契约 ---------- */

/** 表单态默认值（形状见 VaultFilters 注释）；新库默认带上排除项，勾目录在此基础上追加。 */
function emptyFilters() {
  return { exclude: DEFAULT_EXCLUDES.join('\n'), maxKb: '' }
}

/** VaultOut.filters → 表单态；exclude 为空表示「没配过」→ 显示服务端默认排除项。 */
function filtersFromVault(v) {
  const f = v?.filters || {}
  const exclude = [...(f.exclude || [])]
  return {
    exclude: (exclude.length ? exclude : DEFAULT_EXCLUDES).join('\n'),
    maxKb: f.max_file_size ? String(Math.round(f.max_file_size / 1024)) : '',
  }
}

/** 表单态 → IngestFilters；两项全空则返回 null（= 清空过滤，回到服务端默认）。 */
function filtersPayload(form) {
  const out = {}
  const exclude = splitList(form.exclude).map(normalizeRule)
  if (exclude.length) out.exclude = exclude
  const kb = Number(form.maxKb)
  if (form.maxKb !== '' && Number.isFinite(kb) && kb > 0) out.max_file_size = Math.round(kb * 1024)
  return Object.keys(out).length ? out : null
}

/** 纯扩展名写法（`.py` / `.md`，不含 `/` 与通配符）。 */
const EXT_ONLY = /^\.[A-Za-z0-9]+$/

/**
 * 规则归一化：`.py` → `*.py`。
 *
 * 后端 exclude 走 fnmatch 全路径匹配，`.py` 只能精确命中「文件名就叫 .py」的文件；
 * 补上 `*`（fnmatch 的 `*` 跨 `/`）才能命中任意层级的 .py 文件。用户的心智是
 * 「写扩展名就是排除这类文件」，所以在这里补齐，而不是要求他记住写 `*.py`。
 */
function normalizeRule(rule) {
  return EXT_ONLY.test(rule) ? `*${rule}` : rule
}

function splitList(text) {
  return String(text || '')
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** 卡片上的过滤摘要；未设置过滤返回空串（不占一行）。 */
function filterSummary(v) {
  const f = v?.filters
  if (!f) return ''
  const parts = []
  if (f.exclude?.length) parts.push(`排除 ${f.exclude.length} 项`)
  if (f.max_file_size) parts.push(`≤ ${Math.round(f.max_file_size / 1024)} KB`)
  return parts.length ? parts.join(' · ') : ''
}

/** 是否已选好待上传的文件夹（决定过滤区文案与目录树是否可用）。 */
const hasFolder = computed(() => !!folderFiles.value?.length)

/**
 * 所选文件夹 → 嵌套目录树（上传前的本地预览）。
 *
 * webkitdirectory 给每个 File 带 webkitRelativePath（选 `notes` → `notes/a/b.md`），
 * 所以不用等服务端解压就能算出完整层级。首段是所选文件夹本身（vault 的根，打包时会被
 * 剥掉），末段是文件名，中间才是目录。隐藏目录与 __MACOSX 在这里就跳过，与打包丢弃规则
 * 及服务端浏览端点保持一致（否则本地树里勾得到、上传后树里却没有）。
 */
function dirTreeOf(files) {
  const root = {}
  for (const f of files) {
    const parts = (f.webkitRelativePath || '').split('/')
    if (parts.length < 2) continue
    let node = root
    for (const dir of parts.slice(1, -1)) {
      if (dir.startsWith('.') || dir === '__MACOSX') break   // break：整条路径都在被丢的子树里
      node[dir] = node[dir] || {}
      node = node[dir]
    }
  }
  return root
}

/** 目录树的根：服务器目录用路径输入框的值；上传类型没有服务端目录可浏览（还没解压），走本地树。 */
const addFiltersRoot = computed(() =>
  addForm.value.type === 'uploaded' ? '' : addForm.value.path.trim(),
)

/** 上传类型：所选文件夹算出的本地目录树；没选文件夹时为 null（目录树按钮禁用）。 */
const addLocalDirs = computed(() =>
  addForm.value.type === 'uploaded' && hasFolder.value ? dirTreeOf(folderFiles.value) : null,
)

/** 目录树的根：改配置时用 vault 自己的源目录（服务器上的绝对路径）。 */
const editFiltersRoot = computed(() => {
  const v = editTarget.value
  return v && v.source_type !== 'git' && v.source_type !== 'remote' ? v.source_value || '' : ''
})

const FILTER_SOURCE_OPTIONS = [
  { value: 'local', label: '服务器目录' },
  { value: 'uploaded', label: '上传的文件夹' },
]

const FILTER_STATE_OPTIONS = [
  { value: 'active', label: '执行中' },
  { value: 'idle', label: '空闲' },
  { value: 'failed', label: '有失败' },
]

/** vault_id → 最近一条作业（runs 已按 id 倒序，取首次出现即可）。 */
const latestByVault = computed(() => {
  const map = {}
  for (const r of runs.value) {
    if (map[r.vault_id] === undefined) map[r.vault_id] = r
  }
  return map
})

function statusOf(v) {
  return latestByVault.value[v.id]?.status || ''
}

function activeOf(v) {
  const run = latestByVault.value[v.id]
  return run && !isTerminal(run.status) ? run : null
}

const visibleVaults = computed(() => {
  const q = filterText.value.trim().toLowerCase()
  return vaults.value.filter((v) => {
    if (q && !`${v.name} ${v.source_value}`.toLowerCase().includes(q)) return false
    if (filterSource.value && v.source_type !== filterSource.value) return false
    const run = latestByVault.value[v.id]
    if (filterState.value === 'active' && !(run && !isTerminal(run.status))) return false
    if (filterState.value === 'idle' && run && !isTerminal(run.status)) return false
    if (filterState.value === 'failed' && !['failed', 'aborted', 'partial'].includes(run?.status)) return false
    return true
  })
})

const filtered = computed(
  () => filterText.value !== '' || filterSource.value !== '' || filterState.value !== '',
)

/* ---------- 添加 ---------- */

function openAdd(type = 'local') {
  addForm.value = { type, name: '', path: '', filters: emptyFilters() }
  folderFiles.value = null
  packProgress.value = { done: 0, total: 0 }
  packSummary.value = null
  actionError.value = ''
  addOpen.value = true
}

function pickFolder() {
  folderInput.value?.click()
}

function onFolder(event) {
  folderFiles.value = event.target.files || null
  packProgress.value = { done: 0, total: 0 }
}

/** 已选文件夹的摘要（带体积 —— 用户据此判断有没有误选到上级大目录）。 */
const folderLabel = computed(() => {
  if (!folderFiles.value?.length) return '未选择文件夹'
  const s = summarize(folderFiles.value)
  return `${s.count} 个文件 · ${formatBytes(s.bytes)}`
})

/** 打包中动态显示进度，长目录看起来才不像卡死。 */
const uploadLabel = computed(() => {
  const { done, total } = packProgress.value
  return total ? `打包上传 ${done}/${total}` : '上传中…'
})

/** 主按钮文案：上传入口在打包期间显示进度，其余情况是固定动词。 */
const primaryLabel = computed(() => {
  if (addForm.value.type !== 'uploaded') return '添加'
  return addSaving.value ? uploadLabel.value : '上传'
})

/** 大目录确认弹窗的正文。 */
const packSummaryText = computed(() => {
  const s = packSummary.value
  if (!s) return ''
  return `所选文件夹含 ${s.count} 个文件、约 ${formatBytes(s.bytes)}，需要先在你电脑上压缩再上传，可能要等一会儿。`
})

async function submitAdd() {
  actionError.value = ''
  const { type, name, path, filters } = addForm.value
  if (!name.trim()) {
    actionError.value = '请填写 vault 名称'
    return
  }
  if (type === 'uploaded') {
    await startUpload()
    return
  }
  if (!path.trim()) {
    actionError.value = '请填写服务器上的目录绝对路径'
    return
  }
  addSaving.value = true
  try {
    const vault = await vaultsApi.create({
      name: name.trim(),
      source_type: 'local',
      source_value: path.trim(),
      filters: filtersPayload(filters),
    })
    addOpen.value = false
    toast.success('已添加 vault')
    await refresh()
    await autoSubmit(vault.id)
  } catch (e) {
    actionError.value = e.message
  } finally {
    addSaving.value = false
  }
}

/** 打包前把关：整个目录要读进内存压缩，数量或体积超阈值先问一句再动手。 */
async function startUpload() {
  actionError.value = ''
  if (!folderFiles.value?.length) {
    actionError.value = '请选择要上传的文件夹'
    return
  }
  const s = summarize(folderFiles.value)
  if (!s.count) {
    actionError.value = '所选文件夹里没有可上传的文件'
    return
  }
  if (s.count > PACK_LIMITS.files || s.bytes > PACK_LIMITS.bytes) {
    packSummary.value = s
    packConfirmOpen.value = true
    return
  }
  await doUpload()
}

/**
 * 压缩 + 上传 + 落过滤：一次点击建库完成。
 *
 * 过滤在上传前就在本地目录树里配好了，所以上传成功后顺手把过滤 PATCH 上去，
 * 不再要用户点第二次「保存过滤」。上传端点只认 name + zip（要先解压拿到 id 才能落库），
 * 这一步没法省；但两步失败要分清：PATCH 挂了不代表库没建成，提示去卡片重配即可。
 * 最后自动提交首个索引作业并跳任务页（见 autoSubmit）。
 */
async function doUpload() {
  packConfirmOpen.value = false
  addSaving.value = true
  actionError.value = ''
  packProgress.value = { done: 0, total: 0 }
  try {
    const vault = await uploadVault(
      addForm.value.name.trim(),
      folderFiles.value,
      (done, total) => {
        packProgress.value = { done, total }
      },
    )
    addOpen.value = false
    try {
      await vaultsApi.update(vault.id, { filters: filtersPayload(addForm.value.filters) })
      toast.success('已上传 vault')
    } catch (e) {
      toast.warn(`vault 已创建，但过滤未保存（${e.message}）；可在卡片上的「过滤设置」重配`)
    }
    await refresh()
    await autoSubmit(vault.id)
  } catch (e) {
    actionError.value = e.message
  } finally {
    addSaving.value = false
  }
}

/* ---------- 过滤设置（建库后修改） ---------- */

function openEdit(v) {
  editTarget.value = v
  editForm.value = { name: v.name, filters: filtersFromVault(v) }
  actionError.value = ''
  editOpen.value = true
}

async function submitEdit() {
  const v = editTarget.value
  if (!v) return
  const name = editForm.value.name.trim()
  if (!name) {
    actionError.value = '请填写 vault 名称'
    return
  }
  editSaving.value = true
  actionError.value = ''
  try {
    await vaultsApi.update(v.id, { name, filters: filtersPayload(editForm.value.filters) })
    editOpen.value = false
    toast.success('过滤设置已保存，下次「同步」时生效')
    await refresh()
  } catch (e) {
    actionError.value = e.message
  } finally {
    editSaving.value = false
  }
}

/* ---------- 作业 ---------- */

/** 提交作业并跳到任务页；同库已有作业在跑（409）时跟随那一条，不重试（M06 ADR-8）。 */
async function goTasks(vaultId, res) {
  router.push({ name: 'tasks', query: { vault_id: String(vaultId), run_id: String(res.run_id) } })
}

/**
 * 建库成功后的自动提交：发一次增量同步，再跳任务页看进度。
 *
 * 提交失败**不回滚** vault（库已建好、上传文件已落盘），只提示可手动点「同步」重试；
 * 409 说明该 vault 已有作业在跑 —— 跟随那一条，不重试（M06 ADR-8）。
 */
async function autoSubmit(vaultId) {
  try {
    goTasks(vaultId, await vaultsApi.submitSync(vaultId, {}))
  } catch (e) {
    if (e.status === 409 && e.detail?.existing_run_id) {
      toast.info('该 vault 已有作业在运行，已跳到那条任务')
      goTasks(vaultId, { run_id: e.detail.existing_run_id })
      return
    }
    toast.warn(`vault 已创建，但首个索引作业未提交（${e.message}）；可在卡片上点「同步」重试`)
  }
}

async function submit(vaultId, payload = {}) {
  actionError.value = ''
  try {
    await goTasks(vaultId, await vaultsApi.submitSync(vaultId, payload))
  } catch (e) {
    if (e.status === 409 && e.detail?.existing_run_id) {
      toast.info('该 vault 已有作业在运行，已跳到那条任务')
      goTasks(vaultId, { run_id: e.detail.existing_run_id })
    } else {
      actionError.value = e.message
    }
  }
}

async function reindex(vaultId) {
  actionError.value = ''
  try {
    await goTasks(vaultId, await vaultsApi.reindex(vaultId))   // = submitSync(mode="rebuild")
  } catch (e) {
    if (e.status === 409 && e.detail?.existing_run_id) {
      toast.info('该 vault 已有作业在运行，已跳到那条任务')
      goTasks(vaultId, { run_id: e.detail.existing_run_id })
    } else {
      actionError.value = e.message
    }
  }
}

async function onCancel(run) {
  try {
    await vaultsApi.cancelRun(run.vault_id, run.id)
    run.cancelling = true
    toast.info('已请求停止，作业会在文件边界处停下')
    await refresh()
  } catch (e) {
    actionError.value = e.status === 409 ? '该作业已结束，无需取消' : e.message
  }
}

/* ---------- 删除（危险操作，二次确认） ---------- */

function askRemove(v) {
  confirmTarget.value = v
  confirmOpen.value = true
}

async function doRemove() {
  const v = confirmTarget.value
  if (!v) return
  confirmLoading.value = true
  try {
    await vaultsApi.remove(v.id)
    confirmOpen.value = false
    toast.success(`已删除 ${v.name}`)
    await refresh()
  } catch (e) {
    actionError.value = e.message
  } finally {
    confirmLoading.value = false
  }
}

/* ---------- 生命周期 ---------- */

onMounted(() => {
  setTopbarActions([
    {
      key: 'add',
      comp: AppButton,
      props: { variant: 'primary', icon: 'plus' },
      on: { click: () => openAdd('local') },
      text: '添加服务器目录',
    },
    {
      key: 'upload',
      comp: AppButton,
      props: { variant: 'secondary', icon: 'upload' },
      on: { click: () => openAdd('uploaded') },
      text: '上传本机文件夹',
    },
  ])
})

onUnmounted(clearTopbarActions)
</script>

<template>
  <section class="vaults">
    <header class="vaults__intro">
      <h2 class="vaults__title">Vaults</h2>
      <p class="vaults__desc">
        添加服务器上已有的目录（填绝对路径，就地索引，不复制文件），或上传你电脑上的文件夹
        （自动压缩后传到服务器）。建好后点「同步」建索引 —— 索引是后台作业，提交后会跳到任务页看进度。
      </p>
    </header>

    <div class="vaults__filters">
      <AppInput
        v-model="filterText"
        class="vaults__search"
        placeholder="搜索名称或路径"
        aria-label="搜索 vault"
      >
        <template #prefix><AppIcon name="search" :size="16" /></template>
      </AppInput>
      <AppSelect
        v-model="filterSource"
        class="vaults__filter"
        empty-label="全部来源"
        :options="FILTER_SOURCE_OPTIONS"
        aria-label="按来源类型筛选"
      />
      <AppSelect
        v-model="filterState"
        class="vaults__filter"
        empty-label="全部状态"
        :options="FILTER_STATE_OPTIONS"
        aria-label="按状态筛选"
      />
      <span class="vaults__count">
        共 {{ visibleVaults.length }} 个{{ filtered ? ` / 全部 ${vaults.length} 个` : '' }}
      </span>
    </div>

    <p v-if="actionError" class="vaults__alert">
      <AppIcon name="alert" :size="16" />
      <span>{{ actionError }}</span>
    </p>
    <p v-if="error" class="vaults__alert">
      <AppIcon name="alert" :size="16" />
      <span>无法获取 vault 列表，请检查后端与鉴权设置。</span>
    </p>

    <div v-if="loading && !vaults.length" class="vaults__grid">
      <AppCard v-for="i in 3" :key="i" padding="sm" class="vaults__card" loading />
    </div>

    <AppEmptyState
      v-else-if="!vaults.length"
      icon="folder"
      title="还没有 vault"
      description="添加服务器上已有的目录，或上传你电脑上的文件夹，即可开始索引。"
      action-text="添加服务器目录"
      action-icon="plus"
      @action="openAdd('local')"
    />

    <AppEmptyState
      v-else-if="!visibleVaults.length"
      icon="search"
      title="没有匹配的 vault"
      description="试试放宽筛选条件。"
    />

    <!-- 卡片网格 -->
    <div v-else class="vaults__grid">
      <AppCard v-for="v in visibleVaults" :key="v.id" padding="sm" class="vaults__card">
        <span class="vaults__card-head">
          <span class="vaults__name" :title="v.name">{{ v.name }}</span>
          <AppStatusBadge v-if="statusOf(v)" :status="statusOf(v)" size="sm" />
          <span v-else class="vaults__idle">尚无作业</span>
        </span>

        <span class="vaults__meta">
          <AppIcon :name="v.source_type === 'uploaded' ? 'upload' : 'folder'" :size="14" />
          <span class="vaults__meta-text">{{ v.source_value }}</span>
        </span>
        <span class="vaults__meta">
          <AppIcon name="models" :size="14" />
          <span class="vaults__meta-text">
            embed：{{ v.embed_profile_id ?? '未索引' }}
            <template v-if="v.embed_indexed_profiles?.length">
              · 已建过 [{{ v.embed_indexed_profiles.join(', ') }}]
            </template>
          </span>
        </span>
        <span class="vaults__meta">
          <AppIcon name="clock" :size="14" />
          <span class="vaults__meta-text">
            上次索引：{{ relativeTime(v.indexed_at) || '—' }}
          </span>
        </span>
        <span v-if="filterSummary(v)" class="vaults__meta">
          <AppIcon name="filter" :size="14" />
          <span class="vaults__meta-text">过滤：{{ filterSummary(v) }}</span>
        </span>

        <!-- 当前作业：内联进度 + 取消；点按跳到任务页看详情 -->
        <div v-if="activeOf(v)" class="vaults__active">
          <AppProgress :run="activeOf(v)" compact />
          <div class="vaults__active-actions">
            <AppButton
              variant="ghost"
              size="sm"
              :disabled="!!activeOf(v).cancelling"
              @click="onCancel(activeOf(v))"
            >
              {{ activeOf(v).cancelling ? '正在停止…' : '取消' }}
            </AppButton>
            <AppButton
              variant="ghost"
              size="sm"
              icon-right="chevron-right"
              @click="goTasks(v.id, { run_id: activeOf(v).id })"
            >
              查看
            </AppButton>
          </div>
        </div>

        <template #footer>
          <span class="vaults__actions">
            <AppButton variant="secondary" size="sm" icon="refresh" @click="submit(v.id, { mode: 'sync' })">
              同步
            </AppButton>
            <AppButton variant="secondary" size="sm" @click="submit(v.id, { mode: 'sync', dry_run: true })">
              预览变更
            </AppButton>
            <AppButton variant="secondary" size="sm" icon="zap" @click="reindex(v.id)">
              重建索引
            </AppButton>
            <AppButton variant="secondary" size="sm" icon="filter" @click="openEdit(v)">
              过滤设置
            </AppButton>
            <AppButton variant="danger" size="sm" icon="trash" @click="askRemove(v)">
              删除
            </AppButton>
          </span>
        </template>
      </AppCard>

      <!-- 新建入口卡 -->
      <AppCard padding="sm" interactive class="vaults__card vaults__card-new" @click="openAdd('local')">
        <span class="vaults__new">
          <AppIcon name="plus" :size="24" />
          <span>新建</span>
        </span>
      </AppCard>
    </div>

    <!-- 添加 / 上传（同一张表单，来源类型由入口决定，弹窗内不再选） -->
    <!-- 宽度 880：过滤区含目录树与规则标签，窄于此规则会挤成多行 -->
    <AppModal
      v-model="addOpen"
      :title="addForm.type === 'uploaded' ? '上传本机文件夹' : '添加服务器目录'"
      :width="880"
    >
      <div class="vaults__form">
        <AppInput v-model="addForm.name" label="名称" required placeholder="例如 notes" />

        <AppInput
          v-if="addForm.type === 'local'"
          v-model="addForm.path"
          label="服务器目录绝对路径"
          required
          mono
          placeholder="/srv/notes"
          hint="填的是运行服务的这台机器上能读到的路径，不是你自己电脑的路径 —— 那种情况请用「上传本机文件夹」"
        />
        <AppField
          v-else
          label="待上传的文件夹"
          required
          hint="选的是你电脑上的文件夹，会自动压缩后上传，不必自己先打包"
        >
          <span class="vaults__file">
            <AppButton variant="secondary" icon="upload" :disabled="addSaving" @click="pickFolder">
              选择文件夹
            </AppButton>
            <span class="vaults__file-name">{{ folderLabel }}</span>
          </span>
        </AppField>
        <input
          ref="folderInput"
          type="file"
          webkitdirectory
          directory
          multiple
          class="vaults__file-input"
          @change="onFolder"
        />

        <!-- 文件过滤：服务器目录填好路径即可配；上传选好文件夹即可（本地树，不必等解压） -->
        <p class="vaults__section">
          文件过滤
          <span class="vaults__section-hint">
            {{
              addForm.type === 'uploaded' && !hasFolder
                ? '已默认排除 Obsidian 相关目录；选好文件夹后即可在这里浏览它的目录并勾选要排除的'
                : '已默认排除 Obsidian 相关目录；排除之外的文件都会索引（服务端默认收 md / txt）'
            }}
          </span>
        </p>
        <VaultFilters
          v-model="addForm.filters"
          :root="addFiltersRoot"
          :local-dirs="addLocalDirs"
        />

        <p v-if="actionError" class="vaults__form-error">{{ actionError }}</p>
      </div>

      <template #footer>
        <AppButton variant="secondary" @click="addOpen = false">取消</AppButton>
        <AppButton variant="primary" :loading="addSaving" @click="submitAdd">
          {{ primaryLabel }}
        </AppButton>
      </template>
    </AppModal>

    <!-- 大目录确认：整目录要在本地压缩，先让用户知情再动手 -->
    <AppConfirm
      v-model="packConfirmOpen"
      title="文件夹较大，仍要上传？"
      :message="packSummaryText"
      confirm-text="继续上传"
      :loading="addSaving"
      @confirm="doUpload"
    />

    <AppConfirm
      v-model="confirmOpen"
      danger
      title="删除 vault"
      :message="`删除「${confirmTarget?.name || ''}」？同时会清掉它的索引与分块记录，不可撤销。`"
      confirm-text="删除"
      :loading="confirmLoading"
      @confirm="doRemove"
    />

    <!-- 过滤设置（建库后修改）：PATCH /vaults/{id}，改完下次同步生效 -->
    <AppModal v-model="editOpen" title="Vault 设置" :width="880">
      <div class="vaults__form">
        <AppInput v-model="editForm.name" label="名称" required placeholder="例如 notes" />
        <p class="vaults__section">
          文件过滤
          <span class="vaults__section-hint">改动在下次「同步」时生效；排除某个文件夹会让它下面的文件从索引中移除</span>
        </p>
        <VaultFilters v-model="editForm.filters" :root="editFiltersRoot" />
        <p class="vaults__tip">
          源目录（服务器上的路径）：{{ editTarget?.source_value }}
        </p>
        <p v-if="actionError" class="vaults__form-error">{{ actionError }}</p>
      </div>

      <template #footer>
        <AppButton variant="secondary" @click="editOpen = false">取消</AppButton>
        <AppButton variant="primary" :loading="editSaving" @click="submitEdit">保存</AppButton>
      </template>
    </AppModal>
  </section>
</template>

<style scoped>
.vaults {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.vaults__title {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-h1);
  line-height: var(--line-height-h1);
  font-weight: var(--font-weight-semibold);
}

.vaults__desc {
  margin: var(--space-1) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

/* ---------- 筛选 ---------- */
.vaults__filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.vaults__search {
  flex: 1 1 200px;
  min-width: 0;
}

.vaults__filter {
  width: 150px;
}

.vaults__count {
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.vaults__alert {
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

/* ---------- 卡片网格 ---------- */
.vaults__grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
.vaults__card {
  flex: 1 1 300px;
  min-width: 0;
}

.vaults__card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-width: 0;
}

.vaults__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-primary);
  font-size: var(--font-size-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--font-weight-semibold);
}

.vaults__idle {
  flex: none;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.vaults__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.vaults__meta-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vaults__active {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding-top: var(--space-1);
  border-top: var(--border-width) solid var(--color-border);
}

.vaults__active-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-1);
}

.vaults__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
  width: 100%;
}

.vaults__card-new {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 160px;
  border-style: dashed;
}

.vaults__new {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

/* ---------- 添加表单 ---------- */
.vaults__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.vaults__file {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.vaults__file-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.vaults__file-input {
  display: none;
}

.vaults__form-error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

/* 表单里的分组小标题（不用 <label>：它后面跟着多个控件，label 会误关联第一个） */
.vaults__section {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-2);
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  font-weight: var(--font-weight-semibold);
}

.vaults__section-hint {
  color: var(--color-text-muted);
  font-weight: var(--font-weight-regular);
}

.vaults__tip {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  word-break: break-all;
}

@media (max-width: 767px) {
  .vaults__filter {
    flex: 1 1 100%;
    width: auto;
  }
  .vaults__count {
    margin-left: 0;
  }
}
</style>
