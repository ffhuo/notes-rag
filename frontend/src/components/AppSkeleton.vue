<script setup>
// 骨架屏（T2.7 / 规范 §4.2）—— 「禁止用整页 spinner 替代骨架」。
// 用透明度脉动而非位移动画：不引起布局抖动，且 reduced-motion 下自动降级（base.css）。
const props = defineProps({
  variant: { type: String, default: 'text' }, // text | card | list
  rows: { type: Number, default: 3 },
  /** list 形态的行数。 */
  count: { type: Number, default: 3 },
})
</script>

<template>
  <div class="app-skeleton" :class="`is-${variant}`" aria-hidden="true">
    <template v-if="variant === 'text'">
      <span
        v-for="i in rows"
        :key="i"
        class="app-skeleton__line"
        :class="{ 'is-short': i === rows }"
      ></span>
    </template>

    <template v-else-if="variant === 'card'">
      <span class="app-skeleton__line is-title"></span>
      <span class="app-skeleton__line"></span>
      <span class="app-skeleton__line is-short"></span>
    </template>

    <template v-else>
      <span v-for="i in count" :key="i" class="app-skeleton__row">
        <span class="app-skeleton__dot"></span>
        <span class="app-skeleton__row-lines">
          <span class="app-skeleton__line is-title"></span>
          <span class="app-skeleton__line is-short"></span>
        </span>
      </span>
    </template>
  </div>
</template>

<style scoped>
.app-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 100%;
}

.app-skeleton__line {
  display: block;
  height: 12px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-subtle);
  animation: app-skeleton-pulse 1.4s var(--ease-standard) infinite;
}
.app-skeleton__line.is-title {
  height: 16px;
}
.app-skeleton__line.is-short {
  width: 60%;
}

.app-skeleton__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.app-skeleton__dot {
  flex: none;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  background: var(--color-bg-subtle);
  animation: app-skeleton-pulse 1.4s var(--ease-standard) infinite;
}

.app-skeleton__row-lines {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

@keyframes app-skeleton-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .45; }
}
</style>
