<script setup>
// 进度条（T2.5 / 规范 §4.2）—— 四种形态由 jobs.js 判定，本组件不自行推导阶段语义：
//   badge          终态：收起进度条，改「状态徽章 + 计数摘要」
//   indeterminate  总量未知（scan 阶段 total 为 null）：滚动条纹 + 已处理数
//   determinate    已知总量：processed / total + 百分比
//   waiting        排队中且总量未定：空轨道 + 文案
// **绝不给不确定态硬编假分母**（M03 §5.4.2）。
//
// 两种用法：作业用 `run`（自动判定形态）；非作业场景用 value/max/indeterminate。
import { computed } from 'vue'
import { countsSummary, percent, progressShape, stageLabel } from '../jobs'
import { statusColor } from '../statusStyles'
import AppStatusBadge from './AppStatusBadge.vue'

const props = defineProps({
  /** SyncRunOut | SyncRunDetail | null。 */
  run: { type: Object, default: null },
  value: { type: [Number, null], default: null },
  max: { type: [Number, null], default: null },
  indeterminate: { type: Boolean, default: false },
  stage: { type: String, default: '' },
  status: { type: String, default: '' },
  compact: { type: Boolean, default: false },
  /** 不展示上方「阶段 + 状态 + 计数」行（仅要一根进度条时）。 */
  hideMeta: { type: Boolean, default: false },
  /** waiting 形态的提示文案。 */
  waitingText: { type: String, default: '等待开始…' },
})

const shape = computed(() => {
  if (props.run) return progressShape(props.run)
  if (props.indeterminate) return 'indeterminate'
  if (props.max && props.max > 0 && props.value !== null && props.value !== undefined) return 'determinate'
  return 'waiting'
})

const status = computed(() => props.run?.status || props.status || '')

const pct = computed(() => {
  if (props.run) return percent(props.run)
  if (!props.max || props.max <= 0) return 0
  return Math.min(100, Math.round(((props.value || 0) / props.max) * 100))
})

const fillColor = computed(() =>
  status.value ? statusColor(status.value) : 'var(--color-primary)',
)

const stageText = computed(() => stageLabel(props.run ? props.run.stage : props.stage))

const metaText = computed(() => {
  const r = props.run
  if (shape.value === 'badge') {
    if (!r) return ''
    const parts = [countsSummary(r)]
    if (r.failed_cnt) parts.push(`${r.failed_cnt} 个失败`)
    return parts.join(' · ')
  }
  if (shape.value === 'indeterminate') {
    // 只有 probe / scan 是「真不可知」：给具体动作名，别让用户看着「已处理 0 个」发懵
    const st = r ? r.stage : props.stage
    if (st === 'probe') return '正在检查源…'
    if (st === 'scan') return '正在统计文件数…'
    return `已处理 ${(r ? r.processed : props.value) || 0} 个`
  }
  if (shape.value === 'determinate') {
    const done = (r ? r.processed : props.value) || 0
    const total = r ? r.total : props.max
    return `${done} / ${total} · ${pct.value}%`
  }
  return props.waitingText
})

const fillStyle = computed(() => {
  if (shape.value === 'determinate') return { width: `${pct.value}%`, background: fillColor.value }
  if (shape.value === 'indeterminate') return { background: fillColor.value }
  return {}
})
</script>

<template>
  <div class="app-progress" :class="[`is-${shape}`, { 'is-compact': compact }]">
    <div v-if="!hideMeta" class="app-progress__head">
      <span class="app-progress__stage">{{ stageText }}</span>
      <AppStatusBadge v-if="run && shape === 'badge'" :status="run.status" size="sm" />
      <span v-if="metaText" class="app-progress__meta">{{ metaText }}</span>
    </div>

    <div v-if="shape !== 'badge'" class="app-progress__track" :class="`is-${shape}`">
      <i v-if="shape !== 'waiting'" class="app-progress__fill" :style="fillStyle"></i>
    </div>
  </div>
</template>

<style scoped>
.app-progress {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.app-progress__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  min-width: 0;
}

.app-progress__stage {
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  font-weight: var(--font-weight-semibold);
}

.app-progress__meta {
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  font-variant-numeric: tabular-nums;
}

.app-progress__track {
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-bg-subtle);
  overflow: hidden;
}
.app-progress.is-compact .app-progress__track {
  height: 4px;
}

.app-progress__fill {
  display: block;
  height: 100%;
  border-radius: var(--radius-full);
  transition: width var(--duration-base) var(--ease-standard);
}

/* 不确定态：滚动条纹，明确表达「在动但总量未知」 */
.app-progress__track.is-indeterminate .app-progress__fill {
  width: 30%;
  animation: app-progress-slide 1.2s linear infinite;
}

@keyframes app-progress-slide {
  from { transform: translateX(-110%); }
  to { transform: translateX(440%); }
}
</style>
