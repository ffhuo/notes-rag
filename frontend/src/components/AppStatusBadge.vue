<script setup>
// 状态徽章（T2.4，公共件）—— 规范 §4.2「StatusBadge」+ §2.3「作业状态色」。
//
// 硬性要求：颜色 + 文本双重编码，禁止只靠颜色表达状态（色盲可用性）。
// 颜色映射不写在本组件里，统一取自 statusStyles.js —— 保证 T2.5 / T3.x 不会写出第二套。
import { computed } from 'vue'
import { statusInfo } from '../jobs'
import { statusColor } from '../statusStyles'

const props = defineProps({
  /** 后端 sync_runs.status（七态）；未知值回退为「原文 + muted」。 */
  status: { type: String, default: '' },
  /** 覆盖文案（如展示阶段名）；默认取 jobs.js 的状态中文名。 */
  label: { type: String, default: '' },
  /** sm=紧凑（表格内）／md=默认。 */
  size: { type: String, default: 'md' },
  /** 仅圆点（空间极窄处，如折叠侧栏）；文本仍保留给读屏。 */
  dotOnly: { type: Boolean, default: false },
})

const info = computed(() => statusInfo(props.status))
const text = computed(() => props.label || info.value.label)
const color = computed(() => statusColor(props.status))
</script>

<template>
  <span class="app-status-badge" :class="[`is-${size}`, { 'is-dot-only': dotOnly }]">
    <span class="app-status-badge__dot" :style="{ background: color }"></span>
    <span v-if="!dotOnly" class="app-status-badge__text">{{ text }}</span>
    <span v-else class="sr-only">{{ text }}</span>
  </span>
</template>

<style scoped>
.app-status-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
}

.app-status-badge__dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
}

.app-status-badge__text {
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  white-space: nowrap;
}

.is-sm .app-status-badge__text {
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.is-dot-only .app-status-badge__dot {
  width: 10px;
  height: 10px;
}
</style>
