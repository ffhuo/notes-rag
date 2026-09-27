<script setup>
// 弹层外壳（T2.8）—— AppModal / AppDrawer 共用同一份「遮罩 + Esc + 焦点陷阱」实现。
//
// 刻意不用 <Teleport>：小程序没有 DOM 传送能力（规范 §6.1），弹层直接渲染在原地 +
// position: fixed，各端语义一致。
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  variant: { type: String, default: 'modal' }, // modal | drawer
  title: { type: String, default: '' },
  width: { type: [Number, String], default: null },
  /** 进行中（如删除请求已发出）时禁止 Esc / 点遮罩关闭。 */
  persistent: { type: Boolean, default: false },
  closeOnMask: { type: Boolean, default: true },
  showClose: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'close'])

const panelRef = ref(null)
let lastFocused = null
let bound = false

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables() {
  if (!panelRef.value) return []
  return Array.from(panelRef.value.querySelectorAll(FOCUSABLE))
}

/** 焦点陷阱：Tab 在弹层内循环，不逃逸到背景页面（规范 §4.2）。 */
function onKeydown(event) {
  if (event.key === 'Escape' && !props.persistent) {
    event.stopPropagation()
    close()
    return
  }
  if (event.key !== 'Tab') return
  const list = focusables()
  if (!list.length) {
    event.preventDefault()
    return
  }
  const first = list[0]
  const last = list[list.length - 1]
  const active = document.activeElement
  const inside = panelRef.value && panelRef.value.contains(active)
  if (event.shiftKey && (active === first || !inside)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !inside)) {
    event.preventDefault()
    first.focus()
  }
}

function close() {
  emit('update:modelValue', false)
  emit('close')
}

function onMask() {
  if (props.persistent || !props.closeOnMask) return
  close()
}

function bind() {
  if (bound || typeof document === 'undefined') return
  document.addEventListener('keydown', onKeydown, true)
  bound = true
}

function unbind() {
  if (!bound || typeof document === 'undefined') return
  document.removeEventListener('keydown', onKeydown, true)
  bound = false
}

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      lastFocused = typeof document !== 'undefined' ? document.activeElement : null
      bind()
      await nextTick()
      const list = focusables()
      if (list.length) list[0].focus()
      else if (panelRef.value) panelRef.value.focus()
    } else {
      unbind()
      if (lastFocused && lastFocused.focus) lastFocused.focus()
    }
  },
)

onUnmounted(unbind)

const panelStyle = computed(() => {
  if (!props.width) return {}
  return { width: typeof props.width === 'number' ? `${props.width}px` : props.width }
})
</script>

<template>
  <div v-if="modelValue" class="app-overlay" :class="`is-${variant}`">
    <div class="app-overlay__mask" @click="onMask"></div>

    <div
      ref="panelRef"
      class="app-overlay__panel"
      :style="panelStyle"
      role="dialog"
      aria-modal="true"
      :aria-label="title || undefined"
      tabindex="-1"
    >
      <header v-if="title || showClose" class="app-overlay__header">
        <h2 class="app-overlay__title">{{ title }}</h2>
        <button
          v-if="showClose"
          type="button"
          class="app-overlay__close"
          aria-label="关闭"
          @click="close"
        >
          <AppIcon name="close" :size="20" />
        </button>
      </header>

      <div class="app-overlay__body"><slot /></div>

      <footer v-if="$slots.footer" class="app-overlay__footer"><slot name="footer" /></footer>
    </div>
  </div>
</template>

<style scoped>
.app-overlay {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 60;
  display: flex;
}

.app-overlay__mask {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  background: var(--color-overlay);
}

.app-overlay__panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--color-bg-surface);
  box-shadow: var(--shadow-lg);
  outline: none;
}

/* Modal：居中卡片（移动端满宽） */
.is-modal {
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
}
.is-modal .app-overlay__panel {
  width: 480px;
  max-width: 100%;
  max-height: 86%;
  border-radius: var(--radius-xl);
}

/* Drawer：右侧滑出，位置偏移用 transform 过渡（规范 §2.7） */
.is-drawer {
  justify-content: flex-end;
}
.is-drawer .app-overlay__panel {
  width: 480px;
  max-width: 100%;
  height: 100%;
  border-radius: 0;
  animation: app-drawer-in var(--duration-slow) var(--ease-standard);
}

@keyframes app-drawer-in {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.app-overlay__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: none;
  padding: var(--space-4);
  border-bottom: var(--border-width) solid var(--color-border);
}

.app-overlay__title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-primary);
  font-size: var(--font-size-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.app-overlay__close {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard),
              color var(--duration-fast) var(--ease-standard);
}
.app-overlay__close:hover {
  background: var(--color-bg-subtle);
  color: var(--color-text-primary);
}

.app-overlay__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
}

.app-overlay__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  flex: none;
  padding: var(--space-3) var(--space-4);
  border-top: var(--border-width) solid var(--color-border);
}

@media (max-width: 767px) {
  .is-modal {
    align-items: flex-end;
    padding: 0;
  }
  .is-modal .app-overlay__panel {
    width: 100%;
    max-height: 92%;
    border-radius: var(--radius-xl) var(--radius-xl) 0 0;
  }
  .is-drawer .app-overlay__panel {
    width: 100%;
  }
}
</style>
