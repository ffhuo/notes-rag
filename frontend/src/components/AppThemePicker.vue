<script setup>
// 主题设置入口（T1.6 / 规范 §3.3、§2.8）—— 侧栏底部，品牌色 + 明暗两个正交维度。
//
// 只暴露预置主题包，不开放任意色值输入（规范 §2.8「边界」：派生色无法在小程序/RN
// 运行时生成，且任意色值无法保证对比度门禁）。
import { computed, ref } from 'vue'
import { BRANDS, getBrand, getScheme, resolveScheme, setBrand, setScheme } from '../theme'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
})

const brand = ref(getBrand())
const scheme = ref(getScheme()) // null = 跟随系统

const effectiveScheme = computed(() => scheme.value || resolveScheme())

const schemeOptions = [
  { id: null, label: '跟随系统', icon: 'monitor' },
  { id: 'light', label: '浅色', icon: 'sun' },
  { id: 'dark', label: '深色', icon: 'moon' },
]

function pickBrand(id) {
  brand.value = id
  setBrand(id)
}

function pickScheme(id) {
  scheme.value = id
  setScheme(id)
}

/** 折叠态：单击循环切换品牌色（5 个主题，逐个轮换）。 */
function cycleBrand() {
  const i = BRANDS.findIndex((b) => b.id === brand.value)
  pickBrand(BRANDS[(i + 1) % BRANDS.length].id)
}

function toggleScheme() {
  pickScheme(resolveScheme() === 'dark' ? 'light' : 'dark')
}
</script>

<template>
  <div class="theme-picker" :class="{ 'is-collapsed': collapsed }">
    <!-- 展开态：色板 + 明暗分段 -->
    <template v-if="!collapsed">
      <div class="theme-picker__row">
        <span class="theme-picker__label">主题色</span>
        <div class="theme-picker__swatches">
          <!--
            色点用 brand-* 类在本元素上就地覆盖 --brand-primary，
            再取 var(--brand-primary) —— 因此不需要在组件里硬编码任何十六进制色值。
          -->
          <button
            v-for="b in BRANDS"
            :key="b.id"
            type="button"
            class="theme-picker__swatch"
            :class="[`brand-${b.id}`, { 'is-active': b.id === brand }]"
            :title="b.label"
            :aria-label="`主题色：${b.label}`"
            :aria-pressed="b.id === brand"
            @click="pickBrand(b.id)"
          >
            <span class="theme-picker__dot"></span>
          </button>
        </div>
      </div>

      <div class="theme-picker__row">
        <span class="theme-picker__label">明暗</span>
        <div class="theme-picker__seg">
          <button
            v-for="s in schemeOptions"
            :key="String(s.id)"
            type="button"
            class="theme-picker__seg-btn"
            :class="{ 'is-active': scheme === s.id }"
            :title="s.label"
            :aria-label="`明暗：${s.label}`"
            :aria-pressed="scheme === s.id"
            @click="pickScheme(s.id)"
          >
            <AppIcon :name="s.icon" :size="16" />
          </button>
        </div>
      </div>
    </template>

    <!-- 折叠态：收为两个图标按钮 -->
    <template v-else>
      <button
        type="button"
        class="theme-picker__icon-btn"
        :title="`主题色：${brand}（点击轮换）`"
        :aria-label="'轮换主题色'"
        @click="cycleBrand"
      >
        <AppIcon name="droplet" :size="20" />
      </button>
      <button
        type="button"
        class="theme-picker__icon-btn"
        :title="`明暗：${effectiveScheme === 'dark' ? '深色' : '浅色'}（点击切换）`"
        :aria-label="'切换明暗模式'"
        @click="toggleScheme"
      >
        <AppIcon :name="effectiveScheme === 'dark' ? 'moon' : 'sun'" :size="20" />
      </button>
    </template>
  </div>
</template>

<style scoped>
.theme-picker {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border-top: var(--border-width) solid var(--color-border);
}

.theme-picker__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.theme-picker__label {
  flex: none;
  width: 48px;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.theme-picker__swatches {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.theme-picker__swatch {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-full);
  background: transparent;
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-standard);
}
.theme-picker__swatch:hover {
  border-color: var(--color-border-strong);
}
.theme-picker__swatch.is-active {
  border-color: var(--color-text-primary);
}

.theme-picker__dot {
  width: 16px;
  height: 16px;
  border-radius: var(--radius-full);
  background: var(--brand-primary);
}

.theme-picker__seg {
  display: flex;
  align-items: center;
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.theme-picker__seg-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 28px;
  padding: 0;
  border: none;
  background: var(--color-bg-surface);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard),
              color var(--duration-fast) var(--ease-standard);
}
.theme-picker__seg-btn:hover {
  background: var(--color-bg-subtle);
}
.theme-picker__seg-btn.is-active {
  background: var(--color-primary-soft);
  color: var(--color-primary-on-soft);
}

/* 折叠态 */
.theme-picker.is-collapsed {
  flex-direction: row;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-2);
}

.theme-picker__icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard),
              color var(--duration-fast) var(--ease-standard);
}
.theme-picker__icon-btn:hover {
  background: var(--color-bg-subtle);
  border-color: var(--color-border);
  color: var(--color-primary);
}
</style>
