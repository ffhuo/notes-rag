<script setup>
// 多行输入（T2.2 / 规范 §4.2）—— 问答页与模型配置的长文本用。
import { computed } from 'vue'
import AppField from './AppField.vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  required: { type: Boolean, default: false },
  rows: { type: Number, default: 3 },
  id: { type: String, default: '' },
  resize: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'blur', 'enter'])

let seq = 0
const autoId = `app-textarea-${(seq += 1)}`
const controlId = computed(() => props.id || autoId)

function onInput(event) {
  emit('update:modelValue', event.target.value)
}
</script>

<template>
  <AppField
    :label="label"
    :hint="hint"
    :error="error"
    :required="required"
    :disabled="disabled"
    :control-id="controlId"
  >
    <textarea
      :id="controlId"
      v-bind="$attrs"
      class="app-textarea"
      :class="{ 'is-error': !!error, 'is-disabled': disabled, 'is-fixed': !resize }"
      :value="modelValue"
      :rows="rows"
      :placeholder="placeholder"
      :disabled="disabled"
      :required="required"
      :aria-invalid="error ? 'true' : undefined"
      @input="onInput"
      @blur="emit('blur', $event)"
      @keyup.enter="emit('enter', $event)"
    ></textarea>
  </AppField>
</template>

<style scoped>
.app-textarea {
  display: block;
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: var(--border-width) solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  transition: border-color var(--duration-fast) var(--ease-standard);
}
.app-textarea:hover {
  border-color: var(--color-text-muted);
}
.app-textarea:focus {
  border-color: var(--color-primary);
  outline: none;
}
.app-textarea.is-error {
  border-color: var(--color-danger);
}
.app-textarea.is-disabled {
  background: var(--color-bg-subtle);
  opacity: .7;
}
.app-textarea.is-fixed {
  resize: none;
}
.app-textarea::placeholder {
  color: var(--color-text-muted);
}
</style>
