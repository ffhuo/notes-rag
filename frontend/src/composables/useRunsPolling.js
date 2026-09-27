// 作业轮询公共件（docs/ui-tasks.md §4.3：侧栏作业状态与任务页共用同一份数据，
// 避免同一接口被两处重复请求、两套轮询各自为政）。
//
// 数据源说明：后端没有「全量作业」端点（app/api/routes/vaults.py 只在 vault 下挂 /runs），
// 因此这里按「列 vaults → 逐 vault 取 runs → 扁平化」聚合。vault 是十位数量级，可接受。
//
// 停表策略（规范 §5.2 与 M03 §5.4.5「不要空转」）：
//   · 有进行中作业 → 按 jobs.js 的 pollInterval 轮询（取消中 500ms / 运行中 1s / 排队中 2s）
//   · 全部终态     → 停掉定时器，改为「窗口重新可见 / 获得焦点」时刷新
//   · 页面不可见   → 暂停轮询（visibilitychange）

import { computed, onMounted, onUnmounted, ref } from 'vue'
import { vaultsApi } from '../api'
import { isTerminal, pollInterval } from '../jobs'

// 每个 vault 取多少条历史：Tasks 页的「今日成功/失败」KPI 需要足够的时间窗口，
// 20 条在频繁同步的 vault 上不够一天用，故取 50。
const RUNS_PER_VAULT = 50

/* ---------- 模块级共享状态：多组件订阅只发一份请求 ---------- */
const runs = ref([])        // 扁平化作业列表，每项附 vault_name
const vaults = ref([])      // vault 列表（任务页筛选器复用）
const loading = ref(false)  // 仅「尚无数据」的首屏为 true，避免刷新时闪烁
const error = ref(null)
const updatedAt = ref(null)

let subscribers = 0
let timer = null
let inFlight = null         // 进行中的请求 Promise；并发调用共享同一次请求

const activeRuns = computed(() => runs.value.filter((r) => !isTerminal(r.status)))
const runningCount = computed(() => activeRuns.value.length)

function listVisible() {
  if (typeof document === 'undefined') return true
  return document.visibilityState !== 'hidden'
}

async function fetchOnce() {
  if (inFlight) return inFlight
  if (runs.value.length === 0) loading.value = true
  inFlight = (async () => {
    try {
      const list = await vaultsApi.list()
      vaults.value = list
      const batches = await Promise.all(
        list.map((v) => vaultsApi.listRuns(v.id, RUNS_PER_VAULT).catch(() => [])),
      )
      const flat = []
      list.forEach((v, i) => {
        for (const run of batches[i] || []) flat.push({ ...run, vault_name: v.name })
      })
      flat.sort((a, b) => (b.id || 0) - (a.id || 0))
      runs.value = flat
      error.value = null
      updatedAt.value = Date.now()
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
      inFlight = null
    }
  })()
  return inFlight
}

function clearTimer() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

function schedule() {
  clearTimer()
  if (!subscribers || !listVisible()) return
  const active = activeRuns.value
  if (!active.length) return // 全终态 → 不空转
  const delay = Math.min(...active.map((r) => pollInterval(r.status, r.cancelling)))
  timer = setTimeout(async () => {
    await fetchOnce()
    schedule()
  }, delay)
}

/** 手动刷新（用户点「刷新」、提交作业后调用）。 */
export async function refreshRuns() {
  await fetchOnce()
  schedule()
}

function onVisibility() {
  if (listVisible()) refreshRuns()
  else clearTimer()
}

function onFocus() {
  refreshRuns()
}

function bindListeners() {
  if (typeof window === 'undefined' || !window.addEventListener) return
  window.addEventListener('focus', onFocus)
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility)
}

function unbindListeners() {
  if (typeof window === 'undefined' || !window.removeEventListener) return
  window.removeEventListener('focus', onFocus)
  if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility)
}

/** 订阅共享的作业轮询：首个订阅者启动，最后一个取消者停止。 */
export function useRunsPolling() {
  onMounted(() => {
    subscribers += 1
    if (subscribers === 1) {
      bindListeners()
      refreshRuns()
    }
  })

  onUnmounted(() => {
    subscribers -= 1
    if (subscribers <= 0) {
      subscribers = 0
      clearTimer()
      unbindListeners()
    }
  })

  return { runs, vaults, loading, error, updatedAt, activeRuns, runningCount, refresh: refreshRuns }
}
