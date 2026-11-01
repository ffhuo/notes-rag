<script setup>
import { computed } from 'vue'
import AppIcon from '../components/AppIcon.vue'

const props = defineProps({
  progress: { type: Number, required: true },
  vaultName: { type: String, required: true },
})

const emit = defineEmits(['complete', 'navigate'])

const stages = computed(() => [
  { title: '扫描文件', detail: '发现 4 个文件 · 18 个内容片段', status: 'done', time: '00:02' },
  { title: '解析与切片', detail: '按语义边界整理笔记内容', status: 'done', time: '00:04' },
  { title: '生成向量', detail: '将片段转换为可检索的向量', status: props.progress >= 100 ? 'done' : 'running', time: props.progress >= 100 ? '00:06' : '进行中' },
  { title: '写入本地索引', detail: '更新知识库并检查索引状态', status: props.progress >= 100 ? 'done' : 'pending', time: props.progress >= 100 ? '00:01' : '等待中' },
])

const progressText = computed(() => `${props.progress}%`)
</script>

<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow"><span class="eyebrow__dot"></span> INDEXING, STEP BY STEP</div>
      <h1>每一次更新，都有迹可循</h1>
      <p>跟踪知识库处理进度，知道当前阶段与下一步。</p>
    </div>
    <span class="status-pill status-pill--running"><span></span>{{ progress === 100 ? '已完成' : '执行中' }}</span>
  </div>

  <div class="task-kpis">
    <article class="panel task-kpi">
      <span class="task-kpi__icon task-kpi__icon--blue"><AppIcon name="zap" :size="17" /></span>
      <span><small>执行中</small><strong>{{ progress === 100 ? 0 : 1 }}</strong></span>
      <span class="task-kpi__trend">本次任务</span>
    </article>
    <article class="panel task-kpi">
      <span class="task-kpi__icon task-kpi__icon--slate"><AppIcon name="clock" :size="17" /></span>
      <span><small>排队中</small><strong>0</strong></span>
      <span class="task-kpi__trend">暂无等待</span>
    </article>
    <article class="panel task-kpi">
      <span class="task-kpi__icon task-kpi__icon--green"><AppIcon name="check" :size="17" /></span>
      <span><small>今日成功</small><strong>{{ progress === 100 ? 1 : 0 }}</strong></span>
      <span class="task-kpi__trend">索引任务</span>
    </article>
    <article class="panel task-kpi">
      <span class="task-kpi__icon task-kpi__icon--amber"><AppIcon name="alert" :size="17" /></span>
      <span><small>需要关注</small><strong>0</strong></span>
      <span class="task-kpi__trend">无失败任务</span>
    </article>
  </div>

  <section class="panel task-detail">
    <div class="task-detail__header">
      <div class="task-detail__title">
        <div class="task-detail__symbol"><AppIcon name="vaults" :size="20" /></div>
        <div>
          <div class="task-detail__name-row">
            <h2>{{ vaultName }} · 增量同步</h2>
            <span class="status-pill" :class="progress === 100 ? 'status-pill--success' : 'status-pill--running'">
              <span></span>{{ progress === 100 ? '已完成' : '正在处理' }}
            </span>
          </div>
          <p>任务 #1048 <span>·</span> 今天 10:42 启动 <span>·</span> 4 个文件</p>
        </div>
      </div>
      <button class="button button--secondary task-detail__action" type="button" @click="emit('navigate', 'vaults')">
        <AppIcon name="external-link" :size="15" />
        返回知识库
      </button>
    </div>

    <div class="task-overview">
      <div class="task-overview__meter">
        <div class="task-overview__labels"><span>整体进度</span><strong>{{ progressText }}</strong></div>
        <div class="progress-track" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100" aria-label="整体索引进度">
          <span :style="{ width: progressText }"></span>
        </div>
        <p>{{ progress === 100 ? '全部文件已写入索引，可以开始检索。' : '正在为笔记生成语义向量，完成后即可检索。' }}</p>
      </div>
      <div class="task-overview__stats">
        <div><small>已处理文件</small><strong>{{ progress === 100 ? '4 / 4' : '3 / 4' }}</strong></div>
        <div><small>已生成片段</small><strong>{{ progress === 100 ? '18 / 18' : '13 / 18' }}</strong></div>
        <div><small>已用时间</small><strong>{{ progress === 100 ? '00:13' : '00:11' }}</strong></div>
      </div>
    </div>

    <div class="task-timeline">
      <div
        v-for="(stage, index) in stages"
        :key="stage.title"
        class="task-stage"
        :class="`is-${stage.status}`"
      >
        <div class="task-stage__rail">
          <span class="task-stage__marker">
            <AppIcon v-if="stage.status === 'done'" name="check" :size="13" />
            <AppIcon v-else-if="stage.status === 'running'" name="loader" :size="14" />
            <span v-else>{{ index + 1 }}</span>
          </span>
          <span v-if="index < stages.length - 1" class="task-stage__connector"></span>
        </div>
        <div class="task-stage__body">
          <div class="task-stage__top">
            <strong>{{ stage.title }}</strong>
            <span>{{ stage.time }}</span>
          </div>
          <p>{{ stage.detail }}</p>
          <div v-if="stage.status === 'running'" class="task-stage__mini-progress">
            <span :style="{ width: progress < 100 ? '76%' : '100%' }"></span>
          </div>
        </div>
        <span class="task-stage__state">{{ stage.status === 'done' ? '完成' : stage.status === 'running' ? '进行中' : '待处理' }}</span>
      </div>
    </div>

    <div class="task-detail__footer">
      <div><AppIcon name="info" :size="16" /><span>任务可以在后台继续运行，你可以离开此页面。</span></div>
      <button
        v-if="progress < 100"
        class="button button--primary"
        type="button"
        @click="emit('complete')"
      >
        <AppIcon name="check" :size="16" />
        完成演示任务
      </button>
      <button
        v-else
        class="button button--primary"
        type="button"
        @click="emit('navigate', 'search')"
      >
        去检索这批笔记
        <AppIcon name="chevron-right" :size="16" />
      </button>
    </div>
  </section>

  <div class="task-bottom-note">
    <span class="task-bottom-note__icon"><AppIcon name="info" :size="16" /></span>
    <p><strong>进度是实时的</strong>　正式版本中，任务阶段与进度会由服务端作业状态持续更新。</p>
  </div>
</template>

<style scoped>
.status-pill { display: inline-flex; align-items: center; gap: 6px; width: max-content; padding: 5px 9px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.status-pill > span { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.status-pill--running { color: var(--ui-info); background: var(--color-info-soft); }
.status-pill--success { color: var(--ui-success); background: var(--color-success-soft); }
.button { min-height: 40px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 0 14px; border: 1px solid transparent; border-radius: 9px; font-size: 13px; font-weight: 600; cursor: pointer; }
.button--primary { color: var(--color-primary-contrast); background: var(--ui-primary); }
.button--primary:hover { background: var(--ui-primary-hover); }
.button--secondary { color: var(--ui-text); background: var(--ui-surface); border-color: var(--ui-border); }
.button--secondary:hover { background: var(--ui-surface-soft); }
.task-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
.task-kpi { min-height: 104px; display: flex; align-items: center; gap: 12px; padding: 16px; }
.task-kpi__icon { width: 36px; height: 36px; display: grid; flex: none; place-items: center; border-radius: 11px; }
.task-kpi__icon--blue { color: var(--ui-primary); background: var(--ui-primary-soft); }
.task-kpi__icon--slate { color: var(--color-text-secondary); background: var(--ui-surface-soft); }
.task-kpi__icon--green { color: var(--ui-success); background: var(--color-success-soft); }
.task-kpi__icon--amber { color: var(--ui-warning); background: var(--color-warning-soft); }
.task-kpi > span:nth-child(2) { display: grid; gap: 3px; }
.task-kpi small { color: var(--ui-muted); font-size: 11px; }
.task-kpi strong { color: var(--ui-ink); font-size: 21px; line-height: 24px; }
.task-kpi__trend { margin-left: auto; color: var(--ui-muted); font-size: 10px; text-align: right; }
.task-detail { padding: 22px 24px 0; }
.task-detail__header, .task-detail__title, .task-detail__name-row, .task-overview__labels, .task-stage__top, .task-detail__footer, .task-detail__footer > div { display: flex; align-items: center; }
.task-detail__header { justify-content: space-between; gap: 14px; padding-bottom: 20px; border-bottom: 1px solid var(--ui-border); }
.task-detail__title { gap: 13px; min-width: 0; }
.task-detail__symbol { width: 42px; height: 42px; display: grid; flex: none; place-items: center; color: var(--ui-primary); background: var(--ui-primary-soft); border-radius: 12px; }
.task-detail__name-row { flex-wrap: wrap; gap: 9px; }
.task-detail__name-row h2 { color: var(--ui-ink); font-size: 15px; }
.task-detail__title p { margin-top: 6px; color: var(--ui-muted); font-size: 11px; }
.task-detail__title p span { padding: 0 4px; color: var(--color-border-strong); }
.task-detail__action { flex: none; }
.task-overview { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(250px, .8fr); gap: 28px; padding: 22px 0; border-bottom: 1px solid var(--ui-border); }
.task-overview__labels { justify-content: space-between; color: var(--ui-muted); font-size: 12px; }
.task-overview__labels strong { color: var(--ui-primary); font-size: 18px; }
.progress-track { height: 8px; overflow: hidden; margin-top: 10px; background: var(--ui-surface-soft); border-radius: 9px; }
.progress-track span { display: block; height: 100%; background: var(--ui-success); border-radius: inherit; transition: width .32s ease; }
.task-overview__meter > p { margin-top: 9px; color: var(--ui-muted); font-size: 11px; }
.task-overview__stats { display: grid; grid-template-columns: repeat(3, 1fr); align-content: center; gap: 10px; padding-left: 25px; border-left: 1px solid var(--ui-border); }
.task-overview__stats div { display: grid; gap: 4px; }
.task-overview__stats small { color: var(--ui-muted); font-size: 10px; white-space: nowrap; }
.task-overview__stats strong { color: var(--ui-ink); font-size: 15px; }
.task-timeline { display: grid; gap: 0; padding: 14px 0 20px; }
.task-stage { min-height: 68px; display: grid; grid-template-columns: 30px minmax(0, 1fr) 70px; gap: 11px; }
.task-stage__rail { position: relative; display: flex; justify-content: center; }
.task-stage__marker { z-index: 1; width: 24px; height: 24px; display: grid; place-items: center; color: var(--ui-muted); background: var(--ui-surface-soft); border-radius: 50%; font-size: 10px; }
.is-done .task-stage__marker { color: var(--color-success-contrast); background: var(--ui-success); }
.is-running .task-stage__marker { color: var(--color-info-contrast); background: var(--ui-info); box-shadow: 0 0 0 4px var(--color-info-soft); }
.task-stage__connector { position: absolute; top: 23px; bottom: -1px; width: 1px; background: var(--ui-border); }
.task-stage__body { padding: 1px 0 15px; }
.task-stage__top { justify-content: space-between; gap: 12px; }
.task-stage__top strong { color: var(--ui-text); font-size: 12px; }
.task-stage__top > span { color: var(--ui-muted); font-size: 10px; }
.task-stage__body > p { margin-top: 4px; color: var(--ui-muted); font-size: 11px; }
.task-stage__mini-progress { height: 3px; overflow: hidden; margin-top: 9px; background: var(--ui-surface-soft); border-radius: 4px; }
.task-stage__mini-progress > span { display: block; height: 100%; background: var(--ui-info); border-radius: inherit; }
.task-stage__state { justify-self: end; padding-top: 4px; color: var(--ui-muted); font-size: 10px; }
.is-done .task-stage__state { color: var(--ui-success); }
.is-running .task-stage__state { color: var(--ui-info); }
.task-detail__footer { min-height: 68px; justify-content: space-between; gap: 12px; border-top: 1px solid var(--ui-border); }
.task-detail__footer > div { gap: 8px; color: var(--ui-muted); font-size: 11px; }
.task-detail__footer > div :deep(svg) { color: var(--ui-primary); }
.task-bottom-note { display: flex; align-items: center; gap: 9px; margin-top: 15px; color: var(--ui-muted); font-size: 11px; }
.task-bottom-note strong { color: var(--ui-ink); }
.task-bottom-note__icon { color: var(--ui-primary); }
@media (max-width: 920px) {
  .task-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .task-overview { grid-template-columns: 1fr; gap: 17px; }
  .task-overview__stats { padding: 15px 0 0; border-top: 1px solid var(--ui-border); border-left: 0; }
}
@media (max-width: 600px) {
  .task-kpi { min-height: 88px; padding: 12px; gap: 9px; }
  .task-kpi__trend { display: none; }
  .task-detail { padding: 16px 15px 0; }
  .task-detail__header { align-items: flex-start; flex-direction: column; }
  .task-detail__action { align-self: flex-end; }
  .task-overview__stats { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5px; }
  .task-detail__footer { align-items: flex-start; flex-direction: column; padding: 13px 0; }
}
@media (prefers-reduced-motion: reduce) {
  .progress-track span { transition: none; }
}
</style>
