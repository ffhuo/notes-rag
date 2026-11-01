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

const demoFileTemplates = [
  { title: '存储基础', path: '工程笔记 / 数据库', kind: 'md', size: '8.4 KB' },
  { title: '向量库设计', path: '工程笔记 / RAG', kind: 'md', size: '12.1 KB' },
  { title: '架构讨论', path: '项目资料', kind: 'pdf', size: '2.8 MB' },
  { title: '灵感摘录', path: '日常 / 随手记', kind: 'md', size: '3.2 KB' },
  { title: '检索评估记录', path: '工程笔记 / RAG / 评估', kind: 'md', size: '6.7 KB' },
  { title: '产品需求说明', path: '项目资料 / 产品', kind: 'md', size: '18.5 KB' },
  { title: '服务部署手册', path: '运维 / 手册', kind: 'pdf', size: '1.2 MB' },
  { title: '阅读清单', path: '日常 / 阅读', kind: 'md', size: '4.1 KB' },
  { title: '同步策略', path: '工程笔记 / 数据库', kind: 'md', size: '9.6 KB' },
  { title: '访谈纪要', path: '项目资料 / 调研', kind: 'md', size: '15.3 KB' },
  { title: '接口约定', path: '工程笔记 / 架构', kind: 'md', size: '7.9 KB' },
  { title: '季度复盘', path: '项目资料 / 复盘', kind: 'pdf', size: '940 KB' },
]
const demoFileStatuses = ['indexed', 'indexed', 'indexed', 'indexed', 'indexed', 'indexed', 'indexed', 'indexed', 'indexing', 'pending', 'indexed', 'error']

function createDemoFiles(count) {
  return Array.from({ length: count }, (_, index) => {
    const template = demoFileTemplates[index % demoFileTemplates.length]
    return {
      name: `${template.title} ${String(index + 1).padStart(2, '0')}.${template.kind}`,
      path: template.path,
      kind: template.kind,
      updated: index % 3 === 0 ? '今天 10:42' : index % 3 === 1 ? '今天 09:18' : '昨天 16:30',
      size: template.size,
      status: demoFileStatuses[index % demoFileStatuses.length],
    }
  })
}

const vaults = ref([
  {
    id: 1,
    name: '个人知识库',
    sourceType: 'server',
    sourceValue: '/srv/notes/personal',
    fileCount: 48,
    fragmentCount: 216,
    indexedAt: '今天 10:42',
    filters: { exclude: ['.obsidian/**', '.trash/**', '.git/**', 'node_modules/**'], maxKb: 10240 },
    files: createDemoFiles(48),
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
      { name: '用户访谈.md', path: '调研 / 访谈', kind: 'md', updated: '昨天 18:20', size: '14.2 KB', status: 'indexed' },
      { name: '竞品分析.pdf', path: '调研 / 竞品', kind: 'pdf', updated: '昨天 16:04', size: '1.6 MB', status: 'indexed' },
      { name: '需求优先级.md', path: '调研 / 产品', kind: 'md', updated: '昨天 15:12', size: '7.8 KB', status: 'indexed' },
      { name: '访谈摘要.md', path: '调研 / 访谈', kind: 'md', updated: '昨天 14:40', size: '11.3 KB', status: 'indexed' },
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
      files: draft.sourceType === 'uploaded' ? createDemoFiles(6).map((file) => ({ ...file, status: 'pending' })) : [],
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
      ? {
          ...vault,
          fileCount,
          fragmentCount: 0,
          files: createDemoFiles(fileCount).map((file) => ({ ...file, status: 'pending' })),
          sourceValue: `本机上传 · ${fileCount} 个文件`,
          indexedAt: '刚刚更新 · 待索引',
        }
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
