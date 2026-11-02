<script setup>
// 侧栏导航（T1.2 导航 + active 态 / T1.3 折叠 / T1.4 移动端抽屉）
//
// 文案单一来源：label 取自对应路由的 meta.title（见 router.js 的 NAV_ITEMS），
// 不在本组件重写一遍「知识库 / 任务与进度…」。
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { NAV_ITEMS } from '../router'
import { authState, canLogout, logout } from '../auth'
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
const hints = {
  vaults: '文件与集合',
  tasks: '索引与同步',
  search: '语义搜索',
  chat: '对话与引用',
  models: 'LLM · Embed · ASR',
  keys: 'MCP 与授权',
}
const items = computed(() => NAV_ITEMS.map((n) => ({
  ...n,
  active: route.name === n.name,
  hint: hints[n.name],
})))

/** 当前身份名（多用户为账号名；单用户为合成身份 default）。 */
const userName = computed(() => authState.user?.username || '当前用户')
const userInitial = computed(() => userName.value.trim().charAt(0).toUpperCase() || 'N')

/**
 * 产品版本号（如 v1.0）。
 *
 * 取自 GET /healthz 而非前端写死：版本是**当前运行中的服务**的属性，读服务端才能
 * 反映「部署的到底是哪一版」（前端静态资源被缓存时，写死反而会骗人）。
 * 请求失败就不显示，不为此弹错误打扰用户。
 */
const version = ref('')
onMounted(async () => {
  try {
    const res = await fetch('/healthz')
    if (!res.ok) return
    const data = await res.json()
    if (data?.version) version.value = `v${data.version}`
  } catch {
    /* 服务信息拿不到时静默降级：品牌照常显示 */
  }
})
</script>

<template>
  <aside
    class="app-sidebar demo-sidebar"
    :class="{ 'is-collapsed': collapsed, 'is-open': mobileOpen }"
  >
    <div class="demo-sidebar__head">
      <RouterLink class="demo-brand" to="/vaults" @click="emit('close-mobile')">
        <span class="demo-brand__mark" aria-hidden="true">n</span>
        <span class="demo-brand__copy">
          <strong>notes-rag</strong>
          <small>PERSONAL KNOWLEDGE</small>
        </span>
        <span v-if="version" class="app-sidebar__version" :title="`当前服务版本 ${version}`">{{ version }}</span>
      </RouterLink>
      <button
        type="button"
        class="demo-icon-button app-sidebar__collapse"
        :title="collapsed ? '展开侧栏' : '折叠侧栏'"
        :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'"
        :aria-expanded="!collapsed"
        @click="emit('toggle-collapse')"
      >
        <AppIcon :name="collapsed ? 'chevron-right' : 'chevron-left'" :size="15" />
      </button>
    </div>

    <div class="demo-sidebar__section-label">工作空间</div>
    <nav class="demo-nav" aria-label="工作空间">
      <RouterLink
        v-for="item in items"
        :key="item.name"
        class="demo-nav__item"
        :class="{ 'is-active': item.active }"
        :to="item.to"
        :title="collapsed ? item.label : ''"
        :aria-current="item.active ? 'page' : undefined"
        @click="emit('close-mobile')"
      >
        <AppIcon :name="item.icon" :size="19" />
        <span class="demo-nav__copy">
          <strong>{{ item.label }}</strong>
          <small>{{ item.hint }}</small>
        </span>
      </RouterLink>
    </nav>

    <div class="demo-sidebar__spacer"></div>
    <AppJobStatus class="demo-health-card" :collapsed="collapsed" />
    <div class="app-sidebar__foot">
      <AppThemePicker :collapsed="collapsed" />

      <!-- 退出登录：仅在确有凭据可清时出现（单用户免鉴权模式没有账号概念，不显示） -->
      <div class="demo-user">
        <span class="demo-user__avatar" aria-hidden="true">{{ userInitial }}</span>
        <span class="demo-user__name" :title="userName">
          <strong>{{ userName }}</strong>
          <small>{{ canLogout ? '已登录' : '个人工作区' }}</small>
        </span>
        <button
          v-if="canLogout"
          type="button"
          class="demo-icon-button app-sidebar__logout"
          :title="collapsed ? '退出登录' : '退出登录'"
          aria-label="退出登录"
          @click="logout"
        >
          <AppIcon name="logout" :size="16" />
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 30;
  width: var(--demo-sidebar-width, 242px);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 18px 15px 12px;
  background: var(--ui-surface);
  border-right: 1px solid var(--ui-border);
  transition: width 0.18s ease, transform 0.2s ease;
}

.demo-sidebar__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 43px;
  margin-bottom: 5px;
}

.app-sidebar__collapse {
  flex: none;
}

.demo-health-card {
  flex: none;
  background: var(--ui-surface-soft);
  border: 1px solid var(--ui-border);
  border-radius: 10px;
}

.app-sidebar__foot {
  flex: none;
  margin-top: 9px;
}

.app-sidebar__version {
  flex: none;
  color: var(--ui-muted);
  font-size: 8px;
}

.app-sidebar__logout {
  flex: none;
}

.app-sidebar.is-collapsed {
  width: 64px;
  padding-right: 8px;
  padding-left: 8px;
}

.is-collapsed .demo-brand {
  justify-content: center;
  padding: 0;
}

.is-collapsed .demo-brand__copy,
.is-collapsed .app-sidebar__version,
.is-collapsed .app-sidebar__collapse,
.is-collapsed .demo-sidebar__section-label,
.is-collapsed .demo-nav__copy,
.is-collapsed .demo-user__name,
.is-collapsed .demo-user__avatar {
  display: none;
}

.is-collapsed .demo-nav__item {
  justify-content: center;
  padding-right: 0;
  padding-left: 0;
}

.is-collapsed .demo-health-card {
  display: block;
}

.is-collapsed .demo-health-card :deep(.job-status__btn) {
  justify-content: center;
  padding-right: 0;
  padding-left: 0;
}

.is-collapsed .app-sidebar__foot :deep(.theme-picker) {
  align-items: center;
  padding: 8px 0 0;
}

.demo-health-card :deep(.job-status__btn) {
  width: 100%;
  min-height: 48px;
  padding: 8px;
  border-color: transparent;
}

.demo-health-card :deep(.job-status__title) {
  font-size: 9px;
}

.demo-health-card :deep(.job-status__meta),
.demo-health-card :deep(.job-status__vault) {
  font-size: 8px;
}

.app-sidebar__foot :deep(.theme-picker) {
  gap: 8px;
  padding: 12px 5px 8px;
  border-top: 1px solid var(--ui-border);
}

.app-sidebar__foot :deep(.theme-picker__label) {
  width: 36px;
  font-size: 8px;
}

.app-sidebar__foot :deep(.theme-picker__swatch) {
  width: 21px;
  height: 21px;
}

.app-sidebar__foot :deep(.theme-picker__dot) {
  width: 13px;
  height: 13px;
}

.app-sidebar__foot :deep(.theme-picker__seg-btn) {
  width: 27px;
  height: 24px;
}

.app-sidebar__foot :deep(.theme-picker.is-collapsed) {
  justify-content: space-evenly;
  padding: 5px 0;
  border-top: 0;
}

.demo-user {
  min-width: 0;
}

.demo-user__name {
  min-width: 0;
  overflow: hidden;
}

.demo-user__name strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 767px) {
  .app-sidebar,
  .app-sidebar.is-collapsed {
    width: min(280px, 84vw);
    max-width: 84vw;
    transform: translateX(-100%);
    box-shadow: var(--shadow-lg);
  }

  .app-sidebar.is-open {
    transform: translateX(0);
  }

  .app-sidebar__collapse {
    display: none;
  }
}
</style>
