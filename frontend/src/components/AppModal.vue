<script setup>
// 对话框（T2.8）—— 确认与表单用；宽度 480px，移动端满宽（规范 §4.2）。
// 结构与行为全部来自 AppOverlay，本身只固定 variant。
import AppOverlay from './AppOverlay.vue'

defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: [Number, String], default: 480 },
  persistent: { type: Boolean, default: false },
  closeOnMask: { type: Boolean, default: true },
  showClose: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'close'])
</script>

<template>
  <AppOverlay
    :model-value="modelValue"
    variant="modal"
    :title="title"
    :width="width"
    :persistent="persistent"
    :close-on-mask="closeOnMask"
    :show-close="showClose"
    @update:model-value="emit('update:modelValue', $event)"
    @close="emit('close')"
  >
    <slot />
    <template v-if="$slots.footer" #footer><slot name="footer" /></template>
  </AppOverlay>
</template>
