<script setup>
// 单行输入（T2.2 / 规范 §4.2）。六态中 hover/active 由控件自身伪类表达，
// focus 交给全局 :focus-visible。
import { computed } from 'vue'
import AppField from './AppField.vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  label: { type: String, default: '' },
  type: { type: String, default: 'text' },
  placeholder: { type: String, default: '' },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  required: { type: Boolean, default: false },
  id: { type: String, default: '' },
  /** 标识符 / 数值类输入用等宽字体（run_id、路径、score）。 */
  mono: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'blur', 'enter', 'focus'])

let seq = 0
const autoId = `app-input-${(seq += 1)}`
const controlId = computed(() => props.id || autoId)

function onInput(event) {
  emit('update:modelValue', event.target.value)
}
function onEnter(event) {
  emit('enter', event.target.value)
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
    <span class="app-input" :class="{ 'is-error': !!error, 'is-disabled': disabled, 'is-mono': mono }">
      <span v-if="$slots.prefix" class="app-input__affix"><slot name="prefix" /></span>
      <input
        :id="controlId"
        v-bind="$attrs"
        class="app-input__control"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :required="required"
        :aria-invalid="error ? 'true' : undefined"
        @input="onInput"
        @blur="emit('blur', $event)"
        @focus="emit('focus', $event)"
        @keyup.enter="onEnter"
      />
      <span v-if="$slots.suffix" class="app-input__affix"><slot name="suffix" /></span>
    </span>
  </AppField>
</template>

<style scoped>
.app-input {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  height: 36px;
  padding: 0 var(--space-3);
  border: var(--border-width) solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-bg-surface);
  transition: border-color var(--duration-fast) var(--ease-standard),
              background-color var(--duration-fast) var(--ease-standard);
}
.app-input:hover {
  border-color: var(--color-text-muted);
}
.app-input:focus-within {
  border-color: var(--color-primary);
}

.app-input.is-error {
  border-color: var(--color-danger);
}
.app-input.is-disabled {
  background: var(--color-bg-subtle);
  opacity: .7;
}

.app-input__control {
  flex: 1 1 auto;
  min-width: 0;
  height: 100%;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}
.app-input__control::placeholder {
  color: var(--color-text-muted);
}
.app-input__control:focus {
  outline: none;
}
.app-input.is-mono .app-input__control {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-code);
}
/* 控件自身已由外层 :focus-within 表达焦点，去掉内层重复的轮廓 */
.app-input__control:focus-visible {
  outline: none;
}

.app-input__affix {
  flex: none;
  display: flex;
  align-items: center;
  color: var(--color-text-muted);
}

/* 移动端触控目标 ≥44px（规范 §3.4） */
@media (max-width: 767px) {
  .app-input {
    height: 44px;
  }
}
</style>
