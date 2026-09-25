<script setup>
// 作业进度条 —— Vault 卡片内嵌、任务页、详情三处共用（M07 §5.4.2 / §5.4.4）。
//
// 关键：不能对所有阶段都用百分比。scan 阶段的 total 是 null（文件总数要遍历完才知道），
// 给它硬编一个假分母会让用户看着 80% 卡死，比滚动条更焦虑。
import { computed } from 'vue'
import { countsSummary, isCancelling, percent, progressShape, stageLabel, statusInfo } from '../jobs'

const props = defineProps({
  run: { type: Object, default: null },     // SyncRunOut | SyncRunDetail | null
  compact: { type: Boolean, default: false },
  cancellable: { type: Boolean, default: false },
})
const emit = defineEmits(['cancel'])

const shape = computed(() => progressShape(props.run))
const st = computed(() => statusInfo(props.run?.status))
const cancelling = computed(() => isCancelling(props.run))
const pct = computed(() => percent(props.run))
</script>

<template>
  <div v-if="!run" class="jp idle">暂无作业记录</div>

  <div v-else class="jp" :class="{ compact }">
    <div class="row">
      <span class="dot" :class="`tone-${st.tone}`"></span>
      <span class="stage">{{ stageLabel(run.stage) }}</span>

      <!-- 终态：收起进度条，换状态徽标 + 计数摘要 -->
      <template v-if="shape === 'badge'">
        <span class="badge" :class="`tone-${st.tone}`">{{ st.label }}</span>
        <span class="meta">{{ countsSummary(run) }}</span>
        <span v-if="run.failed_cnt" class="meta danger">{{ run.failed_cnt }} 个失败</span>
      </template>

      <!-- 不确定态：横向滚动条纹 + 已处理数（绝不显示假百分比） -->
      <template v-else-if="shape === 'indeterminate'">
        <span class="meta">已扫描 {{ run.processed }} 个文件…</span>
      </template>

      <!-- 确定态：processed / total + 百分比 -->
      <template v-else-if="shape === 'determinate'">
        <span class="meta">{{ run.processed }} / {{ run.total }}</span>
        <span class="meta pct">{{ pct }}%</span>
      </template>

      <template v-else>
        <span class="meta">等待开始…</span>
      </template>

      <span v-if="run.current_item && shape !== 'badge'" class="path" :title="run.current_item">
        {{ run.current_item }}
      </span>

      <!-- 取消：只在运行中且未受理取消时可用；已受理则禁用并改文案 -->
      <button
        v-if="cancellable && (st.running || cancelling)"
        class="cancel"
        :disabled="cancelling"
        :title="cancelling ? '会在当前文件处理完后停止' : '在当前文件处理完后停止（不是瞬时）'"
        @click="emit('cancel', run)"
      >
        {{ cancelling ? '正在停止…' : '取消' }}
      </button>
    </div>

    <div v-if="shape === 'indeterminate'" class="bar indeterminate"><i></i></div>
    <div v-else-if="shape === 'determinate'" class="bar"><i :style="{ width: pct + '%' }"></i></div>

    <div v-if="run.message && shape !== 'badge'" class="msg">{{ run.message }}</div>
  </div>
</template>

<style scoped>
.jp { font-size: 13px; }
.jp.idle { color: #888; }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.stage { font-weight: 600; }
.meta { color: #666; }
.meta.pct { font-variant-numeric: tabular-nums; }
.danger { color: #a32d2d; }
.path { color: #999; font-size: 12px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msg { color: #666; font-size: 12px; margin-top: 2px; }

.dot { width: 8px; height: 8px; border-radius: 50%; background: #999; flex: none; }
.tone-info { background: #185fa5; }
.tone-ok { background: #2f7d32; }
.tone-warn { background: #b26a00; }
.tone-danger { background: #a32d2d; }
.tone-muted { background: #999; }

.badge { padding: 1px 6px; border-radius: 4px; color: #fff; font-size: 12px; }
.badge.tone-info { background: #185fa5; }
.badge.tone-ok { background: #2f7d32; }
.badge.tone-warn { background: #b26a00; }
.badge.tone-danger { background: #a32d2d; }
.badge.tone-muted { background: #999; }

.bar { margin-top: 6px; height: 6px; background: #eee; border-radius: 3px; overflow: hidden; }
.bar i { display: block; height: 100%; background: #185fa5; transition: width .3s ease; }

/* 不确定态：滚动条纹，明确「在动但总量未知」 */
.bar.indeterminate i {
  width: 30%;
  background: repeating-linear-gradient(45deg, #185fa5 0 8px, #4a86c8 8px 16px);
  animation: jp-slide 1.2s linear infinite;
}
@keyframes jp-slide { from { transform: translateX(-100%); } to { transform: translateX(340%); } }

.cancel { margin-left: auto; font-size: 12px; padding: 2px 8px; cursor: pointer; }
.cancel:disabled { cursor: default; opacity: .6; }
.jp.compact .bar { height: 4px; }
</style>
