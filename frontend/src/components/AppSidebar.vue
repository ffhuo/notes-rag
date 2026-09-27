<script setup>
// 侧栏导航（T1.2 导航 + active 态 / T1.3 折叠 / T1.4 移动端抽屉）
//
// 文案单一来源：label 取自对应路由的 meta.title（见 router.js 的 NAV_ITEMS），
// 不在本组件重写一遍「知识库 / 任务与进度…」。
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { NAV_ITEMS } from '../router'
import AppIcon from './AppIcon.vue'
import AppJobStatus from './AppJobStatus.vue'
import AppThemePicker from './AppThemePicker.vue'

const props = defineProps({
  /** 折叠为 64px 图标条（sm 断点下的抽屉态由父级强制传 false）。 */
  collapsed: { type: Boolean, default: false },
  /** 移动端抽屉是否展开。 */
  mobileOpen: { type: Boolean, default: false },
})

const emit = defineEmits(['toggle-collapse', 'close-mobile'])

const route = useRoute()
const items = computed(() => NAV_ITEMS.map((n) => ({ ...n, active: route.name === n.name })))
</script>

<template>
  <aside
    class="app-sidebar"
    :class="{ 'is-collapsed': collapsed, 'is-open': mobileOpen }"
  >
    <div class="app-sidebar__head">
      <RouterLink class="app-sidebar__brand" to="/vaults" @click="emit('close-mobile')">
        <span class="app-sidebar__logo">n</span>
        <span class="app-sidebar__brand-text">notes-rag</span>
      </RouterLink>

      <button
        type="button"
        class="app-sidebar__collapse"
        :title="collapsed ? '展开侧栏' : '折叠侧栏'"
        :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'"
        :aria-expanded="!collapsed"
        @click="emit('toggle-collapse')"
      >
        <AppIcon :name="collapsed ? 'chevron-right' : 'chevron-left'" :size="16" />
      </button>
    </div>

    <nav class="app-sidebar__nav">
      <RouterLink
        v-for="item in items"
        :key="item.name"
        class="app-nav-item"
        :class="{ 'is-active': item.active }"
        :to="item.to"
        :title="collapsed ? item.label : ''"
        :aria-current="item.active ? 'page' : undefined"
        @click="emit('close-mobile')"
      >
        <span class="app-nav-item__indicator"></span>
        <AppIcon class="app-nav-item__icon" :name="item.icon" :size="20" />
        <span class="app-nav-item__label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="app-sidebar__foot">
      <AppJobStatus :collapsed="collapsed" />
      <AppThemePicker :collapsed="collapsed" />
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  flex: 0 0 var(--sidebar-width);
  width: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--color-bg-surface);
  border-right: var(--border-width) solid var(--color-border);
}

/* ---------- 品牌与折叠开关 ---------- */
.app-sidebar__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: none;
  height: var(--topbar-height);
  padding: 0 var(--space-3);
  border-bottom: var(--border-width) solid var(--color-border);
}

.app-sidebar__brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  color: var(--color-text-primary);
  text-decoration: none;
}
.app-sidebar__brand:hover {
  color: var(--color-text-primary);
  text-decoration: none;
}

.app-sidebar__logo {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 24px;
  height: 24px;
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: var(--color-primary-contrast);
  font-size: var(--font-size-sm);
  line-height: 1;
  font-weight: var(--font-weight-semibold);
}

.app-sidebar__brand-text {
  overflow: hidden;
  font-size: var(--font-size-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
  white-space: nowrap;
  transition: opacity var(--duration-base) var(--ease-standard),
              transform var(--duration-base) var(--ease-standard);
}

.app-sidebar__collapse {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 28px;
  height: 28px;
  margin-left: auto;
  padding: 0;
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard),
              color var(--duration-fast) var(--ease-standard);
}
.app-sidebar__collapse:hover {
  background: var(--color-bg-subtle);
  border-color: var(--color-border);
  color: var(--color-text-primary);
}

/* ---------- 导航 ---------- */
.app-sidebar__nav {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3) var(--space-3);
}

.app-nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3) var(--space-2) 0;
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  text-decoration: none;
  transition: background-color var(--duration-fast) var(--ease-standard),
              color var(--duration-fast) var(--ease-standard);
}
.app-nav-item:hover {
  background: var(--color-bg-subtle);
  color: var(--color-text-primary);
  text-decoration: none;
}

/* active 态必须显式（规范 §3.3）：3px 主色指示条 + 主色浅底 + 文字转主色 */
.app-nav-item.is-active {
  background: var(--color-primary-soft);
  color: var(--color-primary-on-soft);
  font-weight: var(--font-weight-semibold);
}

.app-nav-item__indicator {
  flex: none;
  width: 3px;
  height: 20px;
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  background: transparent;
}
.app-nav-item.is-active .app-nav-item__indicator {
  background: var(--color-primary);
}

.app-nav-item__icon {
  flex: none;
}

.app-nav-item__label {
  overflow: hidden;
  white-space: nowrap;
  transition: opacity var(--duration-base) var(--ease-standard),
              transform var(--duration-base) var(--ease-standard);
}

/* ---------- 底部：作业状态 + 主题入口 ---------- */
.app-sidebar__foot {
  flex: none;
  display: flex;
  flex-direction: column;
  padding: 0 var(--space-3) var(--space-3);
}

/* ---------- 折叠态（T1.3）：宽度瞬变，标签淡出（规范 §2.7 只过渡 opacity/transform） ---------- */
.app-sidebar.is-collapsed {
  flex-basis: var(--sidebar-width-collapsed);
  width: var(--sidebar-width-collapsed);
}

.is-collapsed .app-sidebar__brand-text,
.is-collapsed .app-sidebar__collapse {
  display: none;
}
.is-collapsed .app-sidebar__head {
  justify-content: center;
  padding: 0 var(--space-2);
}

.is-collapsed .app-nav-item {
  justify-content: center;
  gap: 0;
  padding: var(--space-2);
}
.is-collapsed .app-nav-item__indicator,
.is-collapsed .app-nav-item__label {
  display: none;
}
.is-collapsed .app-sidebar__foot {
  padding: 0 var(--space-2) var(--space-2);
}

/* ---------- 移动端抽屉（T1.4，sm 断点 0–767px） ----------
   用 transform 做 off-canvas；.is-collapsed 在此一并归零宽度，
   否则 (0,2,0) 的折叠规则会压过媒体查询里的 (0,1,0)。 */
@media (max-width: 767px) {
  .app-sidebar,
  .app-sidebar.is-collapsed {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 30;
    width: 280px;
    max-width: 84%;
    transform: translateX(-100%);
    transition: transform var(--duration-slow) var(--ease-standard);
    box-shadow: var(--shadow-lg);
  }
  .app-sidebar.is-open {
    transform: translateX(0);
  }
  /* 抽屉态由遮罩/汉堡关闭，折叠按钮无意义 */
  .app-sidebar__collapse {
    display: none;
  }
}
</style>
