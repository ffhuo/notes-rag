<script setup>
// 数据表格（T2.10 / 规范 §4.2）。
//
// 为什么用 div + ARIA role 而不是 <table>：sm 断点要把每行降级成「字段标签 + 值」的
// 卡片列表（规范 §3.4），<table> 的 display 覆盖在各端表现不一致；Flex 布局是
// 跨端可迁移的那一层（规范 §6.1「只用 Flex + 令牌 + 单层类名」）。
//
// 列定义：{ key, label, width?, align?: 'left'|'right', sortable?, mono? }
// 插槽：cell-<key>（{ row, value, index }）/ row-actions（{ row, index }）/ 
//       row-expand（{ row, index }，需 expandable）/ empty
import { computed, ref } from 'vue'
import AppEmptyState from './AppEmptyState.vue'
import AppIcon from './AppIcon.vue'
import AppSkeleton from './AppSkeleton.vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  /** 行唯一键：字段名或 (row) => key。缺省用下标。 */
  rowKey: { type: [String, Function], default: '' },
  /** 是否开启排序（列还需各自 sortable）。 */
  sortable: { type: Boolean, default: false },
  clickable: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无数据' },
  emptyIcon: { type: String, default: 'inbox' },
  /** 行可展开（详情行由 row-expand 插槽提供）。 */
  expandable: { type: Boolean, default: false },
  /** 已展开行的 key 列表（受控）。 */
  expanded: { type: Array, default: () => [] },
})

const emit = defineEmits(['sort', 'row-click', 'toggle-expand'])

const sortKey = ref('')
const sortDir = ref('asc')

function keyOf(row, index) {
  if (typeof props.rowKey === 'function') return props.rowKey(row)
  if (props.rowKey) return row[props.rowKey]
  return index
}

function isExpanded(row, index) {
  return props.expanded.includes(keyOf(row, index))
}

function onRowActivate(row, index) {
  if (props.expandable) emit('toggle-expand', keyOf(row, index))
  if (props.clickable) emit('row-click', row)
}

function toggleSort(col) {
  if (!props.sortable || !col.sortable) return
  if (sortKey.value === col.key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = col.key
    sortDir.value = 'asc'
  }
  emit('sort', { key: sortKey.value, dir: sortDir.value })
}

const sortedRows = computed(() => {
  if (!sortKey.value) return props.rows
  const key = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...props.rows].sort((a, b) => {
    const va = a[key]
    const vb = b[key]
    if (va === vb) return 0
    if (va === null || va === undefined) return 1
    if (vb === null || vb === undefined) return -1
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb)) * dir
  })
})

function colStyle(col) {
  return col.width ? { flex: `0 0 ${col.width}` } : null
}

function cellText(value) {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}
</script>

<template>
  <div class="app-table">
    <div v-if="loading" class="app-table__loading">
      <AppSkeleton variant="list" :count="4" />
    </div>

    <template v-else>
      <div class="app-table__head">
        <div v-if="expandable" class="app-table__th is-expand"></div>
        <div
          v-for="col in columns"
          :key="col.key"
          class="app-table__th"
          :class="[`is-${col.align || 'left'}`, { 'is-sortable': sortable && col.sortable }]"
          :style="colStyle(col)"
          @click="toggleSort(col)"
        >
          <span>{{ col.label }}</span>
          <AppIcon
            v-if="sortable && col.sortable && sortKey === col.key"
            :name="sortDir === 'asc' ? 'chevron-up' : 'chevron-down'"
            :size="14"
          />
        </div>
        <div v-if="$slots['row-actions']" class="app-table__th is-right is-actions">操作</div>
      </div>

      <div v-if="!sortedRows.length" class="app-table__empty">
        <slot name="empty">
          <AppEmptyState size="sm" :icon="emptyIcon" :title="emptyText" />
        </slot>
      </div>

      <template v-for="(row, index) in sortedRows" :key="keyOf(row, index)">
        <div
          class="app-table__row"
          :class="{ 'is-clickable': clickable, 'is-expanded': expandable && isExpanded(row, index) }"
          @click="onRowActivate(row, index)"
        >
          <div
            v-if="expandable"
            class="app-table__td is-expand"
            @click.stop="onRowActivate(row, index)"
          >
            <AppIcon :name="isExpanded(row, index) ? 'chevron-down' : 'chevron-right'" :size="16" />
          </div>
          <div
            v-for="col in columns"
            :key="col.key"
            class="app-table__td"
            :class="[`is-${col.align || 'left'}`, { 'is-mono': col.mono }]"
            :style="colStyle(col)"
          >
            <span class="app-table__cell-label">{{ col.label }}</span>
            <span class="app-table__cell-value">
              <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]" :index="index">
                {{ cellText(row[col.key]) }}
              </slot>
            </span>
          </div>

          <div
            v-if="$slots['row-actions']"
            class="app-table__td is-right is-actions"
            @click.stop
          >
            <slot name="row-actions" :row="row" :index="index" />
          </div>
        </div>

        <div v-if="expandable && isExpanded(row, index)" class="app-table__expand">
          <slot name="row-expand" :row="row" :index="index" />
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.app-table {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-surface);
  overflow: hidden;
}

.app-table__loading {
  padding: var(--space-4);
}

/* ---------- 表头 ---------- */
.app-table__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: none;
  padding: var(--space-2) var(--space-4);
  background: var(--color-bg-subtle);
  border-bottom: var(--border-width) solid var(--color-border);
}

.app-table__th {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex: 1 1 0;
  min-width: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}
.app-table__th.is-sortable {
  cursor: pointer;
  user-select: none;
}
.app-table__th.is-sortable:hover {
  color: var(--color-primary);
}
.app-table__th.is-right {
  justify-content: flex-end;
}
.app-table__th.is-actions {
  flex: 0 0 auto;
}
.app-table__th.is-expand {
  flex: 0 0 20px;
}

/* ---------- 行 ---------- */
.app-table__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: var(--border-width) solid var(--color-border);
  transition: background-color var(--duration-fast) var(--ease-standard);
}
.app-table__row:last-child {
  border-bottom: none;
}
.app-table__row.is-clickable {
  cursor: pointer;
}
.app-table__row:hover {
  background: var(--color-bg-subtle);
}

.app-table__td {
  display: flex;
  align-items: center;
  flex: 1 1 0;
  min-width: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}
.app-table__td.is-right {
  justify-content: flex-end;
}
.app-table__td.is-mono {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-code);
}
.app-table__td.is-actions {
  flex: 0 0 auto;
  justify-content: flex-end;
  gap: var(--space-1);
}
.app-table__td.is-expand {
  flex: 0 0 20px;
  justify-content: flex-start;
  color: var(--color-text-muted);
}

/* 展开详情面板：横跨整行，与行同样式分隔 */
.app-table__expand {
  padding: var(--space-3) var(--space-4);
  border-bottom: var(--border-width) solid var(--color-border);
  background: var(--color-bg-subtle);
}

.app-table__cell-value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 字段标签只在 sm 断点的卡片形态下出现 */
.app-table__cell-label {
  display: none;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.app-table__empty {
  border-top: none;
}

/* ---------- sm：降级为卡片列表（规范 §3.4，不做横向滚动） ---------- */
@media (max-width: 767px) {
  .app-table {
    border: none;
    border-radius: 0;
    background: transparent;
    gap: var(--space-3);
  }
  .app-table__head {
    display: none;
  }
  .app-table__row {
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-2);
    padding: var(--space-3);
    border: var(--border-width) solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-bg-surface);
  }
  .app-table__td {
    justify-content: space-between;
    gap: var(--space-3);
    flex: none;
  }
  .app-table__td.is-right,
  .app-table__td.is-actions {
    justify-content: flex-end;
  }
  /* sm：整行都可点击触发展开，展开格退化为右上角的方向指示 */
  .app-table__td.is-expand {
    flex: none;
    justify-content: flex-end;
  }
  .app-table__expand {
    padding: var(--space-3);
    border: var(--border-width) solid var(--color-border);
    border-radius: var(--radius-lg);
  }
  .app-table__cell-label {
    display: block;
  }
  .app-table__cell-value {
    text-align: right;
  }
}
</style>
