<script setup>
import { onUnmounted, ref } from 'vue'
import ApiKeysDemo from './ApiKeysDemo.vue'
import ChatDemo from './ChatDemo.vue'
import DemoShell from './DemoShell.vue'
import ModelsDemo from './ModelsDemo.vue'
import SearchDemo from './SearchDemo.vue'
import TasksDemo from './TasksDemo.vue'
import VaultDemo from './VaultDemo.vue'

const activePage = ref('vaults')
const selectedVaultId = ref(1)
const indexProgress = ref(72)
const toastMessage = ref('')
let toastTimer

const pageTitle = {
  vaults: '知识库',
  tasks: '任务进度',
  search: '检索',
  chat: '问答',
  models: '模型管理',
  keys: 'API Keys',
}

const vaults = ref([
  {
    id: 1,
    name: '个人知识库',
    sourceType: 'server',
    sourceValue: '/srv/notes/personal',
    fileCount: 24,
    fragmentCount: 108,
    indexedAt: '今天 10:42',
    filters: { exclude: ['.obsidian/**', '.trash/**', '.git/**', 'node_modules/**'], maxKb: 10240 },
    files: [
      { name: '存储基础.md', path: '工程笔记 / 数据库', kind: 'md', updated: '今天 10:42', size: '8.4 KB' },
      { name: '向量库设计.md', path: '工程笔记 / RAG', kind: 'md', updated: '今天 09:18', size: '12.1 KB' },
      { name: '架构讨论.pdf', path: '项目资料', kind: 'pdf', updated: '昨天 16:30', size: '2.8 MB' },
      { name: '灵感摘录.md', path: '日常 / 随手记', kind: 'md', updated: '昨天 11:06', size: '3.2 KB' },
    ],
  },
  {
    id: 2,
    name: '产品研究库',
    sourceType: 'uploaded',
    sourceValue: '本机上传 · 4 个文件',
    fileCount: 4,
    fragmentCount: 31,
    indexedAt: '昨天 18:20',
    filters: { exclude: ['.obsidian/**', '.trash/**', 'research/drafts/**'], maxKb: 5120 },
    files: [
      { name: '用户访谈.md', path: '调研 / 访谈', kind: 'md', updated: '昨天 18:20', size: '14.2 KB' },
      { name: '竞品分析.pdf', path: '调研 / 竞品', kind: 'pdf', updated: '昨天 16:04', size: '1.6 MB' },
    ],
  },
])

function showToast(message) {
  toastMessage.value = message
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    toastMessage.value = ''
  }, 2800)
}

function addVault(draft) {
  const id = Math.max(0, ...vaults.value.map((vault) => vault.id)) + 1
  vaults.value = [
    ...vaults.value,
    {
      ...draft,
      id,
      fileCount: draft.sourceType === 'uploaded' ? 6 : 0,
      fragmentCount: 0,
      indexedAt: '尚未索引',
      files: [],
    },
  ]
  selectedVaultId.value = id
  showToast(`已添加演示 Vault「${draft.name}」`)
}

function removeVault(id) {
  if (vaults.value.length < 2) {
    showToast('至少保留一个演示 Vault')
    return
  }
  vaults.value = vaults.value.filter((vault) => vault.id !== id)
  if (selectedVaultId.value === id) selectedVaultId.value = vaults.value[0].id
  showToast('已从演示列表移除 Vault')
}

function updateVaultFiles({ vaultId, fileCount }) {
  vaults.value = vaults.value.map((vault) =>
    vault.id === vaultId
      ? { ...vault, fileCount, fragmentCount: 0, sourceValue: '本机上传 · 6 个文件', indexedAt: '刚刚更新 · 待索引' }
      : vault,
  )
  selectedVaultId.value = vaultId
  indexProgress.value = 72
  activePage.value = 'tasks'
  showToast('演示文件夹已替换，已提交索引任务')
}

function updateVaultFilters({ vaultId, filters }) {
  vaults.value = vaults.value.map((vault) =>
    vault.id === vaultId ? { ...vault, filters } : vault,
  )
  showToast('演示过滤规则已保存')
}

function startIndex({ vaultId, mode }) {
  selectedVaultId.value = vaultId
  indexProgress.value = 72
  activePage.value = 'tasks'
  showToast(`${mode}任务已在演示中启动`)
}

function completeIndex() {
  indexProgress.value = 100
  showToast('演示任务已完成')
}

onUnmounted(() => {
  window.clearTimeout(toastTimer)
})
</script>

<template>
  <DemoShell
    :active-page="activePage"
    :page-title="pageTitle[activePage]"
    @navigate="activePage = $event"
  >
    <VaultDemo
      v-if="activePage === 'vaults'"
      :vaults="vaults"
      :selected-vault-id="selectedVaultId"
      :index-progress="indexProgress"
      @select-vault="selectedVaultId = $event"
      @create-vault="addVault"
      @remove-vault="removeVault"
      @update-files="updateVaultFiles"
      @update-filters="updateVaultFilters"
      @start-index="startIndex"
      @notify="showToast"
    />
    <TasksDemo
      v-else-if="activePage === 'tasks'"
      :progress="indexProgress"
      :vault-name="vaults.find((vault) => vault.id === selectedVaultId)?.name || '个人知识库'"
      @complete="completeIndex"
      @navigate="activePage = $event"
    />
    <SearchDemo
      v-else-if="activePage === 'search'"
      :vaults="vaults"
      :selected-vault-id="selectedVaultId"
      @notify="showToast"
    />
    <ChatDemo
      v-else-if="activePage === 'chat'"
      :vaults="vaults"
      :selected-vault-id="selectedVaultId"
      @notify="showToast"
    />
    <ModelsDemo
      v-else-if="activePage === 'models'"
      @notify="showToast"
    />
    <ApiKeysDemo
      v-else
      @notify="showToast"
    />
  </DemoShell>

  <Transition name="demo-toast">
    <div v-if="toastMessage" class="demo-toast" role="status" aria-live="polite">
      <span class="demo-toast__dot" aria-hidden="true"></span>
      {{ toastMessage }}
    </div>
  </Transition>
</template>
