<script setup>
// 检索页（T3.4 / 规范 §5.3）—— 向量检索命中列表。
//
// 检索必须绑定 vault：向量集合按 (vault_id, embedding 模型) 隔离，脱离 vault 无法确定
// 查哪个集合、用哪个 embedding（§18.2），所以 vault 是必选项而不是可选项。
//
// 三种页面状态必须分开表达（规范 §1「空态有指引」）：
//   · 未查询   → 告诉用户输入什么、要先选 vault
//   · 查询中   → 结果骨架屏（禁止整页 spinner）
//   · 无命中   → 给出可执行的下一步，而不是一片空白
//
// 命中片段按**文件格式**还原：markdown 交给 AppMarkdown 渲染排版，其余按纯文本原样
// 显示 —— 否则 .md 笔记会把 `##`、`**` 这些标记直接糊在界面上。
import { computed, nextTick, onMounted, ref } from 'vue'
import { apiFetch, vaultsApi } from '../api'
import { imageMarkersToText, isMarkdownPath } from '../markdown'
import { toast } from '../toast'
import AppButton from './AppButton.vue'
import AppCard from './AppCard.vue'
import AppEmptyState from './AppEmptyState.vue'
import AppIcon from './AppIcon.vue'
import AppInput from './AppInput.vue'
import AppMarkdown from './AppMarkdown.vue'
import AppProgress from './AppProgress.vue'
import AppSelect from './AppSelect.vue'
import AppSkeleton from './AppSkeleton.vue'

const TOPK_OPTIONS = [
  { value: '3', label: 'Top-K 3' },
  { value: '5', label: 'Top-K 5' },
  { value: '10', label: 'Top-K 10' },
  { value: '20', label: 'Top-K 20' },
]

const query = ref('')
const vaultId = ref('')
const topK = ref('5')

const hits = ref([])
const searched = ref(false)
const loading = ref(false)
const error = ref('')

const vaults = ref([])

// 片段折叠：先用 CSS 限高 3 行，再测量是否真的溢出决定要不要给「展开」
const contentEls = ref([])
const overflow = ref({})
const expanded = ref({})

const vaultOptions = computed(() => vaults.value.map((v) => ({ value: String(v.id), label: v.name })))

const canSearch = computed(() => !!query.value.trim() && !!vaultId.value && !loading.value)

const hitCountText = computed(() => `命中 ${hits.value.length} 条`)

onMounted(async () => {
  try {
    vaults.value = await vaultsApi.list()
    // 只有一个 vault 时直接选中，少一步操作
    if (vaults.value.length === 1) vaultId.value = String(vaults.value[0].id)
  } catch (e) {
    error.value = `无法获取 vault 列表：${e.message}`
  }
})

function bindContent(el, i) {
  contentEls.value[i] = el || null
}

/** 限高是 CSS 决定的，是否溢出只能渲染后测量（测一次即可，展开态不再重测）。 */
async function measureOverflow() {
  await nextTick()
  const next = {}
  contentEls.value.forEach((el, i) => {
    if (el) next[i] = el.scrollHeight > el.clientHeight + 2
  })
  overflow.value = next
}

function toggleContent(i) {
  expanded.value = { ...expanded.value, [i]: !expanded.value[i] }
}

async function search() {
  if (!canSearch.value) return
  error.value = ''
  loading.value = true
  hits.value = []
  expanded.value = {}
  overflow.value = {}
  contentEls.value = []
  try {
    const res = await apiFetch('/search', {
      method: 'POST',
      body: JSON.stringify({
        query: query.value.trim(),
        top_k: Number(topK.value),
        threshold: 0.0,
        vault_id: vaultId.value,
      }),
    })
    hits.value = res?.hits || []
    searched.value = true
  } catch (e) {
    if (e.status === 409) {
      // 该 vault 还没有可用索引：说清下一步，而不是抛原始报错
      error.value = '该 vault 还没有可检索的索引，请先到知识库页同步或重建索引。'
    } else if (e.status === 422) {
      error.value = '请求不合法：请检查查询词与 vault 选择。'
    } else {
      error.value = `检索失败：${e.message}`
    }
    toast.error('检索未能完成')
  } finally {
    loading.value = false
  }
  // 骨架屏退场后才真正渲染出结果，测量必须在 loading 落地之后
  if (hits.value.length) await measureOverflow()
}

function resetSearch() {
  query.value = ''
  hits.value = []
  searched.value = false
  overflow.value = {}
  expanded.value = {}
  error.value = ''
}
</script>

<template>
  <section class="search">
    <header class="search__intro">
      <h2 class="search__title">检索</h2>
      <p class="search__desc">
        语义检索：按意思找，不必与原文用词一致。结果按相似度排序，附出处与片段。
      </p>
    </header>

    <div class="search__bar">
      <AppInput
        v-model="query"
        class="search__input"
        placeholder="用一句话描述你要找的内容，例如「上次讨论的索引重建策略」"
        aria-label="查询内容"
        @enter="search"
      >
        <template #prefix><AppIcon name="search" :size="16" /></template>
      </AppInput>
      <AppSelect
        v-model="vaultId"
        class="search__vault"
        empty-label="选择 vault"
        :options="vaultOptions"
        aria-label="选择 vault"
      />
      <AppSelect
        v-model="topK"
        class="search__topk"
        :options="TOPK_OPTIONS"
        aria-label="返回条数"
      />
      <AppButton variant="primary" icon="search" :loading="loading" :disabled="!canSearch" @click="search">
        检索
      </AppButton>
    </div>

    <p v-if="error" class="search__alert">
      <AppIcon name="alert" :size="16" />
      <span>{{ error }}</span>
    </p>

    <!-- 加载：结果骨架屏 -->
    <AppSkeleton v-if="loading" variant="list" :count="3" />

    <!-- 未查询 -->
    <AppEmptyState
      v-else-if="!searched"
      icon="search"
      title="还没有开始检索"
      description="选择 vault、输入查询词后回车或点「检索」。检索只在该 vault 的索引范围内进行。"
    />

    <!-- 无命中 -->
    <AppEmptyState
      v-else-if="!hits.length"
      icon="inbox"
      title="没有命中"
      description="试试用更贴近笔记原文的说法，或把 Top-K 调大；若该 vault 刚建好，请确认索引已完成。"
      action-text="清空重来"
      action-icon="refresh"
      @action="resetSearch"
    />

    <template v-else>
      <p class="search__count">{{ hitCountText }}</p>

      <div class="search__hits">
        <AppCard v-for="(h, i) in hits" :key="`${h.note_id}-${i}`" padding="sm">
          <span class="search__hit-head">
            <span class="search__hit-title" :title="h.title">{{ h.title || '（无标题）' }}</span>
            <span class="search__score">{{ h.score.toFixed(3) }}</span>
          </span>

          <span class="search__hit-path" :title="h.file_path">
            <AppIcon name="file-text" :size="14" />
            <span class="search__hit-path-text">{{ h.file_path }}</span>
          </span>

          <!-- score 相对长度条（等宽数字 + 长度双编码） -->
          <AppProgress :value="Math.max(0, h.score)" :max="1" compact hide-meta />

          <!-- 按文件格式还原：markdown 走渲染，其余按纯文本原样显示（见 markdown.js） -->
          <div
            :ref="(el) => bindContent(el, i)"
            class="search__hit-content"
            :class="{
              'is-clamped': !expanded[i] && overflow[i],
              'search__hit-content--plain': !isMarkdownPath(h.file_path),
            }"
          >
            <AppMarkdown v-if="isMarkdownPath(h.file_path)" :source="h.content" :images="h.images" />
            <template v-else>{{ imageMarkersToText(h.content, h.images, false) }}</template>
          </div>

          <AppButton
            v-if="overflow[i]"
            variant="ghost"
            size="sm"
            :icon="expanded[i] ? 'chevron-up' : 'chevron-down'"
            @click="toggleContent(i)"
          >
            {{ expanded[i] ? '收起' : '展开全文' }}
          </AppButton>
        </AppCard>
      </div>
    </template>
  </section>
</template>

<style scoped>
.search {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.search__title {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-h1);
  line-height: var(--line-height-h1);
  font-weight: var(--font-weight-semibold);
}

.search__desc {
  margin: var(--space-1) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

/* ---------- 检索栏 ---------- */
.search__bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.search__input {
  flex: 1 1 260px;
  min-width: 0;
}

.search__vault {
  width: 180px;
}

.search__topk {
  width: 130px;
}

/* ---------- 提示 ---------- */
.search__alert {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: var(--border-width) solid var(--color-border);
  border-left-width: 3px;
  border-left-color: var(--color-danger);
  border-radius: var(--radius-md);
  background: var(--color-bg-surface);
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.search__count {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

/* ---------- 命中列表 ---------- */
.search__hits {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.search__hit-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
  min-width: 0;
}

.search__hit-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-primary);
  font-size: var(--font-size-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--font-weight-semibold);
}

.search__score {
  flex: none;
  color: var(--color-primary);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-code);
  line-height: var(--line-height-code);
  font-variant-numeric: tabular-nums;
}

.search__hit-path {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.search__hit-path-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-family-mono);
}

.search__hit-content {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  word-break: break-word;
}
/* 纯文本分支要保留原文换行；markdown 分支由 AppMarkdown 排版，不能带 pre-wrap */
.search__hit-content--plain {
  white-space: pre-wrap;
}
/* 最多 3 行，超出由「展开全文」放开（限高用行高令牌换算，不写死像素） */
.search__hit-content.is-clamped {
  max-height: calc(var(--line-height-body) * 3);
  overflow: hidden;
}

@media (max-width: 767px) {
  .search__vault,
  .search__topk {
    flex: 1 1 0;
    width: auto;
  }
}
</style>
