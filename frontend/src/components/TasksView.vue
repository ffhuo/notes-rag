<script setup>
// 任务与进度页（/tasks）—— 数据看板核心页（规范 §5.2）。
//
// 为什么必须有这一页：后端所有写入类操作都返回 202 + run_id（M03 §5.13），
// 若前端只弹一个 toast，用户点完「重建索引」后 10 分钟不知道发生了什么。
//
// 本页职责：
//   · KPI 卡片：一眼看清「执行中 / 排队 / 今日成功 / 今日失败」
//   · 筛选表格：vault × 状态 × 时间范围，可排序
//   · 行展开详情：同步计划（dry_run）/ 失败清单 / 护栏原因 / 错误
//   · 取消作业（协作式：在文件边界生效，所以不是瞬时）
// 进度轮询由公共件 useRunsPolling 承担（与侧栏作业状态共用一份请求）：
// 全部终态停表、页面不可见暂停，见 §5.2 / M03 §5.4.5「不要空转」。
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { vaultsApi } from '../api'
import { useRunsPolling } from '../composables/useRunsPolling'
import { STATUS, countsSummary, isTerminal, percent, relativeTime, stageLabel } from '../jobs'
import { setTopbarActions, clearTopbarActions } from '../shell'
import { statusColor, toneColor } from '../statusStyles'
import { toast } from '../toast'
import AppButton from './AppButton.vue'
import AppCard from './AppCard.vue'
import AppIcon from './AppIcon.vue'
import AppProgress from './AppProgress.vue'
import AppSelect from './AppSelect.vue'
import AppStatusBadge from './AppStatusBadge.vue'
import AppTable from './AppTable.vue'

const route = useRoute()
const router = useRouter()

const { runs, vaults, loading, error, refresh } = useRunsPolling()

const details = ref({})          // key = `${vault_id}:${id}` → SyncRunDetail
const expanded = ref([])         // AppTable 受控展开：key 列表
const filterVault = ref('')
const filterStatus = ref('')
const filterRange = ref('')
const actionError = ref('')

/* ---------- 筛选 ---------- */

// 状态筛选项来自 jobs.js 的唯一来源，避免页面再定义一份状态语义
const STATUS_OPTIONS = [
  { value: 'active', label: '进行中' },
  ...Object.entries(STATUS).map(([value, info]) => ({ value, label: info.label })),
]

const RANGE_OPTIONS = [
  { value: 'day', label: '近 24 小时' },
  { value: 'week', label: '近 7 天' },
]

const vaultOptions = computed(() => vaults.value.map((v) => ({ value: String(v.id), label: v.name })))

// 时间字段（started_at / finished_at）是 UTC 毫秒时间戳，直接参与数值运算。
function withinRange(ts) {
  if (!filterRange.value) return true
  if (!Number.isFinite(ts)) return false
  const span = filterRange.value === 'day' ? 86_400_000 : 7 * 86_400_000
  return Date.now() - ts <= span
}

const visibleRuns = computed(() =>
  runs.value.filter((r) => {
    if (filterVault.value && String(r.vault_id) !== filterVault.value) return false
    if (filterStatus.value === 'active' && isTerminal(r.status)) return false
    if (filterStatus.value && filterStatus.value !== 'active' && r.status !== filterStatus.value) return false
    return withinRange(r.started_at)
  }),
)

const filtered = computed(
  () =>
    filterVault.value !== '' ||
    filterStatus.value !== '' ||
    filterRange.value !== '',
)

/* ---------- KPI（规范 §5.2） ---------- */

function isToday(ts) {
  if (!Number.isFinite(ts)) return false
  const d = new Date(ts)
  const now = new Date()
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
}

const kpis = computed(() => {
  const list = runs.value
  const count = (fn) => list.filter(fn).length
  return [
    { key: 'running', label: '执行中', icon: 'zap', tone: 'info', value: count((r) => r.status === 'running') },
    { key: 'queued', label: '排队', icon: 'clock', tone: 'muted', value: count((r) => r.status === 'queued') },
    { key: 'ok', label: '今日成功', icon: 'check', tone: 'ok', value: count((r) => r.status === 'success' && isToday(r.started_at)) },
    { key: 'bad', label: '今日失败', icon: 'alert', tone: 'danger', value: count((r) => (r.status === 'failed' || r.status === 'aborted') && isToday(r.started_at)) },
  ]
})

/* ---------- 表格 ---------- */

const columns = [
  { key: 'id', label: '作业', width: '64px', mono: true, sortable: true },
  { key: 'vault_name', label: 'vault' },
  { key: 'status', label: '状态' },
  { key: 'stage', label: '阶段' },
  { key: 'progress', label: '进度' },
  { key: 'elapsed_ms', label: '耗时', align: 'right', sortable: true },
]

const rowKey = (row) => `${row.vault_id}:${row.id}`

function fmtDuration(ms) {
  if (!ms || ms < 0) return '—'
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rest = Math.round(s % 60)
  return rest ? `${m}m ${rest}s` : `${m}m`
}

/** 运行中作业后端还没写 elapsed_ms，用开始时间现算（轮询刷新时会跟着走）。 */
function elapsedOf(row) {
  if (row.elapsed_ms) return fmtDuration(row.elapsed_ms)
  if (!isTerminal(row.status) && Number.isFinite(row.started_at)) {
    return fmtDuration(Date.now() - row.started_at)
  }
  return '—'
}

/** 悬停提示用的绝对时间（本地时区可读格式）；无值返回空串。 */
function absTime(ts) {
  return Number.isFinite(ts) ? new Date(ts).toLocaleString() : ''
}

/**
 * 列表「进度」列的文字：有确定分母才报数字，否则明说进度不可知。
 *
 * 不在这里重复阶段名 —— 表格已有独立的「阶段」列；原先只画一根不带数字的进度条，
 * 用户看不出「处理到第几个」，故改为文字 + 细条。
 */
function progressText(row) {
  if (row.total === null || row.total === undefined) {
    return row.status === 'queued' ? '等待开始' : '统计中…'
  }
  return `${row.processed || 0} / ${row.total} · ${percent(row)}%`
}

/* ---------- 详情加载 ---------- */

async function loadDetail(vaultId, runId) {
  const key = `${vaultId}:${runId}`
  try {
    const detail = await vaultsApi.getRun(vaultId, runId)
    details.value = { ...details.value, [key]: detail }
  } catch {
    /* 详情拉取失败不影响列表本身 */
  }
}

async function refreshOpenDetails() {
  await Promise.all(
    expanded.value.map((key) => {
      const [v, r] = key.split(':')
      return loadDetail(Number(v), Number(r))
    }),
  )
}

function onToggleExpand(key) {
  if (expanded.value.includes(key)) {
    expanded.value = expanded.value.filter((k) => k !== key)
    return
  }
  expanded.value = [...expanded.value, key]
  const [v, r] = key.split(':')
  loadDetail(Number(v), Number(r))
}

// 轮询刷新后，已展开的行跟着更新（计划 / 当前文件 / 失败清单都要新鲜）
watch(runs, () => {
  if (expanded.value.length) refreshOpenDetails()
})

/* ---------- 操作 ---------- */

async function onRefresh() {
  await refresh()
}

async function onCancel(row) {
  actionError.value = ''
  try {
    await vaultsApi.cancelRun(row.vault_id, row.id)
    // 204 ≠ 已停止：立刻进入「正在停止…」，靠轮询等到 status=cancelled
    row.cancelling = true
    toast.info('已请求停止，作业会在文件边界处停下')
    await refresh()
  } catch (e) {
    if (e.status === 409) {
      actionError.value = '该作业已结束，无需取消'
      await refresh()
    } else {
      actionError.value = e.message
    }
  }
}

/** 终态里除「已完成」外都可继续：中断 / 取消 / 失败 / 部分完成都能靠一次增量同步补齐。 */
function canResume(row) {
  return isTerminal(row.status) && row.status !== 'success'
}

/**
 * 提交一次增量执行并跳到新作业；同库已有作业在跑（409）时跟随那一条，不重试（M06 ADR-8）。
 *
 * 「执行预览」与「继续」只差一句提示语，共用同一条提交路径。
 */
async function submitSyncAndFollow(vaultId, successMsg) {
  try {
    const res = await vaultsApi.submitSync(vaultId, { mode: 'sync', dry_run: false })
    toast.success(successMsg)
    expanded.value = []
    router.replace({ query: { ...route.query, vault_id: String(vaultId), run_id: String(res.run_id) } })
    await refresh()
  } catch (e) {
    if (e.status === 409 && e.detail?.existing_run_id) {
      toast.info('该 vault 已有作业在运行，已跳到那条任务')
      expanded.value = []
      router.replace({ query: { ...route.query, vault_id: String(vaultId), run_id: String(e.detail.existing_run_id) } })
      await refresh()
    } else {
      actionError.value = e.message
    }
  }
}

/** dry_run 第二段：用户看过计划后确认执行（后端会**重新对账**，不复用第一段的计划）。 */
async function onConfirmPlan(row) {
  actionError.value = ''
  await submitSyncAndFollow(row.vault_id, '已提交执行')
}

/**
 * 中断/失败后续跑：重新提交一次增量同步。
 *
 * 不做断点续跑（见 run_service.recover_stale）：已索引文件的 size+mtime 未变 →
 * 判 unchanged 直接跳过，不重复嵌入；只有中断时没处理完的那些文件会真正重跑。
 */
async function onResume(row) {
  actionError.value = ''
  await submitSyncAndFollow(row.vault_id, '已提交继续执行')
}

/* ---------- 生命周期 ---------- */

function applyQuery() {
  const v = route.query.vault_id
  const runId = route.query.run_id
  if (v) filterVault.value = String(v)
  if (v && runId) {
    const key = `${v}:${runId}`
    if (!expanded.value.includes(key)) expanded.value = [...expanded.value, key]
    loadDetail(Number(v), Number(runId))
  }
}

onMounted(() => {
  setTopbarActions([
    {
      key: 'refresh',
      comp: AppButton,
      props: { variant: 'secondary', icon: 'refresh' },
      on: { click: onRefresh },
      text: '刷新',
    },
  ])
  applyQuery()
})

onUnmounted(clearTopbarActions)

watch(() => route.query.run_id, (v) => {
  if (v) applyQuery()
})
</script>

<template>
  <section class="tasks">
    <header class="tasks__intro">
      <h2 class="tasks__title">任务与进度</h2>
      <p class="tasks__desc">
        索引是异步作业：提交后立即返回、在后台推进。这里可以看进度、看计划、随时取消。
      </p>
    </header>

    <!-- KPI：数据看板的入口信息 -->
    <div class="tasks__kpis">
      <AppCard v-for="k in kpis" :key="k.key" padding="sm" class="tasks__kpi">
        <span class="tasks__kpi-head">
          <AppIcon :name="k.icon" :size="16" />
          <span class="tasks__kpi-label">{{ k.label }}</span>
        </span>
        <span class="tasks__kpi-value" :style="{ color: toneColor(k.tone) }">{{ k.value }}</span>
      </AppCard>
    </div>

    <!-- 筛选栏：列表页必须内置筛选（规范 §1「筛选即骨架」） -->
    <div class="tasks__filters">
      <AppSelect
        v-model="filterVault"
        class="tasks__filter"
        empty-label="全部 vault"
        :options="vaultOptions"
        aria-label="按 vault 筛选"
      />
      <AppSelect
        v-model="filterStatus"
        class="tasks__filter"
        empty-label="全部状态"
        :options="STATUS_OPTIONS"
        aria-label="按状态筛选"
      />
      <AppSelect
        v-model="filterRange"
        class="tasks__filter"
        empty-label="全部时间"
        :options="RANGE_OPTIONS"
        aria-label="按时间范围筛选"
      />
      <span class="tasks__count">
        共 {{ visibleRuns.length }} 条{{ filtered ? ` / 全部 ${runs.length} 条` : '' }}
      </span>
    </div>

    <p v-if="actionError" class="tasks__alert">
      <AppIcon name="alert" :size="16" />
      <span>{{ actionError }}</span>
    </p>
    <p v-if="error" class="tasks__alert">
      <AppIcon name="alert" :size="16" />
      <span>无法获取作业列表，请检查后端与鉴权设置。</span>
    </p>

    <AppTable
      :columns="columns"
      :rows="visibleRuns"
      :loading="loading && !runs.length"
      :row-key="rowKey"
      sortable
      clickable
      expandable
      :expanded="expanded"
      empty-text="没有匹配的作业记录"
      empty-icon="inbox"
      @toggle-expand="onToggleExpand"
    >
      <template #cell-id="{ row }">
        <span class="tasks__id">#{{ row.id }}</span>
      </template>

      <template #cell-vault_name="{ row }">
        <span class="tasks__vault">{{ row.vault_name }}</span>
      </template>

      <template #cell-status="{ row }">
        <AppStatusBadge :status="row.status" size="sm" />
      </template>

      <template #cell-stage="{ row }">
        <span class="tasks__stage">{{ stageLabel(row.stage) }}</span>
      </template>

      <template #cell-progress="{ row }">
        <div class="tasks__progress">
          <span v-if="!isTerminal(row.status)" class="tasks__counts">{{ progressText(row) }}</span>
          <AppProgress v-if="!isTerminal(row.status)" :run="row" compact hide-meta />
          <span v-else class="tasks__counts">{{ countsSummary(row) }}</span>
        </div>
      </template>

      <template #cell-elapsed_ms="{ row }">
        <span class="tasks__elapsed" :title="absTime(row.started_at)">{{ elapsedOf(row) }}</span>
      </template>

      <template #row-actions="{ row }">
        <AppButton
          v-if="!isTerminal(row.status)"
          variant="secondary"
          size="sm"
          icon="stop"
          :disabled="!!row.cancelling"
          @click="onCancel(row)"
        >
          {{ row.cancelling ? '正在停止…' : '取消' }}
        </AppButton>
        <AppButton
          v-else-if="canResume(row)"
          variant="secondary"
          size="sm"
          icon="play"
          @click="onResume(row)"
        >
          继续
        </AppButton>
      </template>

      <!-- 行展开：计划快照 / 失败清单 / 护栏原因 / 错误 -->
      <template #row-expand="{ row }">
        <div class="tasks__detail">
          <p class="tasks__detail-meta">
            <span>触发方式：{{ row.trigger }}</span>
            <span>模式：{{ row.mode }}{{ row.dry_run ? ' · 预览' : '' }}</span>
            <span>开始：{{ relativeTime(row.started_at) || '—' }}</span>
          </p>
          <div v-if="details[`${row.vault_id}:${row.id}`]" class="tasks__detail-body">
            <div class="tasks__grid">
              <div><label>阶段</label>{{ stageLabel(details[`${row.vault_id}:${row.id}`].stage) }}</div>
              <div><label>本次需处理</label>{{ details[`${row.vault_id}:${row.id}`].total ?? '统计中' }}</div>
              <div><label>已处理</label>{{ details[`${row.vault_id}:${row.id}`].processed ?? 0 }}</div>
              <div><label>变更</label>{{ countsSummary(details[`${row.vault_id}:${row.id}`]) }}</div>
              <div><label>未变化</label>{{ details[`${row.vault_id}:${row.id}`].unchanged ?? '—' }}</div>
              <div><label>失败</label>{{ details[`${row.vault_id}:${row.id}`].failed_cnt ?? 0 }}</div>
            </div>

            <!-- 正在处理哪个文件：长任务里这是唯一能确认「没卡死」的信号 -->
            <p v-if="details[`${row.vault_id}:${row.id}`].current_item" class="tasks__msg">
              正在处理：<code>{{ details[`${row.vault_id}:${row.id}`].current_item }}</code>
            </p>

            <p v-if="details[`${row.vault_id}:${row.id}`].message" class="tasks__msg">
              {{ details[`${row.vault_id}:${row.id}`].message }}
            </p>

            <!-- 护栏拦截：删除被拒绝时要讲清原因，否则用户不知道该怎么办 -->
            <p
              v-if="details[`${row.vault_id}:${row.id}`].blocked_reason"
              class="tasks__blocked"
            >
              <AppIcon name="alert" :size="16" />
              <span>
                删除已被护栏拦截（{{ details[`${row.vault_id}:${row.id}`].blocked_reason }}）：本轮只增不删。
              </span>
            </p>

            <p v-if="details[`${row.vault_id}:${row.id}`].error" class="tasks__alert">
              <AppIcon name="alert" :size="16" />
              <span>{{ details[`${row.vault_id}:${row.id}`].error }}</span>
            </p>

            <!-- dry_run 的计划快照 + 第二段确认 -->
            <template v-if="details[`${row.vault_id}:${row.id}`].plan">
              <h4 class="tasks__sub">同步计划（预览）</h4>
              <div class="tasks__grid">
                <div><label>新增</label>{{ details[`${row.vault_id}:${row.id}`].plan.adds }}</div>
                <div><label>修改</label>{{ details[`${row.vault_id}:${row.id}`].plan.updates }}</div>
                <div><label>移动</label>{{ details[`${row.vault_id}:${row.id}`].plan.moves }}</div>
                <div><label>删除</label>{{ details[`${row.vault_id}:${row.id}`].plan.deletes }}</div>
              </div>
              <p class="tasks__hint">执行时会<strong>重新比对</strong>，计划可能已过期。</p>
              <AppButton variant="primary" size="sm" icon="play" @click="onConfirmPlan(row)">
                执行这次同步
              </AppButton>
            </template>

            <!-- 失败清单：这是「为什么这个文件没被索引」的唯一可查来源 -->
            <template v-if="details[`${row.vault_id}:${row.id}`].result?.failed_files?.length">
              <h4 class="tasks__sub">失败文件</h4>
              <ul class="tasks__failed">
                <li v-for="(f, i) in details[`${row.vault_id}:${row.id}`].result.failed_files" :key="i">
                  <code>{{ f.path }}</code> — {{ f.reason }}
                </li>
              </ul>
            </template>
          </div>
          <p v-else class="tasks__hint">详情加载中…</p>
        </div>
      </template>
    </AppTable>
  </section>
</template>

<style scoped>
.tasks {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.tasks__title {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-h1);
  line-height: var(--line-height-h1);
  font-weight: var(--font-weight-semibold);
}

.tasks__desc {
  margin: var(--space-1) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

/* ---------- KPI ---------- */
.tasks__kpis {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
.tasks__kpi {
  flex: 1 1 140px;
  min-width: 0;
}

.tasks__kpi-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.tasks__kpi-value {
  font-size: var(--font-size-display);
  line-height: var(--line-height-display);
  font-weight: var(--font-weight-semibold);
  font-variant-numeric: tabular-nums;
}

/* ---------- 筛选 ---------- */
.tasks__filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.tasks__filter {
  width: 160px;
}

.tasks__count {
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

/* ---------- 提示条 ---------- */
.tasks__alert,
.tasks__blocked {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: var(--border-width) solid var(--color-border);
  border-left-width: 3px;
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}
.tasks__alert {
  color: var(--color-danger);
  border-left-color: var(--color-danger);
  background: var(--color-bg-surface);
}
.tasks__blocked {
  color: var(--color-warning);
  border-left-color: var(--color-warning);
  background: var(--color-bg-surface);
}

/* ---------- 单元格 ---------- */
.tasks__id {
  color: var(--color-text-secondary);
}
.tasks__vault {
  font-weight: var(--font-weight-semibold);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tasks__stage {
  color: var(--color-text-secondary);
}
.tasks__counts,
.tasks__elapsed {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* 进度列：数值在上、细条在下，两行共用一个单元格 */
.tasks__progress {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

/* ---------- 展开详情 ---------- */
.tasks__detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.tasks__detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.tasks__detail-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.tasks__grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-6);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  font-variant-numeric: tabular-nums;
}
.tasks__grid label {
  display: block;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.tasks__sub {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--font-weight-semibold);
}

.tasks__msg,
.tasks__hint {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.tasks__failed {
  margin: 0;
  padding-left: var(--space-4);
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

@media (max-width: 767px) {
  .tasks__filter {
    flex: 1 1 100%;
    width: auto;
  }
  .tasks__count {
    margin-left: 0;
  }
}
</style>
