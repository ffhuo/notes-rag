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

/** 统计待打包的文件：数量与原始总体积（确认弹窗与进度条都用它）。 */
export function summarize(files) {
  const list = Array.from(files || []).filter((f) => relOf(f) && !isJunk(relOf(f)))
  let bytes = 0
  for (const f of list) bytes += f.size || 0
  return { count: list.length, bytes, list }
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
 * @returns {Promise<Blob>} `application/zip`
 */
export function packFolder(files, onProgress) {
  const { list } = summarize(files)
  const strip = topSegment(list)

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
      for (const file of list) {
        let path = relOf(file)
        if (strip && path.startsWith(`${strip}/`)) path = path.slice(strip.length + 1)
        if (!path) continue

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
