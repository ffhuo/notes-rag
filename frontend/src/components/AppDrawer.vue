<script setup>
// 抽屉（T2.8）—— 详情查看用；右侧 480px（规范 §4.2）。
import AppOverlay from './AppOverlay.vue'

defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: [Number, String], default: 480 },
  persistent: { type: Boolean, default: false },
  closeOnMask: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'close'])
</script>

<template>
  <AppOverlay
    :model-value="modelValue"
    variant="drawer"
    :title="title"
    :width="width"
    :persistent="persistent"
    :close-on-mask="closeOnMask"
    @update:model-value="emit('update:modelValue', $event)"
    @close="emit('close')"
  >
    <slot />
    <template v-if="$slots.footer" #footer><slot name="footer" /></template>
  </AppOverlay>
</template>
