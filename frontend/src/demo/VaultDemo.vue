<script setup>
import { computed, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'

const FILE_PAGE_SIZE = 20
const FILE_STATUSES = [
  { id: 'all', label: '全部' },
  { id: 'indexed', label: '索引完成' },
  { id: 'indexing', label: '索引中' },
  { id: 'pending', label: '待索引' },
  { id: 'error', label: '错误' },
]
const FILE_STATUS_LABELS = {
  indexed: '索引完成',
  indexing: '索引中',
  pending: '待索引',
  error: '错误',
}

const props = defineProps({
  vaults: { type: Array, required: true },
  selectedVaultId: { type: Number, required: true },
  indexProgress: { type: Number, required: true },
})

const emit = defineEmits(['selectVault', 'createVault', 'removeVault', 'updateFiles', 'updateFilters', 'startIndex', 'notify'])
const defaultRules = ['.obsidian/**', '.trash/**', '.git/**', 'node_modules/**', '__pycache__/**', '.venv/**']
const treeRules = [
  { label: '.obsidian 设置', value: '.obsidian/**' },
  { label: '回收站', value: '.trash/**' },
  { label: 'Git 元数据', value: '.git/**' },
  { label: '依赖目录', value: 'node_modules/**' },
  { label: 'Python 环境', value: '.venv/**' },
]
const query = ref('')
const fileStatusFilter = ref('all')
const filePage = ref(1)
const addOpen = ref(false)
const editOpen = ref(false)
const deleteTarget = ref(null)
const updateTarget = ref(null)
const addError = ref('')
const sourceType = ref('server')
const folderSelected = ref(false)
const newForm = ref(blankForm())
const editForm = ref({ exclude: '', maxKb: 10240 })

const selectedVault = computed(
  () => props.vaults.find((vault) => vault.id === props.selectedVaultId) || props.vaults[0],
)
const files = computed(() => selectedVault.value?.files || [])
const fileStatusCounts = computed(() =>
  files.value.reduce(
    (counts, file) => ({ ...counts, [file.status]: (counts[file.status] || 0) + 1 }),
    {},
  ),
)
const filteredFiles = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  return files.value.filter((file) => {
    const matchesText = !term || `${file.name} ${file.path}`.toLocaleLowerCase().includes(term)
    const matchesStatus = fileStatusFilter.value === 'all' || file.status === fileStatusFilter.value
    return matchesText && matchesStatus
  })
})
const filePageCount = computed(() => Math.max(1, Math.ceil(filteredFiles.value.length / FILE_PAGE_SIZE)))
const pageFiles = computed(() => {
  const start = (filePage.value - 1) * FILE_PAGE_SIZE
  return filteredFiles.value.slice(start, start + FILE_PAGE_SIZE)
})
const fileRangeStart = computed(() => (filteredFiles.value.length ? (filePage.value - 1) * FILE_PAGE_SIZE + 1 : 0))
const fileRangeEnd = computed(() => Math.min(filePage.value * FILE_PAGE_SIZE, filteredFiles.value.length))
const progressLabel = computed(() => `${props.indexProgress}%`)

watch([query, fileStatusFilter], () => {
  filePage.value = 1
})

watch(
  () => props.selectedVaultId,
  () => {
    query.value = ''
    fileStatusFilter.value = 'all'
    filePage.value = 1
  },
)

function blankForm() {
  return { name: '', path: '', exclude: defaultRules.join('\n'), maxKb: 10240 }
}

function openAdd(type) {
  updateTarget.value = null
  sourceType.value = type
  newForm.value = blankForm()
  folderSelected.value = false
  addError.value = ''
  addOpen.value = true
}

function openUpdate(vault) {
  updateTarget.value = vault
  sourceType.value = 'uploaded'
  newForm.value = {
    name: vault.name,
    path: '',
    exclude: (vault.filters?.exclude || defaultRules).join('\n'),
    maxKb: vault.filters?.maxKb || 10240,
  }
  folderSelected.value = false
  addError.value = ''
  addOpen.value = true
}

function toggleRule(value, checked) {
  const rules = new Set(newForm.value.exclude.split(/[\n,，]/).map((rule) => rule.trim()).filter(Boolean))
  if (checked) rules.add(value)
  else rules.delete(value)
  newForm.value.exclude = [...rules].join('\n')
}

function submitAdd() {
  const name = newForm.value.name.trim()
  if (!name) {
    addError.value = '请填写 Vault 名称。'
    return
  }
  if (sourceType.value === 'server' && !newForm.value.path.trim()) {
    addError.value = '服务器目录需要填写服务端绝对路径。'
    return
  }
  if (sourceType.value === 'uploaded' && !folderSelected.value) {
    addError.value = '请先选择一个演示文件夹。'
    return
  }
  if (updateTarget.value) {
    emit('updateFiles', { vaultId: updateTarget.value.id, fileCount: 6 })
    updateTarget.value = null
  } else {
    emit('createVault', {
      name,
      sourceType: sourceType.value,
      sourceValue: sourceType.value === 'server' ? newForm.value.path.trim() : '本机上传 · 6 个示例文件',
      filters: {
        exclude: newForm.value.exclude.split(/[\n,，]/).map((rule) => rule.trim()).filter(Boolean),
        maxKb: Number(newForm.value.maxKb) || 0,
      },
    })
  }
  addOpen.value = false
}

function openFilters(vault) {
  editForm.value = {
    exclude: (vault.filters?.exclude || []).join('\n'),
    maxKb: vault.filters?.maxKb || 10240,
  }
  editOpen.value = true
}

function saveFilters() {
  emit('updateFilters', {
    vaultId: selectedVault.value.id,
    filters: {
      exclude: editForm.value.exclude.split(/[\n,，]/).map((rule) => rule.trim()).filter(Boolean),
      maxKb: Number(editForm.value.maxKb) || 0,
    },
  })
  editOpen.value = false
}

function beginIndex(mode) {
  emit('startIndex', { vaultId: selectedVault.value.id, mode })
}
</script>

<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow"><span class="eyebrow__dot"></span> YOUR KNOWLEDGE, IN ONE PLACE</div>
      <h1>让笔记，成为可用的知识</h1>
      <p>管理多个 Vault，从文件入库到索引完成，掌握每一步。</p>
    </div>
    <div class="vault-intro__actions">
      <button class="button button--secondary" type="button" @click="openAdd('uploaded')">
        <AppIcon name="upload" :size="16" />上传本机文件夹
      </button>
      <button class="button button--primary" type="button" @click="openAdd('server')">
        <AppIcon name="plus" :size="17" />添加服务器目录
      </button>
    </div>
  </div>

  <div class="vault-page-grid">
    <div class="vault-main-column">
      <section class="vault-list-section">
        <div class="section-heading">
          <div><h2>我的知识库</h2></div>
          <span class="count-chip">{{ vaults.length }} 个 Vault</span>
        </div>
        <div class="vault-cards">
          <article
            v-for="vault in vaults"
            :key="vault.id"
            class="panel vault-card"
            :class="{ 'is-selected': vault.id === selectedVaultId }"
          >
            <button class="vault-card__select" type="button" @click="emit('selectVault', vault.id)">
              <span class="vault-card__icon"><AppIcon name="vaults" :size="19" /></span>
              <span class="vault-card__copy">
                <strong>{{ vault.name }}</strong>
                <small><AppIcon :name="vault.sourceType === 'uploaded' ? 'upload' : 'folder'" :size="13" />{{ vault.sourceType === 'uploaded' ? '本机上传' : '服务器目录' }}</small>
              </span>
              <span v-if="vault.id === selectedVaultId" class="vault-card__check"><AppIcon name="check" :size="13" /></span>
            </button>
            <div class="vault-card__stats">
              <span><strong>{{ vault.fileCount }}</strong> 个文件</span>
              <span><strong>{{ vault.fragmentCount }}</strong> 个片段</span>
              <span
                class="status-pill"
                :class="vault.indexedAt === '尚未索引' ? 'status-pill--pending' : 'status-pill--success'"
              >
                <span></span>{{ vault.indexedAt === '尚未索引' ? '待索引' : '已就绪' }}
              </span>
            </div>
            <p class="vault-card__path" :title="vault.sourceValue">
              <AppIcon :name="vault.sourceType === 'uploaded' ? 'upload' : 'folder'" :size="13" />
              <span>{{ vault.sourceValue }}</span>
            </p>
          </article>
        </div>
      </section>

      <section v-if="selectedVault" class="panel files-panel">
        <div class="files-panel__heading">
          <div class="files-panel__title">
            <span class="section-icon"><AppIcon name="folder" :size="18" /></span>
            <div><h2>{{ selectedVault.name }}</h2><p>{{ files.length }} 个文件 · 文件状态与索引进度</p></div>
          </div>
          <section class="recent-sync-card" aria-label="最近一次同步进度">
            <div class="recent-sync-card__top">
              <span class="recent-sync-card__title"><AppIcon name="refresh" :size="14" />最近一次同步</span>
              <span class="status-pill status-pill--running"><span></span>进行中</span>
              <strong class="recent-sync-card__percent">{{ progressLabel }}</strong>
            </div>
            <div class="recent-sync-card__track" role="progressbar" :aria-valuenow="indexProgress" aria-valuemin="0" aria-valuemax="100" aria-label="同步进度">
              <span :style="{ width: progressLabel }"></span>
            </div>
            <ol class="sync-stages" aria-label="同步阶段">
              <li class="is-done"><span class="sync-stages__mark"><AppIcon name="check" :size="10" /></span><span>扫描文件</span></li>
              <li class="is-active" aria-current="step"><span class="sync-stages__mark"><AppIcon name="zap" :size="10" /></span><span>解析与分块</span></li>
              <li><span class="sync-stages__mark">3</span><span>写入索引</span></li>
            </ol>
          </section>
        </div>
        <div class="vault-actions">
          <div class="vault-actions__buttons">
            <button v-if="selectedVault.sourceType === 'uploaded'" class="button button--secondary" type="button" @click="openUpdate(selectedVault)">
              <AppIcon name="upload" :size="15" />更新文件
            </button>
            <template v-else>
              <button class="button button--secondary" type="button" @click="beginIndex('sync')"><AppIcon name="refresh" :size="15" />同步</button>
              <button class="button button--secondary" type="button" @click="beginIndex('preview')">预览变更</button>
            </template>
            <button class="button button--secondary" type="button" @click="beginIndex('rebuild')"><AppIcon name="zap" :size="15" />重建索引</button>
            <button class="button button--quiet" type="button" @click="openFilters(selectedVault)"><AppIcon name="filter" :size="15" />过滤设置</button>
            <button class="button button--danger-quiet" type="button" @click="deleteTarget = selectedVault"><AppIcon name="trash" :size="15" />删除</button>
          </div>
        </div>
        <div class="files-panel__meta">
          <span><AppIcon name="clock" :size="14" />上次索引：{{ selectedVault.indexedAt }}</span>
          <span><AppIcon name="filter" :size="14" />排除 {{ selectedVault.filters?.exclude?.length || 0 }} 项 · 单文件 ≤ {{ selectedVault.filters?.maxKb || 0 }} KB</span>
        </div>
        <div class="files-controls">
          <div class="file-status-filters" role="group" aria-label="按索引状态筛选文件">
            <button
              v-for="status in FILE_STATUSES"
              :key="status.id"
              type="button"
              class="file-status-filter"
              :class="{ 'is-active': fileStatusFilter === status.id, [`is-${status.id}`]: status.id !== 'all' }"
              :aria-pressed="fileStatusFilter === status.id"
              @click="fileStatusFilter = status.id"
            >
              <span v-if="status.id !== 'all'" class="file-status-filter__dot"></span>
              {{ status.label }}
              <span class="file-status-filter__count">{{ status.id === 'all' ? files.length : fileStatusCounts[status.id] || 0 }}</span>
            </button>
          </div>
          <label class="file-search">
            <AppIcon name="search" :size="15" />
            <input v-model="query" type="search" placeholder="搜索文件" aria-label="搜索文件" />
          </label>
        </div>
        <div v-if="pageFiles.length" class="file-list" aria-live="polite">
          <button
            v-for="file in pageFiles"
            :key="`${file.path}/${file.name}`"
            type="button"
            class="file-row"
            @click="emit('notify', `已选择 ${file.name}（示例文件）`)"
          >
            <span class="file-row__icon" :class="`is-${file.kind}`"><AppIcon name="file-text" :size="18" /></span>
            <span class="file-row__name"><strong>{{ file.name }}</strong><small>{{ file.path }}</small></span>
            <span class="file-row__updated">{{ file.updated }}</span>
            <span class="file-row__size">{{ file.size }}</span>
            <span class="file-status" :class="`file-status--${file.status}`">
              <span class="file-status__dot"></span>{{ FILE_STATUS_LABELS[file.status] || '待索引' }}
            </span>
            <AppIcon name="chevron-right" :size="16" />
          </button>
        </div>
        <div v-else class="file-empty">
          {{ files.length ? '没有符合当前搜索和状态筛选的文件。' : '当前 Vault 暂无演示文件，开始同步后会显示文件清单。' }}
        </div>
        <nav v-if="filePageCount > 1" class="file-pagination" aria-label="文件列表分页">
          <span>显示 {{ fileRangeStart }}–{{ fileRangeEnd }} 项，共 {{ filteredFiles.length }} 项</span>
          <div class="file-pagination__controls">
            <button type="button" :disabled="filePage === 1" @click="filePage -= 1">
              <AppIcon name="chevron-left" :size="14" />上一页
            </button>
            <span>第 {{ filePage }} / {{ filePageCount }} 页</span>
            <button type="button" :disabled="filePage === filePageCount" @click="filePage += 1">
              下一页<AppIcon name="chevron-right" :size="14" />
            </button>
          </div>
        </nav>
      </section>

      <div class="vault-tip"><AppIcon name="info" :size="15" /><span>服务器目录路径指服务端机器；上传方式才会从当前电脑选择文件夹。过滤规则只配置要排除的内容。</span></div>
      <section class="privacy-card"><span class="privacy-card__mark"><AppIcon name="check" :size="15" /></span><div><strong>你的笔记，仍在本地</strong><p>演示不会读取或上传任何文件。</p></div></section>
    </div>
  </div>

  <div v-if="addOpen" class="dialog-backdrop" @click.self="addOpen = false">
    <section class="dialog-card dialog-card--wide" role="dialog" aria-modal="true" aria-labelledby="add-vault-title" @keydown.esc.prevent="addOpen = false">
      <div class="dialog-card__heading">
        <span class="section-icon"><AppIcon :name="sourceType === 'server' ? 'folder' : 'upload'" :size="18" /></span>
        <button class="demo-icon-button" type="button" aria-label="关闭" @click="addOpen = false"><AppIcon name="close" :size="18" /></button>
      </div>
      <h2 id="add-vault-title">{{ updateTarget ? '更新已上传的文件夹' : sourceType === 'server' ? '添加服务器目录' : '上传本机文件夹' }}</h2>
      <p class="dialog-card__desc">{{ updateTarget ? '整包替换服务端副本；过滤规则只作用于本次上传，不会覆盖 Vault 已保存的规则。' : '先选来源，再设置这一个 Vault 的索引过滤规则。' }}</p>
      <div v-if="!updateTarget" class="source-tabs" role="tablist" aria-label="Vault 来源类型">
        <button type="button" role="tab" :aria-selected="sourceType === 'server'" :class="{ 'is-active': sourceType === 'server' }" @click="sourceType = 'server'; addError = ''"><AppIcon name="folder" :size="16" />服务器目录</button>
        <button type="button" role="tab" :aria-selected="sourceType === 'uploaded'" :class="{ 'is-active': sourceType === 'uploaded' }" @click="sourceType = 'uploaded'; addError = ''"><AppIcon name="upload" :size="16" />上传本机文件夹</button>
      </div>
      <form class="dialog-form" @submit.prevent="submitAdd">
        <label class="form-field"><span>Vault 名称</span><input v-model="newForm.name" required maxlength="60" :disabled="!!updateTarget" placeholder="例如：工作笔记" /></label>
        <label v-if="sourceType === 'server'" class="form-field"><span>服务器目录绝对路径</span><input v-model="newForm.path" required placeholder="/srv/notes" /><small>填写运行服务的机器上可读取的路径，不是当前电脑的路径。</small></label>
        <div v-else class="folder-picker">
          <span class="form-field__label">待上传的文件夹</span>
          <button class="button button--secondary" type="button" @click="folderSelected = true"><AppIcon name="folder" :size="16" />{{ folderSelected ? '已选择示例文件夹' : '选择示例文件夹' }}</button>
          <small>{{ folderSelected ? 'sample-notes · 6 个演示文件（不会上传）' : '本机文件夹在真实产品中会打包后上传；此处仅模拟选择。' }}</small>
        </div>

        <details class="filter-details" open>
          <summary><span><AppIcon name="filter" :size="16" />文件过滤</span><small>只配置不索引的内容</small></summary>
          <p>按目录树快速加入规则，也可以直接编辑 glob。留空时仍会排除服务端默认目录。</p>
          <div class="filter-tree">
            <label v-for="rule in treeRules" :key="rule.value">
              <input type="checkbox" :checked="newForm.exclude.split(/[\n,，]/).map((item) => item.trim()).includes(rule.value)" @change="toggleRule(rule.value, $event.target.checked)" />
              <span>{{ rule.label }}</span><code>{{ rule.value }}</code>
            </label>
          </div>
          <label class="form-field"><span>排除规则</span><textarea v-model="newForm.exclude" rows="3" placeholder=".obsidian/**&#10;**/*.tmp"></textarea><small>一行一条；支持相对路径 glob 和扩展名（如 .py）。</small></label>
          <label class="form-field"><span>单文件大小上限（KB）</span><input v-model.number="newForm.maxKb" type="number" min="0" placeholder="10240" /><small>超过上限的文件会跳过；留空使用服务端默认 10 MB。</small></label>
        </details>
        <p v-if="addError" class="form-error" role="alert">{{ addError }}</p>
        <div class="dialog-card__actions"><button class="button button--secondary" type="button" @click="addOpen = false">取消</button><button class="button button--primary" type="submit">{{ updateTarget ? '更新示例文件并索引' : '添加演示 Vault' }}</button></div>
      </form>
    </section>
  </div>

  <div v-if="editOpen" class="dialog-backdrop" @click.self="editOpen = false">
    <section class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="edit-filter-title" @keydown.esc.prevent="editOpen = false">
      <div class="dialog-card__heading"><span class="section-icon"><AppIcon name="filter" :size="18" /></span><button class="demo-icon-button" type="button" aria-label="关闭" @click="editOpen = false"><AppIcon name="close" :size="18" /></button></div>
      <h2 id="edit-filter-title">{{ selectedVault?.name }} · 过滤设置</h2>
      <p class="dialog-card__desc">修改后在下次同步时生效。</p>
      <label class="form-field"><span>排除规则</span><textarea v-model="editForm.exclude" rows="5"></textarea><small>仅配置排除项；未命中的文件都会被索引。</small></label>
      <label class="form-field"><span>单文件大小上限（KB）</span><input v-model.number="editForm.maxKb" type="number" min="0" /></label>
      <div class="dialog-card__actions"><button class="button button--secondary" type="button" @click="editOpen = false">取消</button><button class="button button--primary" type="button" @click="saveFilters">保存过滤</button></div>
    </section>
  </div>

  <div v-if="deleteTarget" class="dialog-backdrop" @click.self="deleteTarget = null">
    <section class="dialog-card dialog-card--compact" role="alertdialog" aria-modal="true" aria-labelledby="delete-vault-title">
      <h2 id="delete-vault-title">删除「{{ deleteTarget.name }}」？</h2>
      <p class="dialog-card__desc">演示中只会从页面列表移除，不会删除真实数据。</p>
      <div class="dialog-card__actions"><button class="button button--secondary" type="button" @click="deleteTarget = null">取消</button><button class="button button--danger" type="button" @click="emit('removeVault', deleteTarget.id); deleteTarget = null">删除 Vault</button></div>
    </section>
  </div>
</template>

<style scoped>
.vault-intro__actions { display: flex; gap: 8px; }
.button { min-height: 38px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 12px; border: 1px solid transparent; border-radius: 9px; font-size: 11px; font-weight: 600; cursor: pointer; }
.button--primary { color: var(--color-primary-contrast); background: var(--ui-primary); }
.button--primary:hover { background: var(--ui-primary-hover); }
.button--secondary { color: var(--ui-text); background: var(--ui-surface); border-color: var(--ui-border); }
.button--secondary:hover, .button--quiet:hover { background: var(--ui-surface-soft); }
.button--quiet, .button--danger-quiet { color: var(--ui-primary); background: transparent; }
.button--danger-quiet { color: var(--ui-danger); }
.button--danger { color: var(--color-danger-contrast); background: var(--ui-danger); }
.vault-page-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; align-items: start; }
.vault-main-column { display: grid; gap: 15px; min-width: 0; }
.section-heading, .files-panel__heading, .files-panel__title, .vault-card__select, .vault-card__stats, .vault-actions { display: flex; align-items: center; }
.section-heading { justify-content: space-between; gap: 10px; margin-bottom: 11px; }
.section-heading h2, .files-panel h2 { color: var(--ui-ink); font-size: 14px; }
.files-panel__title p { margin-top: 3px; color: var(--ui-muted); font-size: 10px; }
.count-chip { padding: 4px 8px; color: var(--ui-muted); background: var(--ui-surface-soft); border-radius: 999px; font-size: 10px; white-space: nowrap; }
.vault-cards { display: grid; grid-template-columns: repeat(auto-fill, 260px); gap: 10px; }
.vault-card { min-width: 0; padding: 12px; border-color: var(--ui-border); }
.vault-card.is-selected { border-color: var(--ui-primary); box-shadow: 0 0 0 2px var(--ui-primary-soft); }
.vault-card__select { width: 100%; gap: 9px; padding: 0; text-align: left; background: transparent; border: 0; cursor: pointer; }
.vault-card__icon, .section-icon { width: 34px; height: 34px; display: grid; flex: none; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 10px; }
.vault-card__copy { display: grid; flex: 1; gap: 3px; min-width: 0; }
.vault-card__copy > strong { overflow: hidden; color: var(--ui-ink); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.vault-card__copy > small { display: flex; align-items: center; gap: 4px; color: var(--ui-muted); font-size: 9px; }
.vault-card__check { width: 20px; height: 20px; display: grid; place-items: center; color: var(--color-primary-contrast); background: var(--ui-primary); border-radius: 50%; }
.vault-card__stats { flex-wrap: wrap; gap: 8px; margin-top: 12px; color: var(--ui-muted); font-size: 9px; }
.vault-card__stats strong { color: var(--ui-ink); }
.vault-card__path { min-width: 0; display: flex; align-items: center; gap: 5px; overflow: hidden; margin-top: 9px; color: var(--ui-muted); font-size: 9px; }
.vault-card__path > :deep(svg) { flex: none; }
.vault-card__path > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-pill { display: inline-flex; align-items: center; gap: 5px; padding: 4px 7px; border-radius: 999px; font-size: 9px; font-weight: 600; white-space: nowrap; }
.status-pill > span { width: 5px; height: 5px; background: currentColor; border-radius: 50%; }
.status-pill--success { color: var(--ui-success); background: var(--color-success-soft); }
.status-pill--running { color: var(--ui-info); background: var(--color-info-soft); }
.status-pill--pending { color: var(--ui-warning); background: var(--color-warning-soft); }
.files-panel { overflow: hidden; padding: 17px 18px 0; }
.files-panel__heading { align-items: stretch; justify-content: space-between; gap: 18px; }
.files-panel__title { flex: 1 1 auto; gap: 9px; align-self: center; }
.files-panel__title h2 { font-size: 13px; }
.file-search { width: 190px; height: 34px; display: flex; flex: none; align-items: center; gap: 6px; padding: 0 9px; color: var(--ui-muted); background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 8px; }
.file-search input { width: 100%; min-width: 0; color: var(--ui-text); background: transparent; border: 0; outline: 0; font-size: 10px; }
.files-panel__meta { display: flex; flex-wrap: wrap; gap: 12px; margin: 13px 0 5px; color: var(--ui-muted); font-size: 9px; }
.files-panel__meta span { display: flex; align-items: center; gap: 5px; }
.files-controls { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 10px 0 4px; }
.file-status-filters { display: flex; flex: 1 1 auto; gap: 5px; overflow-x: auto; min-width: 0; padding-bottom: 4px; scrollbar-width: thin; }
.file-status-filter { min-height: 29px; display: inline-flex; flex: none; align-items: center; gap: 6px; padding: 0 8px; color: var(--ui-muted); background: transparent; border: 1px solid transparent; border-radius: 7px; font-size: 9px; cursor: pointer; }
.file-status-filter:hover { background: var(--ui-surface-soft); }
.file-status-filter.is-active { color: var(--ui-primary); background: var(--ui-primary-soft); border-color: var(--ui-border); }
.file-status-filter__dot, .file-status__dot { width: 6px; height: 6px; flex: none; background: currentColor; border-radius: 50%; }
.file-status-filter__count { color: inherit; opacity: .8; font-variant-numeric: tabular-nums; }
.file-status-filter.is-indexed { color: var(--ui-success); }
.file-status-filter.is-indexing { color: var(--ui-info); }
.file-status-filter.is-pending { color: var(--ui-warning); }
.file-status-filter.is-error { color: var(--ui-danger); }
.file-row { width: 100%; min-height: 54px; display: flex; align-items: center; gap: 9px; padding: 6px 2px; text-align: left; color: var(--ui-muted); background: transparent; border: 0; border-bottom: 1px solid var(--ui-border); cursor: pointer; }
.file-row:hover { background: var(--ui-surface-soft); }
.file-row__icon { width: 30px; height: 33px; display: grid; flex: none; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 8px; }
.file-row__icon.is-pdf { color: var(--ui-danger); background: var(--ui-surface-soft); }
.file-row__name { display: grid; flex: 1; gap: 2px; min-width: 0; }
.file-row__name strong { overflow: hidden; color: var(--ui-ink); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.file-row__name small, .file-row__updated, .file-row__size { color: var(--ui-muted); font-size: 9px; }
.file-row__updated { min-width: 70px; }
.file-row__size { min-width: 43px; text-align: right; }
.file-status { min-width: 68px; display: inline-flex; flex: none; align-items: center; justify-content: center; gap: 5px; padding: 4px 7px; border-radius: 999px; font-size: 8px; font-weight: 600; white-space: nowrap; }
.file-status--indexed { color: var(--ui-success); background: var(--color-success-soft); }
.file-status--indexing { color: var(--ui-info); background: var(--color-info-soft); }
.file-status--pending { color: var(--ui-warning); background: var(--color-warning-soft); }
.file-status--error { color: var(--ui-danger); background: var(--color-danger-soft); }
.file-pagination { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 2px; border-bottom: 1px solid var(--ui-border); color: var(--ui-muted); font-size: 9px; }
.file-pagination__controls { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.file-pagination__controls button { min-height: 30px; display: inline-flex; align-items: center; gap: 4px; padding: 0 7px; color: var(--ui-text); background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 7px; font-size: 9px; cursor: pointer; }
.file-pagination__controls button:hover:not(:disabled) { background: var(--ui-surface-soft); }
.file-pagination__controls button:disabled { color: var(--ui-muted); opacity: .55; cursor: default; }
.file-empty { padding: 25px 8px; color: var(--ui-muted); text-align: center; font-size: 11px; }
.vault-actions { justify-content: flex-start; flex-wrap: wrap; gap: 10px 14px; padding: 10px 0 0; }
.vault-actions__buttons { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.vault-actions__buttons .button { min-height: 32px; padding: 0 8px; font-size: 9px; }
.recent-sync-card { width: min(100%, 410px); min-height: 106px; display: grid; flex: 0 1 410px; align-content: center; gap: 9px; padding: 11px 13px; color: var(--ui-text); background: var(--ui-surface-soft); border: 1px solid var(--ui-border); border-radius: 10px; }
.recent-sync-card__top, .recent-sync-card__title { display: flex; align-items: center; }
.recent-sync-card__top { gap: 9px; }
.recent-sync-card__title { gap: 5px; color: var(--ui-ink); font-size: 9px; font-weight: 700; }
.recent-sync-card__title :deep(svg) { color: var(--ui-primary); }
.recent-sync-card .status-pill { padding: 3px 6px; font-size: 8px; }
.recent-sync-card__percent { margin-left: auto; color: var(--ui-primary); font-size: 12px; font-variant-numeric: tabular-nums; }
.recent-sync-card__track { height: 4px; overflow: hidden; background: var(--ui-border); border-radius: 99px; }
.recent-sync-card__track > span { display: block; height: 100%; background: var(--ui-info); border-radius: inherit; transition: width .3s ease; }
.sync-stages { display: flex; align-items: center; margin: 0; padding: 0; list-style: none; }
.sync-stages li { position: relative; display: flex; flex: 1 1 0; align-items: center; gap: 5px; min-width: 0; color: var(--ui-muted); font-size: 8px; white-space: nowrap; }
.sync-stages li:not(:last-child)::after { height: 1px; flex: 1 1 auto; min-width: 8px; margin: 0 6px; content: ''; background: var(--ui-border); }
.sync-stages__mark { width: 17px; height: 17px; display: grid; flex: none; place-items: center; color: var(--ui-muted); background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 50%; font-size: 8px; }
.sync-stages li.is-done { color: var(--ui-success); }
.sync-stages li.is-done .sync-stages__mark { color: var(--color-success-contrast); background: var(--ui-success); border-color: var(--ui-success); }
.sync-stages li.is-active { color: var(--ui-info); font-weight: 700; }
.sync-stages li.is-active .sync-stages__mark { color: var(--color-info-contrast); background: var(--ui-info); border-color: var(--ui-info); }
.vault-tip { display: flex; align-items: flex-start; gap: 7px; color: var(--ui-muted); font-size: 9px; line-height: 15px; }
.vault-tip :deep(svg) { flex: none; color: var(--ui-primary); }
.privacy-card { display: flex; align-items: center; gap: 9px; padding: 12px; background: var(--ui-surface-soft); border: 1px solid var(--ui-border); border-radius: 10px; }
.privacy-card__mark { color: var(--ui-success); }
.privacy-card strong { color: var(--ui-ink); font-size: 10px; }
.privacy-card p { margin-top: 2px; color: var(--ui-muted); font-size: 9px; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; overflow-y: auto; padding: 20px; background: rgba(15, 35, 60, .4); }
.dialog-card { width: min(100%, 500px); max-height: min(90vh, 780px); overflow-y: auto; padding: 22px; background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 15px; box-shadow: var(--shadow-lg); }
.dialog-card--wide { width: min(100%, 680px); }
.dialog-card--compact { width: min(100%, 420px); }
.dialog-card__heading { display: flex; align-items: center; justify-content: space-between; }
.dialog-card h2 { margin-top: 13px; color: var(--ui-ink); font-size: 18px; }
.dialog-card__desc { margin-top: 5px; color: var(--ui-muted); font-size: 11px; }
.demo-icon-button { width: 34px; height: 34px; display: grid; place-items: center; color: var(--ui-muted); background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
.demo-icon-button:hover { color: var(--ui-primary); background: var(--ui-primary-soft); }
.source-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 18px; }
.source-tabs button { min-height: 40px; display: flex; align-items: center; justify-content: center; gap: 7px; color: var(--ui-text); background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 8px; font-size: 10px; cursor: pointer; }
.source-tabs button.is-active { color: var(--ui-primary); background: var(--ui-primary-soft); border-color: var(--ui-primary); }
.dialog-form { display: grid; gap: 13px; margin-top: 15px; }
.form-field { display: grid; gap: 6px; }
.form-field > span, .form-field__label { color: var(--ui-ink); font-size: 10px; font-weight: 600; }
.form-field input, .form-field textarea { width: 100%; min-height: 38px; padding: 8px 10px; color: var(--ui-text); background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 7px; outline: 0; font-size: 11px; }
.form-field textarea { resize: vertical; font-family: var(--ui-font-mono); line-height: 17px; }
.form-field small, .folder-picker small { color: var(--ui-muted); font-size: 9px; line-height: 14px; }
.folder-picker { display: grid; justify-items: start; gap: 7px; }
.filter-details { padding: 12px; background: var(--ui-surface-soft); border: 1px solid var(--ui-border); border-radius: 9px; }
.filter-details summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; cursor: pointer; list-style: none; }
.filter-details summary::-webkit-details-marker { display: none; }
.filter-details summary > span { display: flex; align-items: center; gap: 7px; color: var(--ui-ink); font-size: 11px; font-weight: 700; }
.filter-details summary > small { color: var(--ui-muted); font-size: 9px; }
.filter-details > p { margin: 7px 0 10px; color: var(--ui-muted); font-size: 9px; }
.filter-tree { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 11px; }
.filter-tree label { display: grid; grid-template-columns: 14px 1fr; align-items: center; gap: 5px; padding: 6px; background: var(--ui-surface); border: 1px solid var(--ui-border); border-radius: 6px; }
.filter-tree input { accent-color: var(--ui-primary); }
.filter-tree label span { color: var(--ui-text); font-size: 9px; }
.filter-tree code { grid-column: 2; overflow: hidden; color: var(--ui-muted); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.form-error { margin: 0; color: var(--ui-danger); font-size: 10px; }
.dialog-card__actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 17px; }
@media (max-width: 650px) {
  .vault-intro__actions { width: 100%; }
  .vault-intro__actions .button { flex: 1; padding: 0 7px; font-size: 9px; }
  .vault-cards { grid-template-columns: minmax(0, 1fr); }
  .file-row__updated, .file-row__size { display: none; }
  .files-panel { padding-right: 12px; padding-left: 12px; }
  .files-panel__heading { flex-direction: column; }
  .files-panel__title { align-self: auto; }
  .files-controls { align-items: stretch; flex-direction: column; }
  .file-status-filters { flex: none; width: 100%; }
  .file-search { width: 100%; }
  .file-pagination { align-items: flex-start; flex-direction: column; }
  .file-pagination__controls { width: 100%; justify-content: space-between; }
  .vault-actions { align-items: stretch; flex-direction: column; }
  .recent-sync-card { width: 100%; flex-basis: auto; }
  .filter-tree { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) { .button, .recent-sync-card__track > span { transition: none; } }
</style>
