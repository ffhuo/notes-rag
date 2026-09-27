<script setup>
// 卡片（T2.3 / 规范 §4.1）。骨架态用 AppSkeleton，避免每处自定义占位。
import { computed } from 'vue'
import AppSkeleton from './AppSkeleton.vue'

const props = defineProps({
  /** hover / active 反馈 + 键盘可激活（用于「点整卡进详情」的场景）。 */
  interactive: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  /** sm=紧凑内边距（卡片网格）／md=默认。 */
  padding: { type: String, default: 'md' },
  tag: { type: String, default: 'div' },
})

const emit = defineEmits(['click'])

const role = computed(() => (props.interactive ? 'button' : undefined))

function onClick(event) {
  if (!props.interactive) return
  emit('click', event)
}

function onKeydown(event) {
  if (!props.interactive) return
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('click', event)
  }
}
</script>

<template>
  <component
    :is="tag"
    class="app-card"
    :class="[`is-pad-${padding}`, { 'is-interactive': interactive }]"
    :role="role"
    :tabindex="interactive ? 0 : undefined"
    @click="onClick"
    @keydown="onKeydown"
  >
    <div v-if="loading" class="app-card__body">
      <AppSkeleton variant="card" />
    </div>

    <template v-else>
      <div v-if="$slots.header" class="app-card__header"><slot name="header" /></div>
      <div class="app-card__body"><slot /></div>
      <div v-if="$slots.footer" class="app-card__footer"><slot name="footer" /></div>
    </template>
  </component>
</template>

<style scoped>
.app-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-surface);
  box-shadow: var(--shadow-xs);
  transition: border-color var(--duration-fast) var(--ease-standard),
              box-shadow var(--duration-fast) var(--ease-standard);
}

.app-card.is-interactive {
  cursor: pointer;
}
.app-card.is-interactive:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-sm);
}

.app-card__header,
.app-card__footer {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.app-card__header {
  justify-content: space-between;
  border-bottom: var(--border-width) solid var(--color-border);
}
.app-card__footer {
  justify-content: flex-end;
  border-top: var(--border-width) solid var(--color-border);
}

.app-card__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.is-pad-sm .app-card__header,
.is-pad-sm .app-card__footer { padding: var(--space-2) var(--space-3); }
.is-pad-sm .app-card__body { padding: var(--space-3); }

.is-pad-md .app-card__header,
.is-pad-md .app-card__footer { padding: var(--space-3) var(--space-4); }
.is-pad-md .app-card__body { padding: var(--space-4); }
</style>
