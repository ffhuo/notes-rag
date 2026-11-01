<script setup>
// AppShell（T1.1 骨架 + T1.3 折叠状态 + T1.4 移动端抽屉）
//
// 结构：侧栏（可折叠 / 移动端抽屉）+ 顶栏（汉堡 + 页面标题 + 页面级主操作）+ 内容区。
// 侧栏宽度与内容宽度的取值全部来自 L3 布局令牌（规范 §3.2）。
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import AppIcon from './components/AppIcon.vue'
import AppSidebar from './components/AppSidebar.vue'
import AppToast from './components/AppToast.vue'
import AuthGate from './components/AuthGate.vue'
import { initAuth, isReady, watchUnauthorized } from './auth'
import { useTopbarActions } from './shell'

const route = useRoute()
const router = useRouter()
const topbarActions = useTopbarActions()
const pageTitle = computed(() => route.meta?.title || 'notes-rag')
const infoOpen = ref(false)
const workflow = [
  { id: 'vaults', label: '文件入库', path: '/vaults' },
  { id: 'tasks', label: '索引构建', path: '/tasks' },
  { id: 'search', label: '语义检索', path: '/search' },
  { id: 'chat', label: '问答与引用', path: '/chat' },
  { id: 'keys', label: '助手调用', path: '/keys' },
]
const workflowIndex = computed(() => workflow.findIndex((step) => step.id === route.name))
const shellStyle = computed(() => ({
  '--demo-sidebar-width': collapsed.value ? '64px' : '242px',
}))

function navigateWorkflow(path) {
  router.push(path)
}

/* ---------- 折叠状态：持久化 + md 断点默认折叠（规范 §3.2） ---------- */
const SIDEBAR_KEY = 'nr_sidebar_collapsed'
const MD_MAX_WIDTH = 1023 // ≤1023px 视为 md 及以下：侧栏默认收成 64px 图标条
const DRAWER_MAX_WIDTH = 767 // ≤767px 侧栏变成抽屉（与 AppSidebar 的媒体查询一致）

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
/** 是否处于抽屉断点（决定汉堡按钮是开抽屉还是展开侧栏）。 */
const isDrawer = ref(typeof window !== 'undefined' && window.innerWidth <= DRAWER_MAX_WIDTH)

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
  isDrawer.value = window.innerWidth <= DRAWER_MAX_WIDTH
  if (hasPreference.value) return
  collapsed.value = window.innerWidth <= MD_MAX_WIDTH
}

/**
 * 顶栏汉堡按钮：窄屏开抽屉，桌面端折叠态用来展开侧栏。
 *
 * 桌面端折叠后侧栏只有 64px，放不下「logo + 展开按钮」，原实现把按钮整个藏了，
 * 导致折叠后没有任何入口能恢复 —— 这里用顶栏按钮兜住。
 */
function openNav() {
  if (isDrawer.value) mobileOpen.value = true
  else toggleCollapse()
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

  <div v-else class="app-shell demo-shell" :style="shellStyle">
    <!-- 抽屉态下强制展开：抽屉里再显示 64px 图标条没有意义 -->
    <AppSidebar
      :collapsed="collapsed && !mobileOpen"
      :mobile-open="mobileOpen"
      @toggle-collapse="toggleCollapse"
      @close-mobile="mobileOpen = false"
    />

    <div v-if="mobileOpen" class="demo-sidebar-mask" @click="mobileOpen = false"></div>

    <div class="app-main demo-main" :class="{ 'is-chat': route.name === 'chat' }">
      <header class="app-topbar demo-topbar">
        <!-- 窄屏：开抽屉；桌面折叠态：展开侧栏（否则折叠后无入口恢复） -->
        <button
          v-if="isDrawer || collapsed"
          type="button"
          class="app-topbar__hamburger demo-icon-button demo-menu-button"
          :aria-label="isDrawer ? '打开导航' : '展开侧栏'"
          :title="isDrawer ? '打开导航' : '展开侧栏'"
          @click="openNav"
        >
          <AppIcon name="menu" :size="24" />
        </button>

        <div class="demo-topbar__crumb">
          <span>工作空间</span>
          <AppIcon name="chevron-right" :size="14" />
          <strong>{{ pageTitle }}</strong>
        </div>

        <div class="demo-topbar__right">
          <div class="app-topbar__actions">
            <component
              v-for="a in topbarActions"
              :key="a.key"
              :is="a.comp"
              v-bind="a.props"
              v-on="a.on"
            >{{ a.text }}</component>
          </div>
          <button
            class="demo-icon-button demo-help-button"
            type="button"
            aria-label="产品说明"
            :aria-expanded="infoOpen"
            aria-controls="app-info"
            @click="infoOpen = !infoOpen"
          >
            <AppIcon name="info" :size="18" />
          </button>
          <div v-if="infoOpen" id="app-info" class="demo-info" role="status">
            知识库内容由你配置的 Vault 与模型处理。运行状态及错误信息以当前服务返回为准。
          </div>
        </div>
      </header>

      <nav v-if="route.name === 'vaults'" class="demo-workflow" aria-label="知识工作流">
        <template v-for="(step, index) in workflow" :key="step.id">
          <button
            type="button"
            class="demo-workflow__step"
            :class="{
              'is-active': route.name === step.id,
              'is-complete': workflowIndex > index,
            }"
            :aria-current="route.name === step.id ? 'step' : undefined"
            @click="navigateWorkflow(step.path)"
          >
            <span class="demo-workflow__number">{{ index + 1 }}</span>
            <span>{{ step.label }}</span>
          </button>
          <span v-if="index < workflow.length - 1" class="demo-workflow__line" aria-hidden="true"></span>
        </template>
      </nav>

      <main class="app-content demo-content" :aria-label="pageTitle">
        <RouterView />
      </main>
      <footer v-if="route.name !== 'chat'" class="demo-footer">
        <span>notes-rag · 个人知识工作台</span>
        <span>数据与操作由当前服务提供</span>
      </footer>
    </div>
  </div>

  <!-- 全局提示宿主：全应用只挂一次（见 src/toast.js） -->
  <AppToast />
</template>

<style scoped>
.app-shell {
  display: block;
  min-height: 100%;
}

.demo-sidebar-mask { position: fixed; inset: 0; z-index: 20; background: var(--color-overlay); }

/* ---------- 主区 ---------- */
.app-main {
  min-height: 100vh;
  margin-left: var(--demo-sidebar-width, 242px);
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.app-topbar {
  flex: none;
}

.app-topbar__hamburger {
  display: grid;
}

.app-content {
  flex: 1 1 auto;
  width: min(100%, 1370px);
  max-width: 1370px;
  margin: 0 auto;
  padding: 32px 36px 36px;
}

.demo-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 36px 16px;
  color: var(--color-text-muted);
  font-size: 10px;
}

.demo-main.is-chat {
  height: 100vh;
  min-height: 0;
  overflow: hidden;
}
.demo-main.is-chat .app-content {
  min-height: 0;
  flex: 1;
  overflow: hidden;
  padding-bottom: 18px;
}

@media (max-width: 1080px) {
  .app-topbar, .demo-workflow { padding-right: 24px; padding-left: 24px; }
  .app-content { padding-right: 24px; padding-left: 24px; }
  .demo-footer { padding-right: 24px; padding-left: 24px; }
}

@media (max-width: 767px) {
  .app-main { margin-left: 0; }
  .app-topbar { justify-content: flex-start; padding: 0 15px; }
  .app-topbar__hamburger { display: grid; }
  .demo-sidebar-mask { display: block; }
  .app-content { min-height: calc(100vh - 156px); padding: 25px 15px 30px; }
  .demo-workflow { overflow-x: auto; min-height: 58px; padding: 0 14px; }
  .demo-workflow__step { gap: 6px; font-size: 9px; }
  .demo-workflow__number { width: 20px; height: 20px; }
  .demo-workflow__line { width: 14px; flex: none; margin: 0 2px; }
  .demo-footer { padding: 12px 15px 17px; }
  .demo-main.is-chat { height: 100dvh; }
  .demo-main.is-chat .app-content { min-height: 0; padding-top: 14px; padding-bottom: 12px; }
}

@media (max-width: 430px) {
  .demo-workflow { gap: 0; }
  .demo-workflow__step { flex: none; }
  .demo-workflow__line { width: 10px; }
  .demo-footer { font-size: 8px; }
}

.app-topbar__actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

@media (max-width: 767px) {
}
</style>
