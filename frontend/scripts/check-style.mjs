// 样式合规扫描（T5.4 / 规范 §6.1）。
//
// 目的：把「小程序 / RN 表达不了」的 CSS 特性挡在提交之前。这类问题不会在本端报错，
// 只会在迁移时集中爆发，所以必须静态拦。
//
// 扫描范围：frontend/src 下的 .vue（template + script + style）/ .css / .js
//   ✗ 错误（§6.1 明确不支持）：CSS Grid、:has/:is/:where、backdrop-filter、
//     color-mix/lighten/darken、clip-path、mask、[data-*] 属性选择器、system-ui、
//     CSS 嵌套（&）、样式中的硬编码十六进制色值（tokens.css 除外，它是令牌唯一来源）
//   △ 告警（兼容性不稳）：position: sticky、组合选择器 > ~
//
// 用法：node scripts/check-style.mjs
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(HERE, '../src')
const TOKENS_FILE = resolve(SRC, 'styles/tokens.css')

const EXTS = ['.vue', '.css', '.js']

const ERRORS = [
  { re: /display\s*:\s*(inline-)?grid\b/g, msg: 'CSS Grid（§6.1）→ 用 Flexbox' },
  { re: /grid-template\w*/g, msg: 'CSS Grid（§6.1）→ 用 Flexbox' },
  { re: /:has\s*\(/g, msg: ':has()（§6.1）→ 显式类名' },
  { re: /:is\s*\(/g, msg: ':is()（§6.1）→ 显式类名' },
  { re: /:where\s*\(/g, msg: ':where()（§6.1）→ 显式类名' },
  { re: /backdrop-filter\s*:/g, msg: 'backdrop-filter（§6.1）→ 不透明背景' },
  { re: /color-mix\s*\(/g, msg: 'color-mix()（§6.1）→ 显式给出派生色' },
  { re: /\blighten\s*\(|\bdarken\s*\(/g, msg: 'lighten()/darken()（§6.1）→ 显式给出派生色' },
  { re: /clip-path\s*:/g, msg: 'clip-path（§6.1）→ 预裁切资源' },
  { re: /(-webkit-)?mask\s*:/g, msg: 'mask（§6.1）→ 预裁切资源' },
  { re: /\[data-[\w-]+\]/g, msg: '[data-*] 属性选择器（§6.1）→ 用 class' },
  { re: /system-ui/g, msg: 'system-ui 字族（§6.1）→ 显式字族栈' },
  { re: /^\s*&\s*[:.\w[]/gm, msg: 'CSS 嵌套 &（§6.1）→ 扁平选择器' },
]

const WARNINGS = [
  { re: /position\s*:\s*sticky/g, msg: 'position: sticky（§6.1）→ fixed + 占位' },
]

const HEX = /#[0-9a-fA-F]{3,8}\b/g

/* ---------- 收集文件 ---------- */

function walk(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else if (EXTS.some((e) => entry.endsWith(e))) out.push(full)
  }
  return out
}

function lineOf(text, index) {
  let line = 1
  for (let i = 0; i < index; i += 1) if (text[i] === '\n') line += 1
  return line
}

/** 把 CSS 注释替换为等长空白（保留换行与索引），
    否则注释里「不要用 color-mix()」这类说明文字会被规则当成真实用法。 */
function maskComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
}

/** 返回一份「只有 CSS 部分」的等长视图（非样式区域置为空白）。
    · .css → 全文
    · .vue → 仅各 <style> 块，template / script 不套用 CSS 规则
    · .js  → 空（脚本里不写 CSS，扫描会产出大量误报）
    等长是为了让命中位置仍能换算出原文件行号。 */
function cssOnlyView(file, text) {
  if (file.endsWith('.css')) return text
  if (!file.endsWith('.vue')) return ' '.repeat(text.length)

  const buf = text.split('')
  const blank = (from, to) => {
    for (let i = from; i < to; i += 1) if (buf[i] !== '\n') buf[i] = ' '
  }
  const re = /<style[^>]*>([\s\S]*?)<\/style>/g
  let m
  let cursor = 0
  while ((m = re.exec(text)) !== null) {
    const body = m[1]
    const bodyStart = m.index + m[0].indexOf(body)
    blank(cursor, bodyStart)          // 含 <style ...> 开标签
    cursor = bodyStart + body.length  // 保留块内 CSS，</style> 归入下一次置空
  }
  blank(cursor, text.length)
  return buf.join('')
}

/** 从样式文本里抽出选择器（到 { 之前的那段，排除 @ 规则）。 */
function selectorsOf(cssText) {
  const found = []
  const re = /(^|[};])([^{}@;]*)\{/g
  let m
  while ((m = re.exec(cssText)) !== null) {
    const selector = m[2].trim()
    if (selector && !selector.startsWith('@')) found.push({ selector, index: m.index })
  }
  return found
}

/* ---------- 扫描 ---------- */

const errors = []
const warnings = []

for (const file of walk(SRC)) {
  const raw = readFileSync(file, 'utf8')
  const rel = relative(resolve(HERE, '..'), file)
  const isTokens = resolve(file) === TOKENS_FILE

  // CSS 规则只在样式区域上跑；全文（含 script）只用于硬编码色值检查
  const css = maskComments(cssOnlyView(file, raw))
  const whole = maskComments(raw)

  for (const { re, msg } of ERRORS) {
    re.lastIndex = 0
    let m
    while ((m = re.exec(css)) !== null) {
      errors.push(`${rel}:${lineOf(css, m.index)}  ${msg}`)
    }
  }

  for (const { re, msg } of WARNINGS) {
    re.lastIndex = 0
    let m
    while ((m = re.exec(css)) !== null) {
      warnings.push(`${rel}:${lineOf(css, m.index)}  ${msg}`)
    }
  }

  // 硬编码色值：只允许出现在 tokens.css（令牌唯一来源，§1）
  if (!isTokens) {
    HEX.lastIndex = 0
    let m
    while ((m = HEX.exec(whole)) !== null) {
      errors.push(`${rel}:${lineOf(whole, m.index)}  硬编码色值 ${m[0]}（§1 令牌唯一来源）`)
    }
  }

  // 组合选择器（只看样式区域的选择器段，避免把 JS 的 > 比较误判）
  for (const { selector } of selectorsOf(css)) {
    if (selector.includes('>') || selector.includes('~')) {
      warnings.push(`${rel}  组合选择器「${selector.replace(/\s+/g, ' ').slice(0, 60)}」（§6.1）`)
    }
  }
}

/* ---------- 报告 ---------- */

const uniq = (list) => [...new Set(list)]

const errs = uniq(errors)
const warns = uniq(warnings)

console.log(`样式合规扫描：${SRC}\n`)

if (warns.length) {
  console.log(`告警 ${warns.length} 项（兼容性不稳，建议改）：`)
  for (const w of warns) console.log(`  △ ${w}`)
  console.log('')
}

if (errs.length) {
  console.error(`门禁未通过：${errs.length} 项禁用特性`)
  for (const e of errs) console.error(`  ✗ ${e}`)
  process.exit(1)
}

console.log('门禁通过：未发现 §6.1 禁用特性与硬编码色值')
