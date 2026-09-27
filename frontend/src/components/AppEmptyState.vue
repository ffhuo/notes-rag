<script setup>
// 空态（T2.6 / 规范 §4.2）：结构固定为「图标 48px + 标题 + 说明 + 主操作」。
// 空态必须给出下一步指引，不能只留一片空白。
import AppButton from './AppButton.vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  icon: { type: String, default: 'inbox' },
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
  /** 无 actions 插槽时，用这个文案渲染一个 primary 主操作按钮。 */
  actionText: { type: String, default: '' },
  actionIcon: { type: String, default: '' },
  size: { type: String, default: 'md' }, // md | sm
})

const emit = defineEmits(['action'])
</script>

<template>
  <div class="app-empty" :class="`is-${size}`">
    <span class="app-empty__icon"><AppIcon :name="icon" :size="size === 'sm' ? 32 : 48" :stroke-width="1.5" /></span>
    <p class="app-empty__title">{{ title }}</p>
    <p v-if="description" class="app-empty__desc">{{ description }}</p>

    <div v-if="$slots.actions || actionText" class="app-empty__actions">
      <slot name="actions">
        <AppButton variant="primary" :icon="actionIcon" @click="emit('action')">{{ actionText }}</AppButton>
      </slot>
    </div>
  </div>
</template>

<style scoped>
.app-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-10) var(--space-6);
  text-align: center;
}
.app-empty.is-sm {
  padding: var(--space-6) var(--space-4);
}

.app-empty__icon {
  color: var(--color-text-muted);
  opacity: .8;
}

.app-empty__title {
  color: var(--color-text-primary);
  font-size: var(--font-size-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--font-weight-semibold);
}

.app-empty__desc {
  max-width: 420px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

.app-empty__actions {
  margin-top: var(--space-3);
}
</style>
