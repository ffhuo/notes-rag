<script setup>
import { computed, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'

const props = defineProps({
  vaults: { type: Array, required: true },
  selectedVaultId: { type: Number, required: true },
})
const emit = defineEmits(['notify'])

const query = ref('WAL 预写日志')
const vaultId = ref(String(props.selectedVaultId))
const topK = ref('5')
const searched = ref(true)
const expanded = ref({})

const matches = [
  { id: 'storage', title: 'WAL 预写日志原理与落盘机制', path: '工程笔记 / 数据库 / 存储基础.md', score: '0.924', color: 'blue', content: 'WAL（Write-Ahead Logging，预写日志）是一种持久化方案，核心规则是先写日志，再落盘数据。系统崩溃后可以通过日志回放恢复状态。' },
  { id: 'vector', title: '本地向量库的 WAL 回放策略', path: '工程笔记 / RAG / 向量库设计.md', score: '0.861', color: 'teal', content: '写入向量库前先记录变更日志；检查点完成后，过期日志可以安全清理。启动时回放未完成的操作，保证本地索引一致。' },
  { id: 'db', title: 'SQLite 事务与检查点', path: '项目资料 / sqlite-notes.md', score: '0.782', color: 'amber', content: '检查点会把 WAL 中已提交的数据同步到数据库文件，并允许回收已处理的日志页。' },
]

const hasPresetResults = computed(() => /wal|预写|日志/i.test(query.value))
const visibleMatches = computed(() => matches.slice(0, Number(topK.value)))

function runSearch() {
  if (!query.value.trim()) return
  searched.value = true
  if (hasPresetResults.value) emit('notify', '显示 WAL 主题的预置检索结果')
}
</script>

<template>
  <div class="page-intro">
    <div><div class="eyebrow"><span class="eyebrow__dot"></span> FIND NOTES BY MEANING</div><h1>用意思，找到笔记</h1><p>语义检索不要求与原文用词一致，命中结果附带相关度和出处。</p></div>
    <span class="search-demo-label"><AppIcon name="search" :size="14" />语义检索</span>
  </div>

  <section class="panel search-panel">
    <form class="search-form" @submit.prevent="runSearch">
      <label class="search-query"><AppIcon name="search" :size="18" /><input v-model="query" aria-label="检索内容" placeholder="描述你要找的内容…" /></label>
      <label class="search-select"><span>Vault</span><select v-model="vaultId"><option v-for="vault in vaults" :key="vault.id" :value="String(vault.id)">{{ vault.name }}</option></select></label>
      <label class="search-select search-select--topk"><span>Top-K</span><select v-model="topK"><option value="3">3 条</option><option value="5">5 条</option><option value="10">10 条</option><option value="20">20 条</option></select></label>
      <button class="button button--primary" type="submit" :disabled="!query.trim()"><AppIcon name="search" :size="16" />检索</button>
    </form>
    <div class="search-hint"><AppIcon name="info" :size="14" />检索范围：{{ vaults.find((vault) => String(vault.id) === vaultId)?.name || '选择 Vault' }}<span>·</span>返回 {{ topK }} 条以内</div>
  </section>

  <div v-if="searched && hasPresetResults" class="search-results-heading"><div><h2>检索结果</h2><p>找到 {{ visibleMatches.length }} 条相关内容</p></div><span class="demo-result-tag">预置演示结果</span></div>
  <div v-if="searched && hasPresetResults" class="search-results">
    <article v-for="(item, index) in visibleMatches" :key="item.id" class="panel search-result" :class="`search-result--${item.color}`">
      <div class="search-result__heading"><span class="search-result__number">{{ String(index + 1).padStart(2, '0') }}</span><div class="search-result__title"><h3>{{ item.title }}</h3><span><AppIcon name="file-text" :size="13" />{{ item.path }}</span></div><span class="search-score"><strong>{{ item.score }}</strong><small>相关度</small></span></div>
      <p class="search-result__excerpt" :class="{ 'is-expanded': expanded[item.id] }">{{ item.content }}</p>
      <button class="search-result__expand" type="button" :aria-expanded="!!expanded[item.id]" @click="expanded = { ...expanded, [item.id]: !expanded[item.id] }">{{ expanded[item.id] ? '收起片段' : '展开片段' }}<AppIcon :name="expanded[item.id] ? 'chevron-up' : 'chevron-down'" :size="14" /></button>
    </article>
  </div>
  <section v-else-if="searched" class="panel search-empty"><span><AppIcon name="search" :size="22" /></span><h2>这次查询没有预置结果</h2><p>该页面仅演示 WAL 示例结果，不会连接真实向量索引。</p><button class="button button--secondary" type="button" @click="query = 'WAL 预写日志'; runSearch()">查看 WAL 示例</button></section>
  <section v-else class="panel search-empty"><span><AppIcon name="search" :size="22" /></span><h2>开始一次语义检索</h2><p>选择 Vault，输入查询词后按回车或点击检索。</p></section>
</template>

<style scoped>
.search-demo-label, .demo-result-tag { display: inline-flex; align-items: center; gap: 6px; padding: 6px 9px; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 999px; font-size: 9px; }
.panel { padding: 17px; }
.search-form { display: flex; align-items: center; gap: 9px; }
.search-query { min-height: 42px; display: flex; align-items: center; gap: 9px; flex: 1; min-width: 150px; padding: 0 11px; color: var(--ui-primary); border: 1px solid var(--ui-border); border-radius: 9px; }
.search-query:focus-within { border-color: var(--ui-primary); box-shadow: 0 0 0 3px var(--ui-primary-soft); }
.search-query input { width: 100%; min-width: 0; color: var(--ui-ink); background: transparent; border: 0; outline: 0; font-size: 11px; }
.search-query input::placeholder { color: var(--ui-muted); }
.search-select { min-width: 155px; display: grid; gap: 2px; padding: 0 9px; border-left: 1px solid var(--ui-border); }
.search-select span { color: var(--ui-muted); font-size: 8px; }
.search-select select { width: 100%; color: var(--ui-ink); background: transparent; border: 0; outline: 0; font-size: 10px; }
.search-select--topk { min-width: 92px; }
.button { min-height: 39px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 0 13px; border: 1px solid var(--ui-border); border-radius: 8px; font-size: 10px; font-weight: 600; cursor: pointer; }
.button--primary { color: var(--color-primary-contrast); background: var(--ui-primary); border-color: var(--ui-primary); }
.button--primary:hover { background: var(--ui-primary-hover); }
.button--primary:disabled { opacity: .5; cursor: not-allowed; }
.button--secondary { color: var(--ui-text); background: var(--ui-surface); }
.search-hint { display: flex; align-items: center; gap: 6px; margin-top: 12px; color: var(--ui-muted); font-size: 9px; }
.search-results-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 21px 0 10px; }
.search-results-heading h2 { color: var(--ui-ink); font-size: 13px; }
.search-results-heading p { margin-top: 3px; color: var(--ui-muted); font-size: 9px; }
.search-results { display: grid; gap: 10px; }
.search-result { padding: 14px 16px; border-left: 3px solid var(--ui-primary); }
.search-result--teal { border-left-color: var(--ui-success); }
.search-result--amber { border-left-color: var(--ui-warning); }
.search-result__heading { display: flex; align-items: center; gap: 10px; }
.search-result__number { width: 26px; height: 26px; display: grid; flex: none; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 7px; font-size: 9px; font-weight: 700; }
.search-result--teal .search-result__number { color: var(--ui-success); background: var(--ui-surface-soft); }
.search-result--amber .search-result__number { color: var(--ui-warning); background: var(--ui-surface-soft); }
.search-result__title { flex: 1; min-width: 0; }
.search-result__title h3 { overflow: hidden; color: var(--ui-ink); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.search-result__title > span { display: flex; align-items: center; gap: 5px; overflow: hidden; margin-top: 4px; color: var(--ui-muted); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.search-score { display: grid; justify-items: end; gap: 1px; }
.search-score strong { color: var(--ui-primary); font-family: var(--ui-font-mono); font-size: 13px; }
.search-score small { color: var(--ui-muted); font-size: 8px; }
.search-result--teal .search-score strong { color: var(--ui-success); }
.search-result--amber .search-score strong { color: var(--ui-warning); }
.search-result__excerpt { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; margin: 12px 0 0 36px; color: var(--ui-text); font-size: 10px; line-height: 17px; }
.search-result__excerpt.is-expanded { display: block; }
.search-result__expand { display: flex; align-items: center; gap: 4px; margin: 5px 0 0 36px; padding: 0; color: var(--ui-primary); background: transparent; border: 0; font-size: 9px; cursor: pointer; }
.search-empty { display: grid; justify-items: center; gap: 7px; margin-top: 20px; padding: 36px 15px; text-align: center; }
.search-empty > span { width: 42px; height: 42px; display: grid; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 13px; }
.search-empty h2 { color: var(--ui-ink); font-size: 12px; }
.search-empty p { color: var(--ui-muted); font-size: 9px; }
.search-empty .button { margin-top: 6px; }
@media (max-width: 760px) {
  .search-form { align-items: stretch; flex-wrap: wrap; }
  .search-query { flex-basis: 100%; }
  .search-select { flex: 1; min-width: 120px; }
  .search-select--topk { min-width: 80px; }
}
</style>
