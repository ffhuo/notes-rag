<script setup>
// 全局提示宿主（T2.9）—— 由 AppShell 顶层挂载一次，消费 src/toast.js 的队列。
import { dismissToast, toasts } from '../toast'
import { toneColor } from '../statusStyles'
import AppIcon from './AppIcon.vue'

const TONE_ICON = {
  info: 'info',
  success: 'check',
  warn: 'alert',
  danger: 'alert',
}
</script>

<template>
  <div class="app-toast-host">
    <div
      v-for="t in toasts"
      :key="t.id"
      class="app-toast"
      :class="`is-${t.tone}`"
      role="status"
      aria-live="polite"
    >
      <span class="app-toast__icon" :style="{ color: toneColor(t.tone) }">
        <AppIcon :name="TONE_ICON[t.tone] || 'info'" :size="20" />
      </span>
      <span class="app-toast__message">{{ t.message }}</span>
      <button
        v-if="!t.duration"
        type="button"
        class="app-toast__close"
        aria-label="关闭提示"
        @click="dismissToast(t.id)"
      >
        <AppIcon name="close" :size="16" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.app-toast-host {
  position: fixed;
  top: var(--space-4);
  right: var(--space-4);
  z-index: 80;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 360px;
  pointer-events: none; /* 宿主不吃点击，只有提示条本身可交互 */
}

.app-toast {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-surface);
  box-shadow: var(--shadow-md);
  pointer-events: auto;
  animation: app-toast-in var(--duration-base) var(--ease-standard);
}

@keyframes app-toast-in {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: translateY(0); }
}

.app-toast__icon {
  flex: none;
  margin-top: 1px;
}

.app-toast__message {
  flex: 1 1 auto;
  min-width: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  word-break: break-word;
}

.app-toast__close {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}
.app-toast__close:hover {
  background: var(--color-bg-subtle);
  color: var(--color-text-primary);
}

@media (max-width: 767px) {
  .app-toast-host {
    top: var(--space-3);
    right: var(--space-3);
    left: var(--space-3);
    max-width: none;
  }
}
</style>
