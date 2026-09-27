<script setup>
// 下拉选择（T2.2 / 规范 §4.2）。用原生 <select>：跨端可表达，零依赖。
import { computed } from 'vue'
import AppField from './AppField.vue'
import AppIcon from './AppIcon.vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: [String, Number, null], default: '' },
  label: { type: String, default: '' },
  /** [{ value, label, disabled? }]；也可用默认插槽自定义 <option>。 */
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '' },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  required: { type: Boolean, default: false },
  id: { type: String, default: '' },
  /** 值为 null 时是否保留一个空选项（用于「不限 / 全部」筛选）。 */
  emptyLabel: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'change'])

let seq = 0
const autoId = `app-select-${(seq += 1)}`
const controlId = computed(() => props.id || autoId)

function onChange(event) {
  emit('update:modelValue', event.target.value)
  emit('change', event.target.value)
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
    <span class="app-select" :class="{ 'is-error': !!error, 'is-disabled': disabled }">
      <select
        :id="controlId"
        v-bind="$attrs"
        class="app-select__control"
        :value="modelValue"
        :disabled="disabled"
        :required="required"
        :aria-invalid="error ? 'true' : undefined"
        @change="onChange"
      >
        <option v-if="placeholder || emptyLabel" value="">{{ emptyLabel || placeholder }}</option>
        <option
          v-for="opt in options"
          :key="String(opt.value)"
          :value="opt.value"
          :disabled="opt.disabled"
        >
          {{ opt.label }}
        </option>
        <slot />
      </select>
      <span class="app-select__caret">
        <AppIcon name="chevron-down" :size="16" />
      </span>
    </span>
  </AppField>
</template>

<style scoped>
.app-select {
  position: relative;
  display: flex;
  align-items: center;
  height: 36px;
  border: var(--border-width) solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-bg-surface);
  transition: border-color var(--duration-fast) var(--ease-standard);
}
.app-select:hover {
  border-color: var(--color-text-muted);
}
.app-select:focus-within {
  border-color: var(--color-primary);
}
.app-select.is-error {
  border-color: var(--color-danger);
}
.app-select.is-disabled {
  background: var(--color-bg-subtle);
  opacity: .7;
}

.app-select__control {
  flex: 1 1 auto;
  min-width: 0;
  height: 100%;
  padding: 0 calc(var(--space-6) + var(--space-1)) 0 var(--space-3);
  border: none;
  background: transparent;
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  appearance: none;
  -webkit-appearance: none;
  cursor: pointer;
}
.app-select__control:focus {
  outline: none;
}

.app-select__caret {
  position: absolute;
  right: var(--space-2);
  display: flex;
  align-items: center;
  color: var(--color-text-muted);
  pointer-events: none;
}

@media (max-width: 767px) {
  .app-select {
    height: 44px;
  }
}
</style>
