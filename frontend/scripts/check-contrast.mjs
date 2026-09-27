// 主题对比度门禁（T4.3 / 规范 §2.8、§7）。
//
// 为什么必须在构建期跑：任意一个品牌色在深/浅底上掉到 4.5:1 以下，组件侧无法补救
// （组件只认语义令牌，不认识具体色值）。10 组组合的准入条件只能在令牌层守住。
//
// 校验项（§2.8 门禁列）：
//   1) --brand-primary 对 --color-bg-page          ≥ 4.5:1
//   2) --brand-accent  对 --brand-accent-on        ≥ 4.5:1
//   3) --color-text-primary 对 --color-bg-page     ≥ 4.5:1
// 附带校验（§7 检查单）：
//   4) --color-primary-contrast 对 --color-primary ≥ 4.5:1（主色按钮上的文字）
//   5) --color-danger-contrast 对 --color-danger   ≥ 4.5:1（危险按钮上的文字）
// 仅告警（§2.8 未列入门禁）：
//   6) --brand-primary-on-soft 对 --brand-primary-soft ≥ 4.5:1
//
// 用法：node scripts/check-contrast.mjs    （失败 exit 1，供 make 门禁调用）
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const CSS_PATH = resolve(HERE, '../src/styles/tokens.css')

const BRANDS = ['blue', 'indigo', 'teal', 'slate', 'violet']
const SCHEMES = ['light', 'dark']

/* ---------- 解析 tokens.css ---------- */

/** 去掉注释后再按「选择器 { 声明 }」切块（注释里有中文全角符号，先剥离最稳）。
    选择器含逗号时逐个登记（如 `:root, .scheme-light`），否则该块会被当成新键漏读。 */
function parseBlocks(css) {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const blocks = new Map()
  const re = /([^{}]+)\{([^{}]*)\}/g
  let m
  while ((m = re.exec(clean)) !== null) {
    const decls = {}
    for (const part of m[2].split(';')) {
      const i = part.indexOf(':')
      if (i === -1) continue
      const key = part.slice(0, i).trim()
      if (key.startsWith('--')) decls[key] = part.slice(i + 1).trim()
    }
    for (const selector of m[1].split(',').map((s) => s.trim()).filter(Boolean)) {
      blocks.set(selector, { ...(blocks.get(selector) || {}), ...decls })
    }
  }
  return blocks
}

/** 该「品牌 × 明暗」组合实际生效的层叠顺序。 */
function layersFor(brand, scheme) {
  const layers = [':root']
  if (scheme === 'dark') {
    layers.push('.scheme-dark')
    if (brand !== 'blue') layers.push(`.scheme-dark.brand-${brand}`)
  } else {
    layers.push('.scheme-light')
    if (brand !== 'blue') layers.push(`.brand-${brand}`)
  }
  return layers
}

function resolveTokens(blocks, brand, scheme) {
  const merged = {}
  for (const selector of layersFor(brand, scheme)) {
    Object.assign(merged, blocks.get(selector) || {})
  }
  // 语义层只写 `var(--brand-*)`，比对前必须展开成具体色值
  for (let pass = 0; pass < 5; pass += 1) {
    let changed = false
    for (const [k, v] of Object.entries(merged)) {
      const m = /^var\((--[\w-]+)\)$/.exec(v)
      if (!m) continue
      const target = merged[m[1]]
      if (target !== undefined && target !== v) {
        merged[k] = target
        changed = true
      }
    }
    if (!changed) break
  }
  return merged
}

/* ---------- WCAG 相对亮度与对比度 ---------- */

function hexToRgb(hex) {
  const h = hex.trim().replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
}

function luminance([r, g, b]) {
  const f = (c) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

function contrast(fg, bg) {
  const a = hexToRgb(fg)
  const b = hexToRgb(bg)
  if (!a || !b) return null
  const la = luminance(a)
  const lb = luminance(b)
  const [hi, lo] = la > lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

/* ---------- 校验 ---------- */

const REQUIRED = [
  { fg: '--brand-primary', bg: '--color-bg-page', min: 4.5, short: 'primary/bg', label: 'primary / bg-page' },
  { fg: '--brand-accent', bg: '--brand-accent-on', min: 4.5, short: 'accent/on', label: 'accent / accent-on' },
  { fg: '--color-text-primary', bg: '--color-bg-page', min: 4.5, short: 'text/bg', label: 'text-primary / bg-page' },
  // 主色 / 危险色底上的文字：深色主题品牌色会提亮，白字会掉到 3:1 以下，故单独守
  { fg: '--color-primary-contrast', bg: '--color-primary', min: 4.5, short: 'primaryCon', label: 'primary-contrast / primary' },
  { fg: '--color-danger-contrast', bg: '--color-danger', min: 4.5, short: 'dangerCon', label: 'danger-contrast / danger' },
]

const ADVISORY = [
  { fg: '--brand-primary-on-soft', bg: '--brand-primary-soft', min: 4.5, short: 'on-soft', label: 'primary-on-soft / primary-soft' },
]

const COL = 13

function fmt(n) {
  return (n === null ? 'n/a' : n.toFixed(2)).padStart(COL)
}

function main() {
  const blocks = parseBlocks(readFileSync(CSS_PATH, 'utf8'))
  const failures = []
  const warnings = []

  console.log(`主题对比度校验：${CSS_PATH}\n`)
  console.log(
    '组合'.padEnd(20) +
      REQUIRED.map((r) => r.short.padStart(COL)).join('') +
      ADVISORY.map((r) => r.short.padStart(COL)).join(''),
  )

  for (const brand of BRANDS) {
    for (const scheme of SCHEMES) {
      const tokens = resolveTokens(blocks, brand, scheme)
      const name = `${brand} × ${scheme}`

      const cells = []
      for (const rule of REQUIRED) {
        const fg = tokens[rule.fg]
        const bg = tokens[rule.bg]
        if (!fg || !bg) {
          failures.push(`${name}：缺少令牌 ${rule.fg} 或 ${rule.bg}`)
          cells.push(fmt(null))
          continue
        }
        const ratio = contrast(fg, bg)
        if (ratio === null) {
          failures.push(`${name}：${rule.label} 的色值不是可解析的十六进制（${fg} / ${bg}）`)
          cells.push(fmt(null))
          continue
        }
        cells.push(fmt(ratio))
        if (ratio < rule.min) {
          failures.push(`${name}：${rule.label} 对比度 ${ratio.toFixed(2)}:1 < ${rule.min}:1`)
        }
      }

      const advisory = ADVISORY.map((rule) => {
        const ratio = contrast(tokens[rule.fg], tokens[rule.bg])
        if (ratio !== null && ratio < rule.min) {
          warnings.push(`${name}：${rule.label} 对比度 ${ratio.toFixed(2)}:1 < ${rule.min}:1`)
        }
        return fmt(ratio)
      })

      console.log(name.padEnd(20) + cells.join('') + advisory.join(''))
    }
  }

  console.log('')

  if (warnings.length) {
    console.log(`告警 ${warnings.length} 项（未列入 §2.8 门禁，仅提示）：`)
    for (const w of warnings) console.log(`  · ${w}`)
    console.log('')
  }

  if (failures.length) {
    console.error(`门禁未通过：${failures.length} 项`)
    for (const f of failures) console.error(`  ✗ ${f}`)
    process.exit(1)
  }

  console.log(`门禁通过：${BRANDS.length * SCHEMES.length} 组组合的必检项全部 ≥ 4.5:1`)
}

main()
