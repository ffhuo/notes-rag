// 本地文件夹 → zip 包（上传传输层的一部分，T5.2 / 规范 §6.5）。
//
// 为什么需要：后端 /vaults/upload 只认 .zip（Python zipfile 解压，见 vault_service.save_upload），
// 而浏览器没有生成 zip 的原生 API；用 fflate 在本地打包，用户就不必先手动压一遍再选包。
//
// 为什么剥掉顶层目录名：webkitdirectory 给出的 webkitRelativePath 一定以**所选文件夹名**打头
// （选 `notes` → 条目是 `notes/a.md`），照原样入包会让索引出来的目录树凭空多一层壳。
//
// 为什么用流式 Zip 而不是 zipSync：要按文件回报进度 —— 大目录要等几秒到几十秒，
// 没有进度用户会以为页面卡死；同时避免一次性构造完整输出缓冲。
import { Zip, ZipDeflate } from 'fflate'

/** 超过阈值先让调用方与用户确认：整目录要读进内存压缩，误选整个 home 目录会把页面卡死。 */
export const PACK_LIMITS = { files: 3000, bytes: 300 * 1024 * 1024 }

/** 只丢系统垃圾文件，其余一律保留 —— 是否索引由后端 filters 决定，前端不做业务判断。 */
function isJunk(path) {
  return path.split('/').some((seg) => seg === '__MACOSX' || seg === '.DS_Store')
}

function relOf(file) {
  return (file.webkitRelativePath || file.name || '').replace(/^\/+/, '')
}

/** 纯扩展名写法（`.py` / `.md`）—— 与 VaultManager.normalizeRule 同一条规则。 */
const EXT_ONLY = /^\.[A-Za-z0-9]+$/

/**
 * 表单里的排除规则 → 归一化规则数组。
 *
 * exclude 在表单态是「一行一条」的文本，落库后是数组，两种都要能吃。
 * `.py` 补成 `*.py`：后端 fnmatch 的 `*` 跨 `/`，这样才等于「排除所有 .py」。
 */
function excludeRules(filters) {
  const raw = filters?.exclude
  const list = Array.isArray(raw) ? raw : String(raw || '').split(/[,，\n]/)
  return list
    .map((s) => String(s).trim())
    .filter(Boolean)
    .map((rule) => (EXT_ONLY.test(rule) ? `*${rule}` : rule))
}

/** 从规则里取「整目录排除」前缀（`dir/**`、`dir/`），用于目录级剪枝。 */
function dirPrefixes(rules) {
  const out = []
  for (const rule of rules) {
    let prefix = ''
    if (rule.endsWith('/**')) prefix = rule.slice(0, -3)
    else if (rule.endsWith('/')) prefix = rule.replace(/\/+$/, '')
    else continue
    if (prefix.startsWith('./')) prefix = prefix.slice(2)
    if (prefix && !/[*?[\]]/.test(prefix)) out.push(prefix)
  }
  return out
}

/** glob → 正则：与后端 fnmatch 对齐的主要语义（`*` 跨 `/`、`?` 单字符）。 */
function globToRegExp(pattern) {
  let body = ''
  for (const ch of pattern) {
    if (ch === '*') body += '.*'
    else if (ch === '?') body += '.'
    else body += ch.replace(/[.+^${}()|[\]\\]/g, '\\$&')
  }
  return new RegExp(`^${body}$`)
}

/** 该相对路径是否被排除（目录前缀剪枝 + 文件级 glob 兜底）。 */
function isExcluded(path, rules, prefixes) {
  if (prefixes.some((p) => path === p || path.startsWith(`${p}/`))) return true
  return rules.some((rule) => globToRegExp(rule).test(path))
}

/** 隐藏目录不打包：与服务端扫描一致（`d.startswith(".")` 的目录整棵跳过）。 */
function hasHiddenDir(path) {
  return path
    .split('/')
    .slice(0, -1)
    .some((seg) => seg.startsWith('.'))
}

/**
 * 待打包清单：丢掉系统垃圾、隐藏目录，以及被 filters 排除的文件。
 *
 * 排除项在**打包前**就剔除，而不是只让后端索引时跳过 —— 被过滤的内容没有
 * 上传价值，传上去既浪费带宽与磁盘，重新同步时还要再扫一遍。
 * 注意：单文件大小上限（max_file_size）仍只在索引阶段生效 —— 大文件可能
 * 被 get_note 或图片处理读取，不能在打包时就丢掉。
 *
 * 返回的文件已剥掉「所选文件夹名」这一层，path 即 vault 根下的相对路径。
 */
function buildList(files, filters) {
  const raw = Array.from(files || []).filter((f) => relOf(f) && !isJunk(relOf(f)))
  const strip = topSegment(raw)
  const rules = excludeRules(filters)
  const prefixes = dirPrefixes(rules)

  const list = []
  for (const file of raw) {
    let path = relOf(file)
    if (strip && path.startsWith(`${strip}/`)) path = path.slice(strip.length + 1)
    if (!path || hasHiddenDir(path) || isExcluded(path, rules, prefixes)) continue
    list.push({ file, path })
  }
  return list
}

/** 统计待打包的文件：数量与原始总体积（确认弹窗、进度条与摘要都用它）。 */
export function summarize(files, filters) {
  const list = buildList(files, filters)
  let bytes = 0
  for (const { file } of list) bytes += file.size || 0
  return { count: list.length, bytes }
}

/** 所有条目是否共享同一个顶层目录段；是则返回它（用于剥离），否则返回 null。 */
function topSegment(list) {
  let top = null
  for (const f of list) {
    const seg = relOf(f).split('/')[0]
    if (!seg) return null
    if (top === null) top = seg
    else if (top !== seg) return null
  }
  return top
}

/** 人类可读体积（列表摘要与确认弹窗共用，避免两处各写一套换算）。 */
export function formatBytes(bytes) {
  const n = Number(bytes) || 0
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(n / 1024))} KB`
}

/**
 * 把所选文件夹打包成 zip 字节流。
 *
 * @param {FileList|File[]} files 来自 `<input type="file" webkitdirectory>` 的选择结果
 * @param {(done: number, total: number) => void} [onProgress] 每处理完一个文件回调一次
 * @param {{exclude?: string|string[]}} [filters] 排除规则（目录/glob），命中项不入包
 * @returns {Promise<Blob>} `application/zip`
 */
export function packFolder(files, onProgress, filters) {
  const list = buildList(files, filters)

  return new Promise((resolve, reject) => {
    const chunks = []
    const stream = new Zip((err, chunk, final) => {
      if (err) {
        reject(err)
        return
      }
      if (chunk && chunk.length) chunks.push(chunk)
      if (final) resolve(new Blob(chunks, { type: 'application/zip' }))
    })

    ;(async () => {
      let done = 0
      for (const { file, path } of list) {
        const entry = new ZipDeflate(path, { level: 6 })
        stream.add(entry)
        entry.push(new Uint8Array(await file.arrayBuffer()), true)

        done += 1
        if (onProgress) onProgress(done, list.length)
      }
      stream.end()
    })().catch(reject)
  })
}
