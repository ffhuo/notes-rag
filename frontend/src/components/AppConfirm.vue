<script setup>
// 危险操作二次确认（T2.8）—— 规范 §4.2：
// 「危险确认使用 danger 按钮 + 明确动作文案，禁止『确定 / 取消』这类无信息量文案」。
// 因此 confirmText 由调用方给出具体动作（如「确认删除 vault」），默认值仅是兜底。
import AppButton from './AppButton.vue'
import AppModal from './AppModal.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '确认操作' },
  message: { type: String, default: '' },
  confirmText: { type: String, default: '确认' },
  cancelText: { type: String, default: '取消' },
  danger: { type: Boolean, default: false },
  /** 请求进行中：按钮转 loading 且禁止 Esc / 点遮罩关闭。 */
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

function onConfirm() {
  emit('confirm')
}

function onCancel() {
  emit('update:modelValue', false)
  emit('cancel')
}
</script>

<template>
  <AppModal
    :model-value="modelValue"
    :title="title"
    :persistent="loading"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <p class="app-confirm__message">{{ message }}</p>
    <slot />

    <template #footer>
      <AppButton variant="secondary" :disabled="loading" @click="onCancel">{{ cancelText }}</AppButton>
      <AppButton
        :variant="danger ? 'danger' : 'primary'"
        :loading="loading"
        @click="onConfirm"
      >
        {{ confirmText }}
      </AppButton>
    </template>
  </AppModal>
</template>

<style scoped>
.app-confirm__message {
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}
</style>
