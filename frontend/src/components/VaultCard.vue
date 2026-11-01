<script setup>
import { computed } from 'vue'
import { statusInfo } from '../jobs'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  vault: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  run: { type: Object, default: null },
})

const emit = defineEmits(['select'])

const state = computed(() => {
  if (props.run && statusInfo(props.run.status).running) {
    return { label: '进行中', tone: 'running' }
  }
  if (props.run && ['failed', 'aborted', 'partial'].includes(props.run.status)) {
    const info = statusInfo(props.run.status)
    return { label: info.label, tone: info.tone === 'danger' ? 'error' : 'warning' }
  }
  if (props.vault.indexed_at) return { label: '已就绪', tone: 'success' }
  return { label: '待索引', tone: 'pending' }
})
</script>

<template>
  <article class="vault-card panel" :class="{ 'is-selected': selected }">
    <button
      class="vault-card__select"
      type="button"
      :aria-pressed="selected"
      @click="emit('select', vault.id)"
    >
      <span class="vault-card__icon"><AppIcon name="vaults" :size="19" /></span>
      <span class="vault-card__copy">
        <strong :title="vault.name">{{ vault.name }}</strong>
        <small>
          <AppIcon :name="vault.source_type === 'uploaded' ? 'upload' : 'folder'" :size="13" />
          {{ vault.source_type === 'uploaded' ? '本机上传' : '服务器目录' }}
        </small>
      </span>
      <span v-if="selected" class="vault-card__check"><AppIcon name="check" :size="13" /></span>
    </button>

    <div class="vault-card__stats">
      <span><strong>{{ vault.indexed_file_count || 0 }}</strong> 个文件</span>
      <span><strong>{{ vault.chunk_count || 0 }}</strong> 个片段</span>
      <span class="status-pill" :class="`status-pill--${state.tone}`">
        <span></span>{{ state.label }}
      </span>
    </div>

    <p class="vault-card__path" :title="vault.source_value">
      <AppIcon :name="vault.source_type === 'uploaded' ? 'upload' : 'folder'" :size="13" />
      <span>{{ vault.source_value }}</span>
    </p>
  </article>
</template>

<style scoped>
.vault-card {
  min-width: 0;
  padding: 12px;
  border-color: var(--ui-border);
}

.vault-card.is-selected {
  border-color: var(--ui-primary);
  box-shadow: 0 0 0 2px var(--ui-primary-soft);
}

.vault-card__select {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 0;
  text-align: left;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.vault-card__icon {
  width: 34px;
  height: 34px;
  display: grid;
  flex: none;
  place-items: center;
  color: var(--ui-primary);
  background: var(--ui-primary-soft);
  border-radius: 10px;
}

.vault-card__copy {
  min-width: 0;
  display: grid;
  flex: 1;
  gap: 3px;
}

.vault-card__copy strong {
  overflow: hidden;
  color: var(--ui-ink);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vault-card__copy small {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--ui-muted);
  font-size: 9px;
}

.vault-card__check {
  width: 20px;
  height: 20px;
  display: grid;
  flex: none;
  place-items: center;
  color: var(--color-primary-contrast);
  background: var(--ui-primary);
  border-radius: 50%;
}

.vault-card__stats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  color: var(--ui-muted);
  font-size: 9px;
}

.vault-card__stats strong {
  color: var(--ui-ink);
}

.vault-card__path {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 5px;
  overflow: hidden;
  margin: 9px 0 0;
  color: var(--ui-muted);
  font-size: 9px;
}

.vault-card__path :deep(svg) {
  flex: none;
}

.vault-card__path > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 7px;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 600;
  white-space: nowrap;
}

.status-pill > span {
  width: 5px;
  height: 5px;
  background: currentColor;
  border-radius: 50%;
}

.status-pill--success {
  color: var(--ui-success);
  background: var(--color-success-soft);
}

.status-pill--running {
  color: var(--ui-info);
  background: var(--color-info-soft);
}

.status-pill--warning,
.status-pill--pending {
  color: var(--ui-warning);
  background: var(--color-warning-soft);
}

.status-pill--error {
  color: var(--ui-danger);
  background: var(--color-danger-soft);
}
</style>
