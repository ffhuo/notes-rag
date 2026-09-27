<script setup>
// AppShell（T1.1 骨架 + T1.3 折叠状态 + T1.4 移动端抽屉）
//
// 结构：侧栏（可折叠 / 移动端抽屉）+ 顶栏（汉堡 + 页面标题 + 页面级主操作）+ 内容区。
// 侧栏宽度与内容宽度的取值全部来自 L3 布局令牌（规范 §3.2）。
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppIcon from './components/AppIcon.vue'
import AppSidebar from './components/AppSidebar.vue'
import AppToast from './components/AppToast.vue'
import AuthGate from './components/AuthGate.vue'
import { initAuth, isReady, watchUnauthorized } from './auth'
import { useTopbarActions } from './shell'

const route = useRoute()
const topbarActions = useTopbarActions()
const pageTitle = computed(() => route.meta?.title || 'notes-rag')

/* ---------- 折叠状态：持久化 + md 断点默认折叠（规范 §3.2） ---------- */
const SIDEBAR_KEY = 'nr_sidebar_collapsed'
const MD_MAX_WIDTH = 1023 // ≤1023px 视为 md 及以下：侧栏默认收成 64px 图标条

function readStored() {
  try {
    return localStorage.getItem(SIDEBAR_KEY)
  } catch {
    return null
  }
}

const stored = readStored()
const hasPreference = ref(stored === '0' || stored === '1')
const collapsed = ref(
  hasPreference.value ? stored === '1' : typeof window !== 'undefined' && window.innerWidth <= MD_MAX_WIDTH,
)

const mobileOpen = ref(false)

function toggleCollapse() {
  collapsed.value = !collapsed.value
  hasPreference.value = true
  try {
    localStorage.setItem(SIDEBAR_KEY, collapsed.value ? '1' : '0')
  } catch {
    /* 存储不可用：仅本次会话生效 */
  }
}

/** 未手动设置过时，跟随断点：窄屏自动折叠，宽屏自动展开。 */
function onResize() {
  if (hasPreference.value) return
  collapsed.value = window.innerWidth <= MD_MAX_WIDTH
}

onMounted(() => {
  if (typeof window !== 'undefined' && window.addEventListener) window.addEventListener('resize', onResize)
  // 鉴权：先探测后端模式，再决定「直接进入 / 填 API Key / 登录注册」（见 src/auth.js）
  watchUnauthorized()
  initAuth()
})
onUnmounted(() => {
  if (typeof window !== 'undefined' && window.removeEventListener) window.removeEventListener('resize', onResize)
})

/* ---------- 移动端抽屉：路由切换后自动收起（规范 §3.3「选中后自动关闭」） ---------- */
watch(
  () => route.fullPath,
  () => {
    mobileOpen.value = false
  },
)
</script>

<template>
  <!-- 未拿到可用凭据时只渲染鉴权弹窗：主界面一旦挂载就会打满 401 请求 -->
  <AuthGate v-if="!isReady" />

  <div v-else class="app-shell">
    <!-- 抽屉态下强制展开：抽屉里再显示 64px 图标条没有意义 -->
    <AppSidebar
      :collapsed="collapsed && !mobileOpen"
      :mobile-open="mobileOpen"
      @toggle-collapse="toggleCollapse"
      @close-mobile="mobileOpen = false"
    />

    <div v-if="mobileOpen" class="app-shell__mask" @click="mobileOpen = false"></div>

    <div class="app-main">
      <header class="app-topbar">
        <button
          type="button"
          class="app-topbar__hamburger"
          aria-label="打开导航"
          @click="mobileOpen = true"
        >
          <AppIcon name="menu" :size="24" />
        </button>

        <h1 class="app-topbar__title">{{ pageTitle }}</h1>

        <div class="app-topbar__actions">
          <component
            v-for="a in topbarActions"
            :key="a.key"
            :is="a.comp"
            v-bind="a.props"
            v-on="a.on"
          >{{ a.text }}</component>
        </div>
      </header>

      <main class="app-content">
        <RouterView />
      </main>
    </div>
  </div>

  <!-- 全局提示宿主：全应用只挂一次（见 src/toast.js） -->
  <AppToast />
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100%;
}

.app-shell__mask {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 20;
  background: var(--color-overlay);
}

/* ---------- 主区 ---------- */
.app-main {
  flex: 1 1 auto;
  min-width: 0; /* 防止 flex 子项被内容撑破 */
  display: flex;
  flex-direction: column;
}

.app-topbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: var(--topbar-height);
  padding: 0 var(--space-6);
  background: var(--color-bg-surface);
  border-bottom: var(--border-width) solid var(--color-border);
}

/* 汉堡仅在 sm 断点出现（规范 §3.2） */
.app-topbar__hamburger {
  display: none;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 44px;
  height: 44px;
  margin-left: calc(var(--space-3) * -1);
  padding: 0;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-primary);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-standard);
}
.app-topbar__hamburger:hover {
  background: var(--color-bg-subtle);
}

.app-topbar__title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  font-size: var(--font-size-h1);
  line-height: var(--line-height-h1);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.app-topbar__actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.app-content {
  flex: 1 1 auto;
  width: 100%;
  max-width: var(--content-max-width);
  margin: 0 auto;
  padding: var(--space-6);
}

@media (max-width: 767px) {
  .app-topbar {
    padding: 0 var(--space-4);
  }
  .app-topbar__hamburger {
    display: flex;
  }
  .app-content {
    padding: var(--space-4);
  }
}
</style>
