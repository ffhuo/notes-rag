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
    <header class="page-intro">
      <div>
        <div class="eyebrow"><span class="eyebrow__dot"></span> FIND NOTES BY MEANING</div>
        <h1>用意思，找到笔记</h1>
        <p>语义检索不要求与原文用词一致，命中结果附带相关度和出处。</p>
      </div>
      <span class="search-demo-label"><AppIcon name="search" :size="14" />语义检索</span>
    </header>

    <div class="search__bar panel">
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
      <div class="search-hint">
        <AppIcon name="info" :size="14" />
        检索范围：{{ vaults.find((vault) => String(vault.id) === vaultId)?.name || '选择 Vault' }}
        <span>·</span>返回 {{ topK }} 条以内
      </div>
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
      <div class="search-results-heading">
        <div><h2>检索结果</h2><p>{{ hitCountText }}</p></div>
        <span class="demo-result-tag">真实索引结果</span>
      </div>

      <div class="search__hits">
        <AppCard
          v-for="(h, i) in hits"
          :key="`${h.note_id}-${i}`"
          padding="sm"
          class="panel search-result"
          :class="`search-result--${['blue', 'teal', 'amber'][i % 3]}`"
        >
          <div class="search-result__heading">
            <span class="search-result__number">{{ String(i + 1).padStart(2, '0') }}</span>
            <div class="search-result__title">
              <h3 :title="h.title">{{ h.title || '（无标题）' }}</h3>
              <span :title="h.file_path"><AppIcon name="file-text" :size="13" />{{ h.file_path }}</span>
            </div>
            <span class="search-score">
              <strong>{{ Number(h.rerank_score ?? h.score).toFixed(3) }}</strong>
              <small>{{ h.rerank_score != null ? '精排分' : '向量分' }}</small>
              <small v-if="h.rerank_score != null" class="search-score__vector">
                向量 {{ Number(h.score).toFixed(3) }}
              </small>
            </span>
          </div>

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

          <button
            v-if="overflow[i]"
            class="search-result__expand"
            type="button"
            :aria-expanded="!!expanded[i]"
            @click="toggleContent(i)"
          >
            {{ expanded[i] ? '收起片段' : '展开片段' }}
            <AppIcon :name="expanded[i] ? 'chevron-up' : 'chevron-down'" :size="14" />
          </button>
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

.search-demo-label,
.demo-result-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 9px;
  color: var(--ui-primary);
  background: var(--ui-primary-soft);
  border-radius: 999px;
  font-size: 9px;
  white-space: nowrap;
}

.search__bar {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) minmax(145px, 190px) minmax(90px, 120px) auto;
  gap: 10px;
  padding: 16px;
}

.search__bar > :deep(.search__input) {
  width: 100%;
}

.search-hint {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ui-muted);
  font-size: 9px;
}

.search-hint :deep(svg) {
  color: var(--ui-primary);
}

.search-results-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 3px 0 -7px;
}

.search-results-heading h2 {
  color: var(--ui-ink);
  font-size: 13px;
}

.search-results-heading p {
  margin-top: 3px;
  color: var(--ui-muted);
  font-size: 9px;
}

.search__hits {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.search-result {
  padding: 0;
  border-left: 3px solid var(--ui-primary);
}

.search-result--teal {
  border-left-color: var(--ui-success);
}

.search-result--amber {
  border-left-color: var(--ui-warning);
}

.search-result :deep(.app-card__body) {
  gap: 10px;
}

.search-result__heading {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.search-result__number {
  width: 26px;
  height: 26px;
  display: grid;
  flex: none;
  place-items: center;
  color: var(--ui-primary);
  background: var(--ui-primary-soft);
  border-radius: 7px;
  font-size: 9px;
  font-weight: 700;
}

.search-result--teal .search-result__number {
  color: var(--ui-success);
  background: var(--ui-surface-soft);
}

.search-result--amber .search-result__number {
  color: var(--ui-warning);
  background: var(--ui-surface-soft);
}

.search-result__title {
  flex: 1;
  min-width: 0;
}

.search-result__title h3 {
  overflow: hidden;
  color: var(--ui-ink);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-result__title > span {
  display: flex;
  align-items: center;
  gap: 5px;
  overflow: hidden;
  margin-top: 4px;
  color: var(--ui-muted);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-score {
  display: grid;
  flex: none;
  justify-items: end;
}

.search-score strong {
  color: var(--ui-primary);
  font-family: var(--font-family-mono);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}

.search-score small {
  color: var(--ui-muted);
  font-size: 8px;
}

.search-score .search-score__vector {
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}

.search-result__expand {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  align-self: flex-start;
  padding: 0;
  color: var(--ui-primary);
  background: transparent;
  border: 0;
  font-size: 9px;
  cursor: pointer;
}

@media (max-width: 767px) {
  .search__vault,
  .search__topk {
    flex: 1 1 0;
    width: auto;
  }

  .search__bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .search__bar > :deep(.search__input) {
    grid-column: 1 / -1;
  }

  .search__bar > :deep(button) {
    width: 100%;
  }
}
</style>
