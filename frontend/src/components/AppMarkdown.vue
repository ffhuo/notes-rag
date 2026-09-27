<script setup>
// 片段级 Markdown 渲染（T3.4 检索命中）。
//
// 只做两件事：把 markdown.js 产出的安全 HTML 放进 DOM，并给一套「片段尺度」的排版
// （标题压到正文字号 —— 一个 `#` 标题不该在命中卡片里撑成大标题）。
// 安全边界（禁原始 HTML、限链接协议）在 markdown.js 里，本组件不重复实现。
//
// 代码块「复制」只能走事件委托：v-html 出来的节点不受 Vue 模板管理，绑不上 @click。
import { computed } from 'vue'
import { copyText } from '../clipboard'
import { renderMarkdown } from '../markdown'

const props = defineProps({
  /** markdown 原文（命中片段的 content）。 */
  source: { type: String, default: '' },
  /** 片段内的图片信息（后端 chunk.metadata["images"]），用于把图片标记还原成可读块。 */
  images: { type: Array, default: () => [] },
})

const html = computed(() => renderMarkdown(props.source, props.images))

/** 复制反馈在按钮上显示多久（毫秒）。 */
const COPIED_HINT_MS = 1500

/**
 * 根元素上的点击委托：命中 .md-copy 就从同容器的 <code> 取文本写入剪贴板。
 *
 * 代码文本不从 data-* 属性读（样式门禁禁用属性选择器），按钮文案直接改 DOM
 * —— 这些节点是 v-html 产物，改 Vue 状态不会重绘它们。
 */
async function onRootClick(event) {
  const btn = event.target?.closest?.('.md-copy')
  if (!btn) return
  const codeEl = btn.closest('.md-code')?.querySelector('code')
  const ok = await copyText(codeEl?.textContent ?? '')
  btn.textContent = ok ? '已复制' : '复制失败'
  window.setTimeout(() => {
    if (btn.isConnected) btn.textContent = '复制'
  }, COPIED_HINT_MS)
}
</script>

<template>
  <!-- v-html 的数据源是 renderMarkdown 的产物：原始 HTML 已转义、链接已限协议 -->
  <div class="app-md" v-html="html" @click="onRootClick"></div>
</template>

<style scoped>
.app-md {
  min-width: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  word-break: break-word;
}

/* v-html 生成的内容拿不到 scoped 属性，只能靠 :deep() 命中 */
.app-md :deep(p) {
  margin: 0 0 var(--space-2);
}
.app-md :deep(:last-child) {
  margin-bottom: 0;
}

/* 标题压到正文尺度：片段里追求的是「结构和正文区分开」，不是层级高低 */
.app-md :deep(h1),
.app-md :deep(h2),
.app-md :deep(h3),
.app-md :deep(h4),
.app-md :deep(h5),
.app-md :deep(h6) {
  margin: var(--space-2) 0 var(--space-1);
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  font-weight: var(--font-weight-semibold);
}

.app-md :deep(ul),
.app-md :deep(ol) {
  margin: 0 0 var(--space-2);
  padding-left: var(--space-4);
}
.app-md :deep(li) {
  margin: 0;
}
.app-md :deep(li + li) {
  margin-top: var(--space-1);
}

.app-md :deep(code) {
  padding: 0 var(--space-1);
  border-radius: var(--radius-sm);
  background: var(--color-bg-subtle);
  color: var(--color-text-primary);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-code);
  line-height: var(--line-height-code);
}
.app-md :deep(pre) {
  margin: 0 0 var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-bg-subtle);
  overflow-x: auto;
}
.app-md :deep(pre code) {
  padding: 0;
  background: transparent;
  white-space: pre;
}

/* 代码块容器：顶部小条（语言 + 复制）与代码区共用一层边框，看起来是一块东西 */
.app-md :deep(.md-code) {
  margin: 0 0 var(--space-2);
  border: var(--border-width) solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.app-md :deep(.md-code pre) {
  margin: 0;
  border-radius: 0;
}
.app-md :deep(.md-code__bar) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-1) var(--space-1) var(--space-3);
  border-bottom: var(--border-width) solid var(--color-border);
  background: var(--color-bg-subtle);
}
.app-md :deep(.md-code__lang) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}
.app-md :deep(.md-copy) {
  flex: none;
  padding: 0 var(--space-2);
  border: var(--border-width) solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: inherit;
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  cursor: pointer;
}
.app-md :deep(.md-copy:hover) {
  border-color: var(--color-border);
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
}

.app-md :deep(blockquote) {
  margin: 0 0 var(--space-2);
  padding: 0 var(--space-3);
  border-left: 3px solid var(--color-border-strong);
  color: var(--color-text-muted);
}

.app-md :deep(table) {
  margin: 0 0 var(--space-2);
  border-collapse: collapse;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}
.app-md :deep(th),
.app-md :deep(td) {
  padding: var(--space-1) var(--space-2);
  border: var(--border-width) solid var(--color-border);
  text-align: left;
}
.app-md :deep(th) {
  background: var(--color-bg-subtle);
  color: var(--color-text-primary);
}

.app-md :deep(a) {
  color: var(--color-primary);
  text-decoration: underline;
}

.app-md :deep(hr) {
  margin: var(--space-2) 0;
  border: 0;
  border-top: var(--border-width) solid var(--color-border);
}
</style>