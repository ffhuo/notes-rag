<script setup>
// Vault 管理页：列出当前用户的 vault，并内嵌「当前作业」的一行进度（M07 §5.4.1）。
//
// 两种添加方式：
//  1) 本地目录：填 name + 绝对路径 → POST /vaults（JSON）
//  2) 上传 vault：选 .zip → POST /vaults/upload（multipart，source_type=uploaded）
//
// 索引类按钮**不再同步等待**（后端一律 202，M03 §5.13）：
//   - 同步：增量对账（日常用，通常数秒）
//   - 预览变更：dry_run 作业，停在 stage=plan_ready，先在任务页看计划再决定
//   - 重建索引：全量重算（换 embedding / 分块参数 / 索引疑似损坏时才用，分钟级）
// 提交后跳转到 /tasks?run_id=…，让用户立刻看到进度，而不是盯着一个没有反馈的按钮。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { vaultsApi } from '../api'
import { isTerminal, pollInterval } from '../jobs'
import JobProgress from './JobProgress.vue'

const router = useRouter()

const vaults = ref([])
const latest = ref({})            // vault_id → 最近一条作业（SyncRunOut）
const newName = ref('')
const newPath = ref('')
const uploadFile = ref(null)
const error = ref('')
let timer = null

const hasRunning = computed(() => Object.values(latest.value).some((r) => r && !isTerminal(r.status)))

async function load() {
  try {
    vaults.value = await vaultsApi.list()
    const per = await Promise.all(
      vaults.value.map((v) => vaultsApi.listRuns(v.id, 1).catch(() => []))
    )
    latest.value = Object.fromEntries(
      vaults.value.map((v, i) => [v.id, per[i]?.[0] || null])
    )
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

function schedule() {
  clearTimeout(timer)
  if (!hasRunning.value) return            // 没有运行中作业就停表
  const base = Math.min(...Object.values(latest.value)
    .filter((r) => r && !isTerminal(r.status))
    .map((r) => pollInterval(r.status, r.cancelling)))
  timer = setTimeout(load, base)
}

async function refresh() {
  await load()
  schedule()
}

async function addLocal() {
  error.value = ''
  try {
    await vaultsApi.create({ name: newName.value, source_type: 'local', source_value: newPath.value })
    newName.value = ''
    newPath.value = ''
    await refresh()
  } catch (e) {
    error.value = e.message
  }
}

async function addUpload() {
  error.value = ''
  try {
    await vaultsApi.upload(newName.value, uploadFile.value)
    newName.value = ''
    uploadFile.value = null
    await refresh()
  } catch (e) {
    error.value = e.message
  }
}

/** 提交作业并跳到任务页；同库已有作业在跑（409）时跟随那一条，不重试（M06 ADR-8）。 */
async function submit(vaultId, payload = {}) {
  error.value = ''
  try {
    const res = await vaultsApi.submitSync(vaultId, payload)
    router.push({ name: 'tasks', query: { vault_id: vaultId, run_id: res.run_id } })
  } catch (e) {
    if (e.status === 409 && e.body?.existing_run_id) {
      router.push({ name: 'tasks', query: { vault_id: vaultId, run_id: e.body.existing_run_id } })
    } else {
      error.value = e.message
    }
  }
}

async function reindex(vaultId) {
  error.value = ''
  try {
    const res = await vaultsApi.reindex(vaultId)      // = submitSync(mode="rebuild")
    router.push({ name: 'tasks', query: { vault_id: vaultId, run_id: res.run_id } })
  } catch (e) {
    if (e.status === 409 && e.body?.existing_run_id) {
      router.push({ name: 'tasks', query: { vault_id: vaultId, run_id: e.body.existing_run_id } })
    } else {
      error.value = e.message
    }
  }
}

async function remove(id) {
  if (!confirm('删除该 vault？同时会清掉它的索引与分块记录，不可撤销。')) return
  try {
    await vaultsApi.remove(id)
    await refresh()
  } catch (e) {
    error.value = e.message
  }
}

async function cancel(run) {
  try {
    await vaultsApi.cancelRun(run.vault_id, run.id)
    run.cancelling = true       // 204 ≠ 已停止：先进入「正在停止…」，靠轮询等终态
  } catch (e) {
    error.value = e.message
  }
}

onMounted(refresh)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <section>
    <h2>Vaults</h2>
    <p class="hint">
      添加本地目录（填绝对路径）或上传 vault 压缩包（.zip）。建好后点「同步」建索引 ——
      索引是后台作业，提交后会跳到任务页看进度。
    </p>

    <div class="form">
      <input v-model="newName" placeholder="vault 名称" />
      <input v-model="newPath" placeholder="本地目录绝对路径（local 模式）" />
      <button @click="addLocal">添加本地目录</button>
    </div>

    <div class="form">
      <input v-model="newName" placeholder="vault 名称" />
      <input type="file" accept=".zip" @change="e => (uploadFile = e.target.files[0])" />
      <button @click="addUpload">上传 vault</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <ul>
      <li v-for="v in vaults" :key="v.id">
        <div class="line">
          <span>{{ v.name }} · {{ v.source_type }} · {{ v.source_value }}</span>
          <span class="actions">
            <button @click="submit(v.id, { mode: 'sync' })">同步</button>
            <button @click="submit(v.id, { mode: 'sync', dry_run: true })">预览变更</button>
            <button @click="reindex(v.id)">重建索引</button>
            <button @click="remove(v.id)">删除</button>
          </span>
        </div>

        <!-- 内嵌当前作业：空闲时也显示最近一条的结果摘要，让「上次同步什么时候」一目了然 -->
        <JobProgress :run="latest[v.id]" compact cancellable @cancel="cancel" />

        <!-- 模型绑定状态：只在作业成功后回写，所以它恒表示「当前可检索的 embedding」 -->
        <div class="models" :title="'已建过索引的 embedding 配置 id'">
          当前 embedding：{{ v.embed_profile_id ?? '未索引' }}
          <template v-if="v.embed_indexed_profiles?.length">
            · 已建过 [{{ v.embed_indexed_profiles.join(', ') }}]
          </template>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.form { display: flex; gap: 8px; margin: 8px 0; }
.hint { color: #888; font-size: 13px; }
.error { color: #a32d2d; }
ul { list-style: none; padding: 0; }
ul > li { border: 1px solid #eee; border-radius: 6px; padding: 10px; margin-bottom: 8px; }
.line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.actions { margin-left: auto; display: flex; gap: 6px; }
.models { margin-top: 4px; color: #999; font-size: 12px; }
</style>
