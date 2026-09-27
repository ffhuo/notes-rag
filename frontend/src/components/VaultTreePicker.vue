<script setup>
// 目录树选择器 —— 勾选文件夹即「排除该文件夹及其子目录」。
//
// 勾选结果写入 filters.exclude，形如 `notes/private/**`（相对 vault 根的 POSIX glob），
// 后端同步时按目录前缀剪枝，整棵子树既不遍历也不入库（见 sync_service._exclude_dir_prefixes）。
//
// 两种数据来源，同一套 UI：
//  1) root —— 服务端某个可读目录（建库后改过滤、服务器目录建库前都用它）。真实笔记目录
//     可能很深，一次拉全树既慢又没意义，所以懒加载：展开哪个节点才请求哪个
//     （GET /vaults/browse 只返回目录、不返回文件）。
//  2) localDirs —— 上传前浏览器自己算出的目录树。用户选完文件夹其实已经拿到了全部
//     路径（webkitdirectory 给每个 File 带 webkitRelativePath），没必要非等解压完才能
//     预览 —— 那样「选完文件却看不到目录」还以为坏了。
//
// 为什么用「扁平可见行」而非递归组件：状态集中在一处、渲染不嵌套，
// 换端（小程序）时也无需找递归组件的替代写法。
import { computed, ref, watch } from 'vue'
import { vaultsApi } from '../api'
import AppButton from './AppButton.vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  /** 服务端浏览根目录（绝对路径）。与 localDirs 二选一，都有时以 localDirs 为准。 */
  root: { type: String, default: '' },
  /** 本地已知的目录树，形如 `{ notes: { private: {} } }`；层级完整，无需请求后端。 */
  localDirs: { type: Object, default: null },
  /** 当前 filters.exclude（glob 列表）；本组件只增删 `<目录>/**` 这一种形态。 */
  selected: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:selected'])

const open = ref(false)
const nodes = ref({})      // rel → { name, rel, has_children }
const kids = ref({})       // rel → 子目录 rel 列表（有值即表示该层已加载）
const expanded = ref({})   // rel → 是否展开
const loading = ref({})    // rel → 是否正在拉这一层
const error = ref('')

const selectedSet = computed(() => new Set(props.selected))

/** 目录 → 排除规则（尾随 /**，与后端剪枝约定一致）。 */
function globOf(rel) {
  return `${rel}/**`
}

/** 扁平化「当前可见」的行：只包含已展开路径上的节点，带好缩进层级与勾选态。 */
const rows = computed(() => {
  const out = []
  const walk = (rel, depth, covered) => {
    for (const key of kids.value[rel] || []) {
      const node = nodes.value[key]
      const glob = globOf(key)
      const on = selectedSet.value.has(glob)
      out.push({
        ...node,
        depth,
        glob,
        on,
        covered,                                   // 上级已排除 → 本级无需再勾
        expanded: !!expanded.value[key],
        busy: !!loading.value[key],
      })
      if (expanded.value[key]) walk(key, depth + 1, covered || on)
    }
  }
  walk('', 0, false)
  return out
})

function reset() {
  nodes.value = {}
  kids.value = {}
  expanded.value = {}
  loading.value = {}
  error.value = ''
  if (props.localDirs) {
    const flat = flattenLocal(props.localDirs)
    nodes.value = flat.nodes
    kids.value = flat.kids
    return
  }
  load('')
}

/** 有无可用数据源：本地树（选好文件夹即有）或服务端可读目录。都没有 → 按钮禁用。 */
const ready = computed(() => !!props.localDirs || !!props.root)

/**
 * 本地嵌套目录树 → 与懒加载同形的 nodes / kids（层级已全知，一次填满）。
 *
 * 隐藏目录与 __MACOSX 在这里就跳过：前者服务端 `_list_subdirs` 不列，后者打包时会被丢，
 * 不跳过就会出现「本地树里有、上传后树里没有」这种对不上的情况。
 */
function flattenLocal(tree) {
  const nodes = {}
  const kids = {}
  const visible = (obj) => Object.keys(obj || {}).filter((n) => !n.startsWith('.') && n !== '__MACOSX')
  const walk = (prefix, obj) => {
    const names = visible(obj)
    kids[prefix] = names.map((n) => (prefix ? `${prefix}/${n}` : n))
    for (const name of names) {
      const rel = prefix ? `${prefix}/${name}` : name
      const sub = obj[name] || {}
      nodes[rel] = { name, rel, has_children: visible(sub).length > 0 }
      walk(rel, sub)
    }
  }
  walk('', tree || {})
  return { nodes, kids }
}

async function load(rel) {
  if (kids.value[rel] || loading.value[rel]) return
  loading.value = { ...loading.value, [rel]: true }
  error.value = ''
  try {
    const res = await vaultsApi.browse(props.root, rel)
    for (const e of res.entries) nodes.value[e.rel] = e
    kids.value = { ...kids.value, [rel]: res.entries.map((e) => e.rel) }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = { ...loading.value, [rel]: false }
  }
}

function toggleExpand(row) {
  const next = !expanded.value[row.rel]
  expanded.value = { ...expanded.value, [row.rel]: next }
  if (next) load(row.rel)
}

function toggleDir(row) {
  if (row.covered) return
  if (row.on) {
    emit('update:selected', props.selected.filter((g) => g !== row.glob))
    return
  }
  // 勾中父目录：顺手删掉它子孙目录的冗余规则（祖先已覆盖，留着只会让清单变脏）
  const prefix = `${row.rel}/`
  const kept = props.selected.filter((g) => !g.startsWith(prefix))
  emit('update:selected', [...kept, row.glob])
}

function toggleOpen() {
  open.value = !open.value
  if (open.value && ready.value) reset()
}

// 数据源变了（用户重选文件夹 / 改了路径输入框）→ 树作废重拉
watch(
  () => [props.root, props.localDirs],
  () => {
    if (open.value && ready.value) reset()
  },
)

/** 缩进用令牌计算，避免在模板里写死间距值。 */
function indentStyle(depth) {
  return { paddingLeft: `calc(var(--space-2) + ${depth} * var(--space-4))` }
}
</script>

<template>
  <div class="picker">
    <div class="picker__bar">
      <AppButton variant="secondary" size="sm" icon="folder" :disabled="!ready" @click="toggleOpen">
        {{ open ? '收起目录树' : '浏览目录' }}
      </AppButton>
      <span class="picker__tip">
        {{ ready ? '勾选文件夹 = 排除它及其下全部内容' : '需要先有目录：服务器目录填好路径 / 上传先选择文件夹' }}
      </span>
    </div>

    <div v-if="open" class="picker__panel">
      <p v-if="localDirs" class="picker__root">根目录：所选文件夹（上传前预览）</p>
      <p v-else class="picker__root" :title="root">根目录：{{ root }}</p>

      <p v-if="error" class="picker__error">
        <AppIcon name="alert" :size="14" />
        <span>{{ error }}</span>
      </p>
      <p v-else-if="!rows.length && !loading['']" class="picker__empty">
        {{
          localDirs
            ? '所选文件夹下没有可勾选的子文件夹（隐藏目录不列出）'
            : '该目录下没有可勾选的子文件夹（只列目录，隐藏目录与文件不列出）'
        }}
      </p>

      <ul class="picker__tree" role="tree" aria-label="目录树">
        <li
          v-for="r in rows"
          :key="r.rel"
          class="picker__row"
          role="treeitem"
          :aria-level="r.depth + 1"
          :aria-expanded="r.has_children ? String(r.expanded) : undefined"
        >
          <button
            v-if="r.has_children"
            type="button"
            class="picker__twisty"
            :aria-label="`${r.expanded ? '收起' : '展开'} ${r.name}`"
            @click="toggleExpand(r)"
          >
            <AppIcon :name="r.busy ? 'loader' : (r.expanded ? 'chevron-down' : 'chevron-right')" :size="14" />
          </button>
          <span v-else class="picker__twisty" aria-hidden="true"></span>

          <button
            type="button"
            class="picker__label"
            :class="{ 'is-on': r.on, 'is-covered': r.covered }"
            :style="indentStyle(r.depth)"
            :disabled="r.covered"
            :aria-pressed="String(r.on)"
            @click="toggleDir(r)"
          >
            <AppIcon :name="r.on ? 'close' : 'folder'" :size="16" :class="{ 'picker__mark': r.on }" />
            <span class="picker__name" :title="r.rel">{{ r.name }}</span>
            <span v-if="r.covered" class="picker__covered">上级已排除</span>
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
}

.picker__bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  min-width: 0;
}

.picker__tip {
  min-width: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.picker__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 260px;
  padding: var(--space-2) var(--space-3);
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-subtle);
  overflow-y: auto;
}

.picker__root {
  margin: 0;
  overflow: hidden;
  color: var(--color-text-muted);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.picker__empty {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.picker__error {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  margin: 0;
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.picker__tree {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.picker__row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
}

.picker__twisty {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}
.picker__twisty:hover {
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
}

.picker__label {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  gap: var(--space-2);
  min-width: 0;
  height: 28px;
  padding: 0 var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: inherit;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  text-align: left;
  cursor: pointer;
}
.picker__label:hover {
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
}
.picker__label.is-on {
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
}
.picker__label.is-covered {
  color: var(--color-text-muted);
  cursor: default;
}
.picker__label.is-covered:hover {
  background: transparent;
  color: var(--color-text-muted);
}

/* 选中 = 已排除：用红叉而不是对勾 —— 这个动作是「不要它」，不是「要它」 */
.picker__mark {
  color: var(--color-danger);
}

.picker__name {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.picker__covered {
  flex: none;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}
</style>
