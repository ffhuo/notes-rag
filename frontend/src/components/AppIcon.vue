<script setup>
// 图标渲染器（规范 §4.3）。所有图标固定 viewBox 0 0 24 24、线性描边、尺寸档位 16/20/24。
// 颜色一律 currentColor —— 由使用方通过 color 继承控制，组件内不出现具体色值。
import { computed } from 'vue'
import { iconShapes } from '../icons'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
  /** 描边粗细：16px 小图标可传 2 以保持视觉重量。 */
  strokeWidth: { type: [Number, String], default: 1.8 },
  /** 实心填充（如 ★ 默认项标记）。 */
  filled: { type: Boolean, default: false },
})

const shapes = computed(() => iconShapes(props.name))
</script>

<template>
  <svg
    class="app-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    :fill="filled ? 'currentColor' : 'none'"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <template v-for="(s, i) in shapes" :key="i">
      <circle v-if="s.c" :cx="s.c[0]" :cy="s.c[1]" :r="s.c[2]" />
      <rect v-else-if="s.r" :x="s.r[0]" :y="s.r[1]" :width="s.r[2]" :height="s.r[3]" :rx="s.r[4]" />
      <path v-else :d="s.p" />
    </template>
  </svg>
</template>

<style scoped>
.app-icon {
  display: block;
  flex: none;
}
</style>
