<script setup>
// 表单字段外壳（AppInput / AppTextarea / AppSelect 共用）。
// 只负责 label / 说明 / 错误三行结构与间距，控件本身由默认插槽提供。
defineProps({
  label: { type: String, default: '' },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  required: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  /** 与控件的 id 对应，保证 label 与输入框关联（规范 §7「表单输入有关联 label」）。 */
  controlId: { type: String, default: '' },
})
</script>

<template>
  <div class="app-field" :class="{ 'is-error': !!error, 'is-disabled': disabled }">
    <label v-if="label" class="app-field__label" :for="controlId">
      {{ label }}<span v-if="required" class="app-field__req" aria-hidden="true">*</span>
    </label>
    <slot />
    <p v-if="error" class="app-field__msg is-error">{{ error }}</p>
    <p v-else-if="hint" class="app-field__msg">{{ hint }}</p>
  </div>
</template>

<style scoped>
.app-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.app-field__label {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  font-weight: var(--font-weight-semibold);
}

.app-field__req {
  margin-left: 2px;
  color: var(--color-danger);
}

.app-field__msg {
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}
.app-field__msg.is-error {
  color: var(--color-danger);
}
</style>
