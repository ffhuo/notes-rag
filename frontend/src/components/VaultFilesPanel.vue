<script setup>
import { computed } from 'vue'
import { relativeTime, statusInfo } from '../jobs'
import AppButton from './AppButton.vue'
import AppIcon from './AppIcon.vue'
import AppProgress from './AppProgress.vue'
import AppStatusBadge from './AppStatusBadge.vue'

const FILE_STATUSES = [
  { id: 'all', label: '全部' },
  { id: 'indexed', label: '索引完成' },
  { id: 'indexing', label: '索引中' },
  { id: 'pending', label: '待索引' },
  { id: 'error', label: '错误' },
]
const FILE_STATUS_LABELS = {
  indexed: '索引完成',
  indexing: '索引中',
  pending: '待索引',
  error: '错误',
}
const STATUS_TONE = {
  indexed: 'success',
  indexing: 'info',
  pending: 'muted',
  error: 'danger',
}
const SYNC_PHASES = [
  { label: '扫描文件', stages: ['probe', 'scan'] },
  { label: '比对变更', stages: ['diff', 'plan', 'plan_ready'] },
  { label: '建立索引', stages: ['index', 'prune', 'done'] },
]

const props = defineProps({
  vault: { type: Object, required: true },
  files: { type: Array, required: true },
  counts: { type: Object, required: true },
  total: { type: Number, required: true },
  page: { type: Number, required: true },
  pageSize: { type: Number, required: true },
  search: { type: String, required: true },
  status: { type: String, required: true },
  loading: { type: Boolean, required: true },
  error: { type: String, default: '' },
  scanComplete: { type: Boolean, default: true },
  run: { type: Object, default: null },
  activeRun: { type: Object, default: null },
  filterSummary: { type: String, default: '' },
  embedSummary: { type: String, default: '' },
})

const emit = defineEmits([
  'update:search',
  'update:status',
  'change-page',
  'sync',
  'preview',
  'rebuild',
  'edit-filters',
  'remove',
  'update-files',
  'refresh',
])

const pageCount = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const rangeStart = computed(() => (props.total ? (props.page - 1) * props.pageSize + 1 : 0))
const rangeEnd = computed(() => Math.min(props.page * props.pageSize, props.total))
const allFileCount = computed(() =>
  Object.values(props.counts).reduce((sum, count) => sum + count, 0),
)
const syncPhaseIndex = computed(() => {
  if (!props.run || props.run.status === 'queued') return -1
  const stage = props.run?.stage
  return SYNC_PHASES.findIndex((phase) => phase.stages.includes(stage))
})
const runFinished = computed(() => props.run && !statusInfo(props.run.status).running)

function phaseState(index) {
  if (!props.run) return ''
  if (runFinished.value && ['success', 'partial'].includes(props.run.status)) {
    return props.run.dry_run ? (index < 2 ? 'is-done' : '') : 'is-done'
  }
  if (syncPhaseIndex.value < 0) return ''
  if (index < syncPhaseIndex.value) return 'is-done'
  if (index === syncPhaseIndex.value) return 'is-active'
  return ''
}

function displayedStatus(file) {
  return props.activeRun?.current_item === file.path ? 'indexing' : file.status
}

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`
}

function modifiedLabel(timestamp) {
  return relativeTime(timestamp) || '时间未知'
}

function statusLabel(fileStatus) {
  return FILE_STATUS_LABELS[fileStatus] || fileStatus
}
</script>

<template>
  <section class="files-panel panel">
    <header class="files-panel__heading">
      <div class="files-panel__title">
        <span class="section-icon"><AppIcon name="vaults" :size="17" /></span>
        <div>
          <h2>{{ vault.name }}</h2>
          <p>{{ allFileCount }} 个符合过滤规则的文件</p>
        </div>
      </div>

      <section class="recent-sync-card" aria-label="最近一次同步">
        <div class="recent-sync-card__top">
          <span class="recent-sync-card__title"><AppIcon name="refresh" :size="14" />最近一次同步</span>
          <AppStatusBadge v-if="run" :status="run.status" size="sm" />
          <span v-else class="recent-sync-card__empty">暂无任务</span>
        </div>
        <template v-if="run">
          <AppProgress :run="run" compact />
          <ol class="sync-stages" aria-label="同步阶段">
            <li
              v-for="(phase, index) in SYNC_PHASES"
              :key="phase.label"
              :class="phaseState(index)"
              :aria-current="phaseState(index) === 'is-active' ? 'step' : undefined"
            >
              <span class="sync-stages__mark">
                <AppIcon v-if="phaseState(index) === 'is-done'" name="check" :size="10" />
                <template v-else>{{ index + 1 }}</template>
              </span>
              <span>{{ phase.label }}</span>
            </li>
          </ol>
          <div class="recent-sync-card__footer">
            <span>{{ relativeTime(run.started_at) || '时间未知' }}</span>
          </div>
          <p v-if="activeRun?.current_item" class="recent-sync-card__current" :title="activeRun.current_item">
            正在处理：{{ activeRun.current_item }}
          </p>
        </template>
        <p v-else class="recent-sync-card__hint">提交同步后会显示阶段与进度</p>
      </section>
    </header>

    <div class="vault-actions">
      <div class="vault-actions__buttons">
        <AppButton
          v-if="vault.source_type === 'uploaded'"
          variant="secondary"
          size="sm"
          icon="upload"
          :disabled="!!activeRun"
          @click="emit('update-files', vault)"
        >
          更新文件
        </AppButton>
        <template v-else>
          <AppButton variant="secondary" size="sm" icon="refresh" :disabled="!!activeRun" @click="emit('sync')">
            同步
          </AppButton>
          <AppButton variant="secondary" size="sm" :disabled="!!activeRun" @click="emit('preview')">
            预览变更
          </AppButton>
        </template>
        <AppButton variant="secondary" size="sm" icon="zap" :disabled="!!activeRun" @click="emit('rebuild')">
          重建索引
        </AppButton>
        <AppButton variant="secondary" size="sm" icon="filter" @click="emit('edit-filters', vault)">
          过滤设置
        </AppButton>
        <AppButton variant="danger" size="sm" icon="trash" @click="emit('remove', vault)">
          删除
        </AppButton>
      </div>
      <div class="files-panel__meta">
        <span><AppIcon name="clock" :size="14" />上次索引：{{ relativeTime(vault.indexed_at) || '—' }}</span>
        <span v-if="filterSummary"><AppIcon name="filter" :size="14" />{{ filterSummary }}</span>
        <span v-if="embedSummary"><AppIcon name="models" :size="14" />{{ embedSummary }}</span>
      </div>
    </div>

    <div class="files-controls">
      <div class="file-status-filters" role="group" aria-label="按索引状态筛选文件">
        <button
          v-for="item in FILE_STATUSES"
          :key="item.id"
          type="button"
          class="file-status-filter"
          :class="{ 'is-active': status === item.id, [`is-${item.id}`]: item.id !== 'all' }"
          :aria-pressed="status === item.id"
          @click="emit('update:status', item.id)"
        >
          <span v-if="item.id !== 'all'" class="file-status-filter__dot"></span>
          {{ item.label }}
          <span class="file-status-filter__count">{{ item.id === 'all' ? total : counts[item.id] || 0 }}</span>
        </button>
      </div>
      <label class="file-search">
        <AppIcon name="search" :size="15" />
        <input
          :value="search"
          type="search"
          placeholder="搜索文件"
          aria-label="搜索文件"
          @input="emit('update:search', $event.target.value)"
        />
      </label>
    </div>

    <p v-if="!scanComplete" class="file-notice" role="status">
      <AppIcon name="alert" :size="15" />扫描未完整，文件清单可能遗漏无法读取的文件。
    </p>
    <p v-if="error" class="file-error" role="alert">
      <AppIcon name="alert" :size="15" />无法读取文件清单：{{ error }}
      <AppButton variant="ghost" size="sm" @click="emit('refresh')">重试</AppButton>
    </p>

    <div v-if="files.length" class="file-list" aria-live="polite" :aria-busy="loading">
      <div v-for="file in files" :key="file.path" class="file-row">
        <span class="file-row__icon"><AppIcon name="file-text" :size="17" /></span>
        <span class="file-row__name">
          <strong :title="file.name">{{ file.name }}</strong>
          <small :title="file.path">{{ file.path }}</small>
        </span>
        <span class="file-row__updated">{{ modifiedLabel(file.modified_at) }}</span>
        <span class="file-row__size">{{ formatBytes(file.size_bytes) }}</span>
        <span class="file-status" :class="`file-status--${STATUS_TONE[displayedStatus(file)] || 'muted'}`">
          <span class="file-status__dot"></span>{{ statusLabel(displayedStatus(file)) }}
        </span>
      </div>
    </div>
    <div v-else-if="!loading && !error" class="file-empty">
      {{ allFileCount ? '没有符合当前搜索和状态筛选的文件。' : '当前 Vault 中没有符合过滤规则的文件。' }}
    </div>
    <div v-else-if="loading && !files.length" class="file-empty">正在读取文件清单…</div>

    <nav v-if="pageCount > 1" class="file-pagination" aria-label="文件列表分页">
      <span>显示 {{ rangeStart }}–{{ rangeEnd }} 项，共 {{ total }} 项</span>
      <div class="file-pagination__controls">
        <AppButton
          variant="secondary"
          size="sm"
          icon="chevron-left"
          :disabled="page <= 1"
          @click="emit('change-page', page - 1)"
        >
          上一页
        </AppButton>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
        <AppButton
          variant="secondary"
          size="sm"
          icon-right="chevron-right"
          :disabled="page >= pageCount"
          @click="emit('change-page', page + 1)"
        >
          下一页
        </AppButton>
      </div>
    </nav>
  </section>
</template>

<style scoped>
.files-panel {
  min-width: 0;
  padding: 16px;
}

.files-panel__heading,
.files-panel__title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.files-panel__heading {
  justify-content: space-between;
  align-items: stretch;
}

.files-panel__title {
  min-width: 0;
  align-self: flex-start;
}

.files-panel__title > div {
  min-width: 0;
}

.section-icon {
  width: 34px;
  height: 34px;
  display: grid;
  flex: none;
  place-items: center;
  color: var(--ui-primary);
  background: var(--ui-primary-soft);
  border-radius: 10px;
}

.files-panel__title h2 {
  overflow: hidden;
  color: var(--ui-ink);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.files-panel__title p {
  margin-top: 4px;
  color: var(--ui-muted);
  font-size: 9px;
}

.recent-sync-card {
  width: min(390px, 52%);
  min-width: 280px;
  display: grid;
  align-content: start;
  gap: 8px;
  padding: 10px 12px;
  background: var(--ui-surface-soft);
  border: 1px solid var(--ui-border);
  border-radius: 10px;
}

.recent-sync-card__top,
.recent-sync-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.recent-sync-card__title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ui-text);
  font-size: 9px;
  font-weight: var(--font-weight-semibold);
}

.recent-sync-card__title :deep(svg) {
  color: var(--ui-primary);
}

.recent-sync-card__empty,
.recent-sync-card__hint,
.recent-sync-card__footer,
.recent-sync-card__current {
  color: var(--ui-muted);
  font-size: 9px;
}

.recent-sync-card__hint {
  margin: 0;
}

.recent-sync-card__current {
  overflow: hidden;
  margin: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sync-stages {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.sync-stages li {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  color: var(--ui-muted);
  font-size: 8px;
  white-space: nowrap;
}

.sync-stages__mark {
  width: 16px;
  height: 16px;
  display: grid;
  flex: none;
  place-items: center;
  color: var(--ui-muted);
  background: var(--ui-border);
  border-radius: 50%;
  font-size: 8px;
}

.sync-stages .is-done {
  color: var(--ui-success);
}

.sync-stages .is-done .sync-stages__mark {
  color: var(--color-success-contrast);
  background: var(--ui-success);
}

.sync-stages .is-active {
  color: var(--ui-primary);
  font-weight: var(--font-weight-semibold);
}

.sync-stages .is-active .sync-stages__mark {
  color: var(--color-primary-contrast);
  background: var(--ui-primary);
}

.vault-actions {
  display: grid;
  gap: 10px;
  margin-top: 14px;
  padding: 12px 0;
  border-top: 1px solid var(--ui-border);
  border-bottom: 1px solid var(--ui-border);
}

.vault-actions__buttons,
.files-panel__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.files-panel__meta {
  gap: 14px;
  color: var(--ui-muted);
  font-size: 9px;
}

.files-panel__meta > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.files-panel__meta :deep(svg) {
  color: var(--ui-primary);
}

.files-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 12px 0 8px;
}

.file-status-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.file-status-filter {
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 8px;
  color: var(--ui-muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 7px;
  font: inherit;
  font-size: 9px;
  cursor: pointer;
}

.file-status-filter.is-active {
  color: var(--ui-primary);
  background: var(--ui-primary-soft);
  border-color: var(--ui-border);
}

.file-status-filter__dot,
.file-status__dot {
  width: 6px;
  height: 6px;
  flex: none;
  background: currentColor;
  border-radius: 50%;
}

.file-status-filter.is-indexed,
.file-status--success {
  color: var(--ui-success);
}

.file-status-filter.is-indexing,
.file-status--info {
  color: var(--ui-primary);
}

.file-status-filter.is-pending,
.file-status--muted {
  color: var(--ui-muted);
}

.file-status-filter.is-error,
.file-status--danger {
  color: var(--ui-danger);
}

.file-status-filter__count {
  font-variant-numeric: tabular-nums;
}

.file-search {
  width: min(260px, 100%);
  height: 34px;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 9px;
  color: var(--ui-muted);
  background: var(--ui-surface);
  border: 1px solid var(--ui-border);
  border-radius: 8px;
}

.file-search input {
  width: 100%;
  min-width: 0;
  color: var(--ui-text);
  background: transparent;
  border: 0;
  outline: 0;
  font: inherit;
  font-size: 10px;
}

.file-list {
  display: grid;
}

.file-row {
  min-width: 0;
  display: grid;
  grid-template-columns: 25px minmax(0, 1fr) 100px 75px 92px;
  align-items: center;
  gap: 9px;
  min-height: 52px;
  padding: 7px 4px;
  border-bottom: 1px solid var(--ui-border);
}

.file-row__icon {
  color: var(--ui-primary);
}

.file-row__name {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.file-row__name strong,
.file-row__name small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-row__name strong {
  color: var(--ui-text);
  font-size: 10px;
  font-weight: var(--font-weight-semibold);
}

.file-row__name small,
.file-row__updated,
.file-row__size {
  color: var(--ui-muted);
  font-size: 8px;
}

.file-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 8px;
  white-space: nowrap;
}

.file-empty,
.file-notice,
.file-error {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 18px 6px;
  color: var(--ui-muted);
  font-size: 10px;
}

.file-notice,
.file-error {
  padding: 8px;
  color: var(--ui-warning);
  background: var(--color-warning-soft);
  border-radius: 7px;
}

.file-error {
  color: var(--ui-danger);
  background: var(--color-danger-soft);
}

.file-pagination,
.file-pagination__controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.file-pagination {
  margin-top: 10px;
  color: var(--ui-muted);
  font-size: 9px;
}

.file-pagination__controls > span {
  white-space: nowrap;
}

@media (max-width: 760px) {
  .files-panel__heading,
  .files-controls {
    align-items: stretch;
    flex-direction: column;
  }

  .recent-sync-card {
    width: 100%;
    min-width: 0;
  }

  .file-search {
    width: 100%;
  }

  .file-row {
    grid-template-columns: 22px minmax(0, 1fr) 76px;
  }

  .file-row__updated,
  .file-row__size {
    display: none;
  }
}

@media (max-width: 480px) {
  .files-panel {
    padding: 12px;
  }

  .file-status-filters {
    gap: 2px;
  }

  .file-status-filter {
    padding: 0 5px;
    font-size: 8px;
  }

  .file-pagination,
  .file-pagination__controls {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
