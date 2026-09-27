// 令牌导出（T5.3 / 规范 §6.3）：把 tokens.css 的 L2 / L3 令牌导出给小程序与 RN。
//
// 为什么需要：换端时**只改令牌这一层**（§6.3 令牌映射表），组件样式与组件契约保持不变。
// 本脚本是那次迁移的起点，不是运行时依赖 —— 导出的文件不入库，随时可重生成。
//
// 产出（frontend/tokens/）：
//   · tokens.rpx.css  —— 选择器结构与 tokens.css 一致，px 全部换算为 rpx（1px = 2rpx）
//   · tokens.theme.ts —— RN / TS 用的主题对象，px 换算为无单位数值
//
// 用法：node scripts/export-tokens.mjs
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC_FILE = resolve(HERE, '../src/styles/tokens.css')
const OUT_DIR = resolve(HERE, '../tokens')

/** 小程序 rpx 与设计稿 px 的换算比（750rpx 设计宽 → 375px 视口）。 */
const RPX_PER_PX = 2

/** 品牌与明暗的组合（与 tokens.css 的选择器一一对应）。 */
const BRANDS = ['blue', 'indigo', 'teal', 'slate', 'violet']

/* ---------- 解析 ---------- */

/** 剥掉注释：注释里出现的示例声明不能当成真实令牌。 */
const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, '')

/**
 * 解析出 [{ selector, decls: Map }]，只保留 `--*` 自定义属性。
 * 同一选择器可能出现多次（tokens.css 的 :root 分品牌层与语义层两段），保持顺序、后写覆盖。
 */
function parseBlocks(css) {
  const blocks = []
  const re = /([^{}]+)\{([^{}]*)\}/g
  let m
  while ((m = re.exec(css)) !== null) {
    const decls = new Map()
    for (const part of m[2].split(';')) {
      const i = part.indexOf(':')
      if (i === -1) continue
      const name = part.slice(0, i).trim()
      if (!name.startsWith('--')) continue
      decls.set(name, part.slice(i + 1).trim())
    }
    if (decls.size) blocks.push({ selector: m[1].trim(), decls })
  }
  return blocks
}

/** 按选择器顺序合并若干块的声明（后面的覆盖前面的）。 */
function mergeDecls(blocks, selectors) {
  const out = new Map()
  for (const b of blocks) {
    if (!selectors.includes(b.selector)) continue
    for (const [k, v] of b.decls) out.set(k, v)
  }
  return out
}

/**
 * 把 `var(--x)` 展开为实际值。
 * WXSS / 浏览器会自己解析 var()，但 RN 与 TS 不会 —— 那边必须拿到终值。
 * 迭代到稳定（存在 L4 → L3 → L2 的多级引用），带轮次上限防引用成环。
 */
function resolveVars(decls) {
  const out = new Map(decls)
  for (let pass = 0; pass < 5; pass += 1) {
    let changed = false
    for (const [k, v] of out) {
      const m = /^var\((--[\w-]+)\)$/.exec(v)
      if (!m) continue
      const target = out.get(m[1])
      if (target !== undefined && target !== v) {
        out.set(k, target)
        changed = true
      }
    }
    if (!changed) break
  }
  return out
}

/* ---------- 换算 ---------- */

/** px → rpx，用于小程序 WXSS。 */
const pxToRpx = (value) =>
  value.replace(/(-?\d*\.?\d+)px\b/g, (_, n) => `${Number(n) * RPX_PER_PX}rpx`)

/** 纯 px 值 → 无单位数字（RN 数值型样式）；其余保持字符串。 */
function toTsValue(value) {
  const px = value.match(/^(-?\d*\.?\d+)px$/)
  if (px) return String(Number(px[1]))
  return JSON.stringify(value)
}

/** `--color-primary-hover` → `colorPrimaryHover`。 */
const toCamel = (name) => name.replace(/^--/, '').replace(/-(\w)/g, (_, c) => c.toUpperCase())

const HEADER = `/* 本文件由 frontend/scripts/export-tokens.mjs 自动生成，请勿手改。
   来源：frontend/src/styles/tokens.css（规范 docs/ui-spec.md §6.3） */`

const TS_HEADER = `// 本文件由 frontend/scripts/export-tokens.mjs 自动生成，请勿手改。
// 来源：frontend/src/styles/tokens.css（规范 docs/ui-spec.md §6.3）
// px 已换算为无单位数值；RN 数值型样式可直接使用，Web 端需自行拼 'px'。`

/* ---------- 生成 ---------- */

const blocks = parseBlocks(stripComments(readFileSync(SRC_FILE, 'utf8')))

/** 每个选择器块原样输出，仅把 px 换成 rpx。 */
function buildRpxCss() {
  const body = blocks
    .map((b) => {
      const lines = [...b.decls].map(([k, v]) => `  ${k}: ${pxToRpx(v)};`)
      return `${b.selector} {\n${lines.join('\n')}\n}`
    })
    .join('\n\n')
  return `${HEADER}\n\n${body}\n`
}

function declsToTsObject(decls, indent = '  ') {
  return [...decls]
    .map(([k, v]) => `${indent}${toCamel(k)}: ${toTsValue(v)},`)
    .join('\n')
}

/** RN / TS 主题：默认（blue × light）、深色（blue × dark）、以及 10 组品牌层 8 值。 */
function buildTsTheme() {
  const light = resolveVars(mergeDecls(blocks, [':root']))
  const dark = resolveVars(mergeDecls(blocks, [':root', '.scheme-dark']))

  const brandThemes = []
  for (const brand of BRANDS) {
    const lightSel = brand === 'blue' ? [':root'] : [`.brand-${brand}`]
    const darkSel = brand === 'blue' ? ['.scheme-dark'] : ['.scheme-dark', `.scheme-dark.brand-${brand}`]
    const lightBrand = new Map([...mergeDecls(blocks, lightSel)].filter(([k]) => k.startsWith('--brand-')))
    const darkBrand = new Map([...mergeDecls(blocks, darkSel)].filter(([k]) => k.startsWith('--brand-')))
    brandThemes.push(`  '${brand}-light': {\n${declsToTsObject(lightBrand, '    ')}\n  },`)
    brandThemes.push(`  '${brand}-dark': {\n${declsToTsObject(darkBrand, '    ')}\n  },`)
  }

  return `${TS_HEADER}

/** 默认主题（blue × light）的全部令牌。 */
export const tokens = {
${declsToTsObject(light)}
} as const

/** 深色主题（blue × dark）：品牌值已提亮，中性色与状态色同步切换。 */
export const darkTokens = {
${declsToTsObject(dark)}
} as const

/** 品牌层（L2）：主题切换只需替换这 8 个值，与换端互不影响（§6.3）。 */
export const brandThemes = {
${brandThemes.join('\n')}
} as const
`
}

/* ---------- 落盘 ---------- */

mkdirSync(OUT_DIR, { recursive: true })

const rpxPath = resolve(OUT_DIR, 'tokens.rpx.css')
const tsPath = resolve(OUT_DIR, 'tokens.theme.ts')

writeFileSync(rpxPath, buildRpxCss(), 'utf8')
writeFileSync(tsPath, buildTsTheme(), 'utf8')

console.log(`令牌导出完成：${blocks.length} 个选择器块`)
console.log(`  · tokens/tokens.rpx.css   （px → rpx，小程序 WXSS）`)
console.log(`  · tokens/tokens.theme.ts  （${BRANDS.length * 2} 组品牌主题 + 明暗全集，RN / TS）`)
