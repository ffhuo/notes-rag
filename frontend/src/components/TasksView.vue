<script setup>
// 任务与进度页（/tasks）—— 异步作业的前端主视图（M07 §5.4）。
//
// 为什么必须有这一页：后端所有写入类操作都返回 202 + run_id（M03 §5.13），
// 若前端只弹一个 toast，用户点完「重建索引」后 10 分钟不知道发生了什么。
//
// 本页职责：
//   - 聚合全部 vault 的作业，「运行中置顶」+ 历史
//   - 按 vault / 状态筛选
//   - 轮询进度（只在有运行中作业时轮询，全部终态后**停表**，不空转）
//   - 展开详情：计划快照（dry_run）/ 失败清单 / 护栏原因 / 错误
//   - 取消作业（协作式：在文件边界生效，所以不是瞬时）
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { vaultsApi } from '../api'
import { countsSummary, isTerminal, pollInterval, relativeTime, stageLabel, statusInfo } from '../jobs'
import JobProgress from './JobProgress.vue'

const route = useRoute()
const router = useRouter()

const vaults = ref([])
const runs = ref([])              // [{...run, vault_name}]
const details = ref({})           // key = `${vault_id}:${id}` → SyncRunDetail
const expanded = ref(new Set())
const filterVault = ref(route.query.vault_id ? Number(route.query.vault_id) : null)
const filterStatus = ref('all')   // all | running | success | partial | failed | cancelled | aborted
const error = ref('')
const loading = ref(true)

let timer = null
let failures = 0

const runningRuns = computed(() => runs.value.filter((r) => !isTerminal(r.status)))
const hasRunning = computed(() => runningRuns.value.length > 0)

const visibleRuns = computed(() =>
  runs.value.filter((r) => {
    if (filterVault.value && r.vault_id !== filterVault.value) return false
    if (filterStatus.value === 'running') return !isTerminal(r.status)
    if (filterStatus.value !== 'all') return r.status === filterStatus.value
    return true
  })
)

function keyOf(vaultId, runId) {
  return `${vaultId}:${runId}`
}

async function loadAll() {
  try {
    const list = await vaultsApi.list()
    vaults.value = list
    const perVault = await Promise.all(list.map((v) => vaultsApi.listRuns(v.id, 50)))
    runs.value = perVault
      .flatMap((rs, i) => rs.map((r) => ({ ...r, vault_name: list[i].name })))
      // 运行中置顶，其余按开始时间倒序（后端返回全部状态，排序责任在前端）
      .sort((a, b) => {
        const ra = isTerminal(a.status) ? 1 : 0
        const rb = isTerminal(b.status) ? 1 : 0
        if (ra !== rb) return ra - rb
        return String(b.started_at || '').localeCompare(String(a.started_at || ''))
      })
    failures = 0
    error.value = ''
  } catch (e) {
    failures += 1
    // 轮询失败不弹错打断用户；连续失败才提示（§5.4.5）
    if (failures >= 10) error.value = '无法获取进度，请检查后端与鉴权设置'
  } finally {
    loading.value = false
  }
  await refreshDetails()
  schedule()
}

/** 已展开的行需要跟着刷新详情（计划 / 失败清单 / 当前文件）。 */
async function refreshDetails() {
  const targets = runs.value.filter((r) => expanded.value.has(keyOf(r.vault_id, r.id)))
  await Promise.all(
    targets.map(async (r) => {
      try {
        details.value = { ...details.value, [keyOf(r.vault_id, r.id)]: await vaultsApi.getRun(r.vault_id, r.id) }
      } catch {
        /* 详情拉取失败不影响列表 */
      }
    })
  )
}

function schedule() {
  clearTimeout(timer)
  if (!hasRunning.value) return              // 全部终态 → 停表（不要空转）
  const base = Math.min(
    ...runningRuns.value.map((r) => pollInterval(r.status, r.cancelling))
  )
  // 失败退避：1s → 2s → 5s（封顶）
  const wait = failures ? Math.min(5000, 1000 * 2 ** (failures - 1)) : base
  timer = setTimeout(() => {
    if (document.visibilityState === 'hidden') return schedule()   // 页面不可见时暂停
    loadAll()
  }, wait)
}

function onVisibility() {
  if (document.visibilityState === 'visible') loadAll()           // 回到前台立即补一次
}

async function toggle(run) {
  const k = keyOf(run.vault_id, run.id)
  const next = new Set(expanded.value)
  if (next.has(k)) {
    next.delete(k)
  } else {
    next.add(k)
    try {
      details.value = { ...details.value, [k]: await vaultsApi.getRun(run.vault_id, run.id) }
    } catch (e) {
      error.value = e.message
    }
  }
  expanded.value = next
}

async function cancel(run) {
  try {
    await vaultsApi.cancelRun(run.vault_id, run.id)
    // 204 ≠ 已停止：立刻进入「正在停止…」（cancelling），并靠轮询等到 status=cancelled
    run.cancelling = true
  } catch (e) {
    if (e.status === 409) {
      error.value = '该作业已结束，无需取消'
      await loadAll()
    } else {
      error.value = e.message
    }
  }
}

/** 提交一次同步作业；撞上 409（同库已有作业在跑）时跳到那个任务的进度视图。 */
async function submitSync(vaultId, payload = {}) {
  error.value = ''
  try {
    const res = await vaultsApi.submitSync(vaultId, payload)
    router.replace({ query: { ...route.query, vault_id: vaultId, run_id: res.run_id } })
    await loadAll()
  } catch (e) {
    if (e.status === 409 && e.body?.existing_run_id) {
      // 同 vault 不排队：直接跟随已有的那条任务，而不是重试（M06 ADR-8）
      router.replace({ query: { ...route.query, vault_id: vaultId, run_id: e.body.existing_run_id } })
      await loadAll()
    } else {
      error.value = e.message
    }
  }
}

/** dry_run 第二段：用户看过计划后确认执行（会**重新对账**，不复用第一段的计划）。 */
async function confirmPlan(run) {
  await submitSync(run.vault_id, { mode: 'sync', dry_run: false })
}

onMounted(() => {
  document.addEventListener('visibilitychange', onVisibility)
  // 从 VaultManager 跳进来时带 run_id → 自动展开该任务，省去用户再点一次
  const jump = route.query.run_id ? Number(route.query.run_id) : null
  if (jump) expanded.value = new Set([keyOf(Number(route.query.vault_id), jump)])
  loadAll()
})

onUnmounted(() => {
  clearTimeout(timer)
  document.removeEventListener('visibilitychange', onVisibility)
})

watch(() => route.query.run_id, (v) => {
  if (!v) return
  const k = keyOf(Number(route.query.vault_id), Number(v))
  if (!expanded.value.has(k)) expanded.value = new Set([...expanded.value, k])
})
</script>

<template>
  <section>
    <h2>任务与进度</h2>
    <p class="hint">
      索引是异步作业：提交后立即返回、在后台推进。这里可以看进度、看计划、随时取消。
    </p>

    <div class="filters">
      <select v-model="filterVault">
        <option :value="null">全部 vault</option>
        <option v-for="v in vaults" :key="v.id" :value="v.id">{{ v.name }}</option>
      </select>
      <select v-model="filterStatus">
        <option value="all">全部状态</option>
        <option value="running">进行中</option>
        <option value="success">已完成</option>
        <option value="partial">部分完成</option>
        <option value="failed">失败</option>
        <option value="cancelled">已取消</option>
        <option value="aborted">已中断</option>
      </select>
      <span class="spacer"></span>
      <span class="meta">{{ runningRuns.length }} 个进行中 · 共 {{ runs.length }} 条</span>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="hint">加载中…</p>
    <p v-else-if="!visibleRuns.length" class="hint">没有匹配的作业记录。</p>

    <ul class="list">
      <li v-for="r in visibleRuns" :key="keyOf(r.vault_id, r.id)" :class="{ active: !isTerminal(r.status) }">
        <div class="head" @click="toggle(r)">
          <span class="vault">{{ r.vault_name }}</span>
          <span class="tag">{{ r.mode }}{{ r.dry_run ? ' · 预览' : '' }}</span>
          <span class="tag muted">{{ r.trigger }}</span>
          <span class="when">{{ relativeTime(r.started_at) }}</span>
          <span class="times">耗时 {{ r.elapsed_ms ? (r.elapsed_ms / 1000).toFixed(1) + 's' : '—' }}</span>
          <span class="chevron">{{ expanded.has(keyOf(r.vault_id, r.id)) ? '▾' : '▸' }}</span>
        </div>

        <!-- 摘要：进度条（三态自适应）或终态徽标 -->
        <JobProgress :run="r" compact cancellable @cancel="cancel" />

        <div v-if="expanded.has(keyOf(r.vault_id, r.id))" class="detail">
          <template v-if="details[keyOf(r.vault_id, r.id)]">
            <div class="grid">
              <div><label>状态</label>{{ statusInfo(details[keyOf(r.vault_id, r.id)].status).label }}</div>
              <div><label>阶段</label>{{ stageLabel(details[keyOf(r.vault_id, r.id)].stage) }}</div>
              <div><label>变更</label>{{ countsSummary(details[keyOf(r.vault_id, r.id)]) }}</div>
              <div><label>未变化</label>{{ details[keyOf(r.vault_id, r.id)].unchanged }}</div>
            </div>

            <p v-if="details[keyOf(r.vault_id, r.id)].message" class="msg">
              {{ details[keyOf(r.vault_id, r.id)].message }}
            </p>

            <!-- 护栏拦截：删除被拒绝时要讲清原因，否则用户不知道该怎么办 -->
            <p v-if="details[keyOf(r.vault_id, r.id)].blocked_reason" class="blocked">
              删除已被护栏拦截（{{ details[keyOf(r.vault_id, r.id)].blocked_reason }}）：本轮只增不删。
            </p>
            <p v-if="details[keyOf(r.vault_id, r.id)].error" class="error">
              {{ details[keyOf(r.vault_id, r.id)].error }}
            </p>

            <!-- dry_run 的计划快照 + 第二段确认 -->
            <template v-if="details[keyOf(r.vault_id, r.id)].plan">
              <h4>同步计划（预览）</h4>
              <div class="grid">
                <div><label>新增</label>{{ details[keyOf(r.vault_id, r.id)].plan.adds }}</div>
                <div><label>修改</label>{{ details[keyOf(r.vault_id, r.id)].plan.updates }}</div>
                <div><label>移动</label>{{ details[keyOf(r.vault_id, r.id)].plan.moves }}</div>
                <div><label>删除</label>{{ details[keyOf(r.vault_id, r.id)].plan.deletes }}</div>
              </div>
              <p class="hint">执行时会<strong>重新比对</strong>，计划可能已过期。</p>
              <button class="primary" @click="confirmPlan(r)">执行这次同步</button>
            </template>

            <!-- 失败清单：这是「为什么这个文件没被索引」的唯一可查来源 -->
            <template v-if="details[keyOf(r.vault_id, r.id)].result?.failed_files?.length">
              <h4>失败文件</h4>
              <ul class="failed">
                <li v-for="(f, i) in details[keyOf(r.vault_id, r.id)].result.failed_files" :key="i">
                  <code>{{ f.path }}</code> — {{ f.reason }}
                </li>
              </ul>
            </template>
          </template>
          <p v-else class="hint">详情加载中…</p>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.hint { color: #888; font-size: 13px; }
.error { color: #a32d2d; font-size: 13px; }
.blocked { color: #b26a00; font-size: 13px; }
.filters { display: flex; align-items: center; gap: 8px; margin: 10px 0; }
.spacer { flex: 1; }
.meta { color: #666; font-size: 13px; }

.list { list-style: none; padding: 0; }
.list > li { border: 1px solid #eee; border-radius: 6px; padding: 10px; margin-bottom: 8px; }
.list > li.active { border-color: #185fa5; background: #f7fafd; }

.head { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.vault { font-weight: 600; }
.tag { font-size: 12px; background: #eef2f7; border-radius: 4px; padding: 1px 6px; }
.tag.muted { background: #f3f3f3; color: #777; }
.when { color: #888; font-size: 12px; }
.times { color: #888; font-size: 12px; }
.chevron { margin-left: auto; color: #999; }

.detail { margin-top: 10px; border-top: 1px dashed #eee; padding-top: 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 6px 12px; }
.grid label { display: block; color: #999; font-size: 12px; }
.msg { color: #666; font-size: 13px; }
.failed { font-size: 13px; color: #a32d2d; }
button.primary { margin-top: 6px; }
</style>
