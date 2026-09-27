<script setup>
// 侧栏作业状态区（T1.5）—— 规范 §3.3「侧栏底部常驻作业状态：正在执行的作业数量 +
// 最近一次结果，点击跳 /tasks」。
//
// 数据来自 useRunsPolling()（与任务页同一份、同一次轮询，见 docs/ui-tasks.md §4.3）。
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useRunsPolling } from '../composables/useRunsPolling'
import { countsSummary, percent, progressShape, relativeTime, stageLabel } from '../jobs'
import AppIcon from './AppIcon.vue'
import AppStatusBadge from './AppStatusBadge.vue'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
})

const router = useRouter()
const { runs, loading, runningCount, activeRuns } = useRunsPolling()

const active = computed(() => activeRuns.value[0] || null)
const latest = computed(() => runs.value[0] || null)

/** 运行中作业的一行摘要：进度形态由 jobs.js 判定，绝不硬编假分母。 */
const activeMeta = computed(() => {
  const r = active.value
  if (!r) return ''
  const shape = progressShape(r)
  if (shape === 'indeterminate') return `已处理 ${r.processed || 0} 个`
  if (shape === 'determinate') return `${r.processed || 0} / ${r.total} · ${percent(r)}%`
  return stageLabel(r.stage) || countsSummary(r)
})

const tip = computed(() => {
  if (active.value) return `${runningCount.value} 个作业进行中，点击查看任务与进度`
  return '查看任务与进度'
})

function go() {
  router.push('/tasks')
}
</script>

<template>
  <div class="job-status" :class="{ 'is-collapsed': collapsed }">
    <button class="job-status__btn" type="button" :title="tip" @click="go">
      <span class="job-status__icon">
        <AppIcon name="tasks" :size="20" />
        <span v-if="runningCount > 0" class="job-status__count">{{ runningCount }}</span>
      </span>

      <span class="job-status__body">
        <span class="job-status__title">作业状态</span>

        <template v-if="active">
          <span class="job-status__line">
            <AppStatusBadge :status="active.status" size="sm" />
            <span class="job-status__vault">{{ active.vault_name }}</span>
          </span>
          <span class="job-status__meta">{{ activeMeta }}</span>
        </template>

        <template v-else-if="loading && !runs.length">
          <span class="job-status__meta">读取中…</span>
        </template>

        <template v-else-if="latest">
          <span class="job-status__line">
            <AppStatusBadge :status="latest.status" size="sm" />
            <span class="job-status__vault">{{ latest.vault_name }}</span>
          </span>
          <span class="job-status__meta">{{ relativeTime(latest.finished_at ?? latest.started_at) }}</span>
        </template>

        <span v-else class="job-status__meta">暂无作业记录</span>
      </span>
    </button>
  </div>
</template>

<style scoped>
.job-status {
  min-width: 0;
}

.job-status__btn {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  text-align: left;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard),
              border-color var(--duration-fast) var(--ease-standard);
}
.job-status__btn:hover {
  background: var(--color-bg-subtle);
  border-color: var(--color-border);
}

.job-status__icon {
  position: relative;
  flex: none;
  color: var(--color-text-secondary);
}

/* 运行中计数：数字角标（颜色 + 数字双重编码，不单靠色） */
.job-status__count {
  position: absolute;
  top: -6px;
  right: -8px;
  min-width: 16px;
  padding: 0 4px;
  border-radius: var(--radius-full);
  background: var(--color-accent);
  color: var(--color-accent-on);
  font-size: var(--font-size-caption);
  line-height: 16px;
  font-weight: var(--font-weight-semibold);
  text-align: center;
}

.job-status__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.job-status__title {
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  font-weight: var(--font-weight-semibold);
}

.job-status__line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.job-status__vault {
  overflow: hidden;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.job-status__meta {
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  font-variant-numeric: tabular-nums;
}

/* 折叠态：只留图标 + 计数 */
.is-collapsed .job-status__btn {
  justify-content: center;
  padding: var(--space-2);
}
.is-collapsed .job-status__body {
  display: none;
}
</style>
