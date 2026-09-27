import { shallowRef } from 'vue'

// 顶栏「页面级主操作」区（规范 §3.1：Topbar 承载「页面标题 + 页面级主操作」）。
//
// 为什么用响应式描述表而不是 <Teleport>：小程序没有 DOM 传送能力，Teleport 无法迁移
// （规范 §6.1「只用 Flex + 令牌 + 单层类名」的跨端子集思路）。描述表是纯数据，
// 各端都能渲染。
//
// 页面用法（在 setup 内，顺序即渲染顺序）：
//   import { onUnmounted } from 'vue'
//   import AppButton from './AppButton.vue'
//   import { setTopbarActions, clearTopbarActions } from '../shell'
//
//   setTopbarActions([
//     { key: 'create', comp: AppButton, props: { variant: 'primary', icon: 'plus' },
//       on: { click: () => (showCreate.value = true) }, text: '新建 Vault' },
//   ])
//   onUnmounted(clearTopbarActions)      // 路由切换卸载时清空，避免上一页操作残留
//
// 描述项：key（必需，渲染 key）· comp（组件）· props（属性）· on（事件）· text（默认插槽文本）

const topbarActions = shallowRef([])

export function setTopbarActions(list) {
  // 归一化：渲染端直接 v-bind / v-on，缺省字段补空对象，避免 spread undefined
  topbarActions.value = (Array.isArray(list) ? list : []).map((a) => ({
    key: a.key,
    comp: a.comp,
    props: a.props || {},
    on: a.on || {},
    text: a.text,
  }))
}

export function clearTopbarActions() {
  topbarActions.value = []
}

/** 供 AppShell 读取渲染。 */
export function useTopbarActions() {
  return topbarActions
}
