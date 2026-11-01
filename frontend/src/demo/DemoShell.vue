<script setup>
import { computed, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import AppThemePicker from '../components/AppThemePicker.vue'

const props = defineProps({
  activePage: { type: String, required: true },
  pageTitle: { type: String, required: true },
})

const emit = defineEmits(['navigate'])
const mobileNavOpen = ref(false)
const infoOpen = ref(false)

const navigation = [
  { id: 'vaults', label: '知识库', icon: 'vaults', hint: '文件与集合' },
  { id: 'tasks', label: '任务进度', icon: 'tasks', hint: '索引与同步' },
  { id: 'search', label: '检索', icon: 'search', hint: '语义搜索' },
  { id: 'chat', label: '问答', icon: 'chat', hint: '对话与引用' },
  { id: 'models', label: '模型管理', icon: 'models', hint: 'LLM · Embed · ASR' },
  { id: 'keys', label: 'API Keys', icon: 'keys', hint: 'MCP 与授权' },
]

const workflow = [
  { id: 'vaults', label: '文件入库' },
  { id: 'tasks', label: '索引构建' },
  { id: 'search', label: '语义检索' },
  { id: 'chat', label: '问答与引用' },
  { id: 'keys', label: '助手调用' },
]

const workflowIndex = computed(() => workflow.findIndex((step) => step.id === props.activePage))

function navigate(page) {
  emit('navigate', page)
  mobileNavOpen.value = false
}
</script>

<template>
  <div class="demo-shell">
    <aside class="demo-sidebar" :class="{ 'is-open': mobileNavOpen }" aria-label="主导航">
      <a class="demo-brand" href="#top" @click.prevent="navigate('vaults')">
        <span class="demo-brand__mark" aria-hidden="true">n</span>
        <span class="demo-brand__copy">
          <strong>notes-rag</strong>
          <small>PERSONAL KNOWLEDGE</small>
        </span>
      </a>

      <div class="demo-sidebar__section-label">工作空间</div>
      <nav class="demo-nav">
        <button
          v-for="item in navigation"
          :key="item.id"
          type="button"
          class="demo-nav__item"
          :class="{ 'is-active': activePage === item.id }"
          :aria-current="activePage === item.id ? 'page' : undefined"
          @click="navigate(item.id)"
        >
          <AppIcon :name="item.icon" :size="19" />
          <span class="demo-nav__copy">
            <strong>{{ item.label }}</strong>
            <small>{{ item.hint }}</small>
          </span>
        </button>
      </nav>

      <div class="demo-sidebar__spacer"></div>

      <div class="demo-health">
        <span class="demo-health__mark" aria-hidden="true"><AppIcon name="check" :size="14" /></span>
        <span>
          <strong>交互评审模式</strong>
          <small>不连接业务后端</small>
        </span>
        <span class="demo-health__signal" aria-label="演示模式"></span>
      </div>

      <AppThemePicker />

      <div class="demo-user">
        <span class="demo-user__avatar" aria-hidden="true">G</span>
        <span class="demo-user__name">
          <strong>我的工作区</strong>
          <small>个人空间 · 示例数据</small>
        </span>
        <AppIcon name="chevron-down" :size="16" />
      </div>
    </aside>

    <div
      v-if="mobileNavOpen"
      class="demo-sidebar-mask"
      aria-hidden="true"
      @click="mobileNavOpen = false"
    ></div>

    <main id="top" class="demo-main" :class="{ 'is-chat': activePage === 'chat' }">
      <header class="demo-topbar">
        <button
          class="demo-icon-button demo-menu-button"
          type="button"
          aria-label="打开导航"
          :aria-expanded="mobileNavOpen"
          @click="mobileNavOpen = !mobileNavOpen"
        >
          <AppIcon name="menu" :size="20" />
        </button>
        <div class="demo-topbar__crumb">
          <span>工作空间</span>
          <AppIcon name="chevron-right" :size="14" />
          <strong>{{ pageTitle }}</strong>
        </div>
        <div class="demo-topbar__right">
          <span class="demo-mode-badge">
            <span aria-hidden="true"></span>
            交互演示
          </span>
          <button
            class="demo-icon-button demo-help-button"
            type="button"
            aria-label="演示说明"
            title="演示数据仅保存在当前页面，不会调用后端"
            :aria-expanded="infoOpen"
            aria-controls="demo-info"
            @click="infoOpen = !infoOpen"
          >
            <AppIcon name="info" :size="18" />
          </button>
          <div v-if="infoOpen" id="demo-info" class="demo-info" role="status">
            这是交互评审稿。页面使用预置内容，不会读取本地文件或调用真实服务。
          </div>
        </div>
      </header>

      <div v-if="activePage === 'vaults'" class="demo-workflow" aria-label="知识工作流">
        <template v-for="(item, index) in workflow" :key="item.id">
          <button
            type="button"
            class="demo-workflow__step"
            :class="{
              'is-active': activePage === item.id,
              'is-complete': workflowIndex > index,
            }"
            :aria-current="activePage === item.id ? 'step' : undefined"
            @click="navigate(item.id)"
          >
            <span class="demo-workflow__number">{{ index + 1 }}</span>
            <span>{{ item.label }}</span>
          </button>
          <span v-if="index < workflow.length - 1" class="demo-workflow__line" aria-hidden="true"></span>
        </template>
      </div>

      <section class="demo-content" aria-live="polite">
        <slot></slot>
      </section>

      <footer v-if="activePage !== 'chat'" class="demo-footer">
        <span>notes-rag · UI 设计评审稿</span>
        <span>示例内容仅用于交互演示</span>
      </footer>
    </main>
  </div>
</template>
