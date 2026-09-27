<script setup>
// Vault 过滤表单块。
//
// 只配一件事：**不索引哪些内容**。没有「包含规则」这个概念 —— 没被排除的就是要索引的，
// 再加一层白名单只会让「为什么这个文件没进库」变成两道推理。
//
// 为什么是一个文本域而不是若干带 label 的字段：排除项、手写规则、扩展名原本是同一份
// 「过滤清单」的四种呈现，拆成四个控件时改一处另一处就得跟着同步。现在清单只有一份真源
// —— 文本域本身，一行一条（换行或逗号分隔），目录树勾选也往这里追加。
// 扩展名同样是排除规则（`.py` 排除所有 Python 文件），提交前由父组件补成 `*.py`。
//
// v-model 形状：{ exclude: '一行一条的文本', maxKb: '' }
//   exclude 每行是相对 vault 根的 POSIX glob，目录树写 `<目录>/**`（后端按目录前缀剪枝）。
import { ref, watch } from 'vue'
import AppInput from './AppInput.vue'
import AppTextarea from './AppTextarea.vue'
import VaultTreePicker from './VaultTreePicker.vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  /** 目录树要浏览的根目录绝对路径；空则只支持手写规则。 */
  root: { type: String, default: '' },
  /** 本地已知的目录树（上传前由所选文件夹算出）；给定时目录树不再请求后端。 */
  localDirs: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

const m = ref({ ...props.modelValue })
// 记住自己刚发出去的那份，避免「emit → 父组件回传 → 重置本地态」把光标打回开头
let lastEmitted = null

watch(
  () => props.modelValue,
  (v) => {
    if (v !== lastEmitted) m.value = { ...v }
  },
)

function patch(part) {
  m.value = { ...m.value, ...part }
  lastEmitted = { ...m.value }
  emit('update:modelValue', lastEmitted)
}

/** 文本 → 规则数组（换行或中英文逗号分隔），供目录树判断哪些目录已勾选。 */
function rulesOf(text) {
  return String(text || '')
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** 目录树勾选结果 → 文本；树上只增删 `<目录>/**`，手写规则原样保留。 */
function onTreeSelected(list) {
  patch({ exclude: list.join('\n') })
}
</script>

<template>
  <div class="vfilters">
    <AppTextarea
      :model-value="m.exclude"
      label="排除规则"
      :rows="6"
      placeholder="一行一条：notes/private/**、**/*.tmp、.py"
      hint="一行一条，换行或逗号分隔。可写目录（notes/private/**）、路径 glob（**/*.tmp）或扩展名（.py 排除所有 Python 文件）；留空 = 只排除服务端默认目录（node_modules、.git、.obsidian 等）"
      @update:model-value="(v) => patch({ exclude: v })"
    />

    <VaultTreePicker
      :root="root"
      :local-dirs="localDirs"
      :selected="rulesOf(m.exclude)"
      @update:selected="onTreeSelected"
    />

    <AppInput
      :model-value="m.maxKb"
      type="number"
      label="单文件大小上限（KB）"
      placeholder="例如 2048"
      hint="超过则跳过；留空 = 用服务端默认（10 MB）"
      @update:model-value="(v) => patch({ maxKb: v })"
    />
  </div>
</template>

<style scoped>
.vfilters {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}
</style>
