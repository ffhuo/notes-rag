<script setup>
// 按钮（T2.1 / 规范 §4.2）。
//
// 关键约束：primary 变体的文字必须用 --color-accent-on（深色，随主题包提供），
// 不得用白色 —— 琥珀底配白字仅约 2.2:1，不达 WCAG AA。
// 加载态保留原宽（图标位换成旋转指示器、文案不变），避免按钮宽度跳动。
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  variant: { type: String, default: 'secondary' }, // primary | secondary | ghost | danger
  size: { type: String, default: 'md' }, // sm | md | lg
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
  icon: { type: String, default: '' },
  iconRight: { type: String, default: '' },
  title: { type: String, default: '' },
  type: { type: String, default: 'button' },
})

const emit = defineEmits(['click'])

const inert = computed(() => props.disabled || props.loading)
const iconSize = computed(() => (props.size === 'lg' ? 20 : 16))

function onClick(event) {
  if (inert.value) return
  emit('click', event)
}
</script>

<template>
  <button
    class="app-btn"
    :class="[`is-${variant}`, `is-${size}`, { 'is-block': block, 'is-loading': loading }]"
    :type="type"
    :disabled="inert"
    :title="title"
    @click="onClick"
  >
    <AppIcon v-if="loading" class="app-btn__spinner" name="loader" :size="iconSize" />
    <AppIcon v-else-if="icon" :name="icon" :size="iconSize" />
    <span class="app-btn__label"><slot /></span>
    <AppIcon v-if="iconRight && !loading" :name="iconRight" :size="iconSize" />
  </button>
</template>

<style scoped>
.app-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard),
              border-color var(--duration-fast) var(--ease-standard),
              color var(--duration-fast) var(--ease-standard);
}
.app-btn:disabled {
  cursor: default;
  opacity: .55;
}
.app-btn.is-block {
  display: flex;
  width: 100%;
}

/* ---------- 尺寸（plus 2px 边框 → 视觉高度 28/36/44） ---------- */
.is-sm {
  height: 28px;
  padding: 0 var(--space-3);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}
.is-md {
  height: 36px;
  padding: 0 var(--space-4);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}
.is-lg {
  height: 44px;
  padding: 0 var(--space-5);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

/* ---------- 变体 ---------- */
.is-primary {
  background: var(--color-accent);
  color: var(--color-accent-on);
}
.is-primary:hover:not(:disabled) {
  background: var(--color-accent-hover);
}

.is-secondary {
  background: var(--color-bg-surface);
  border-color: var(--color-border-strong);
  color: var(--color-text-primary);
}
.is-secondary:hover:not(:disabled) {
  background: var(--color-bg-subtle);
  border-color: var(--color-text-muted);
}

.is-ghost {
  background: transparent;
  color: var(--color-primary);
}
.is-ghost:hover:not(:disabled) {
  background: var(--color-primary-soft);
  color: var(--color-primary-on-soft);
}

.is-danger {
  background: var(--color-danger);
  color: var(--color-danger-contrast);
}
.is-danger:hover:not(:disabled) {
  background: var(--color-danger);
  opacity: .88;
}

.app-btn__label {
  display: inline-flex;
  align-items: center;
}

.app-btn__spinner {
  animation: app-btn-spin .8s linear infinite;
}
@keyframes app-btn-spin {
  to { transform: rotate(360deg); }
}

/* 移动端触控目标 ≥44px（规范 §3.4） */
@media (max-width: 767px) {
  .is-sm,
  .is-md {
    height: 44px;
  }
}
</style>
