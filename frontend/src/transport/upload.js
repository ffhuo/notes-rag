// vault 上传传输抽象（T5.2 / 规范 §6.5）。
//
// 为什么单独一层：Web 用 FormData + fetch；小程序用 wx.uploadFile、RN 用其自有上传。
// 页面只关心「把文件夹交上去并拿到 vault」，端的差异（含要不要本地打包）关在这里。
// 与 transport/chat.js 同一策略：**页面不直接认识平台的网络 API**。
import { vaultsApi } from '../api'
import { packFolder } from './zip'

/**
 * 把所选文件夹打包成 zip 再上传（source_type=uploaded）。
 *
 * 用户不再需要自己先压好包 —— 选目录即可；顶层文件夹名会在打包时剥掉，
 * 使 vault 的根就是所选目录本身（否则目录树会多一层同名壳）。
 *
 * @param {string} name vault 名称
 * @param {FileList|File[]} files `<input type="file" webkitdirectory>` 的选择结果
 * @param {(done: number, total: number) => void} [onProgress] 打包进度（按文件数）
 * @returns {Promise<object>} 后端 201 响应体（VaultOut）
 */
export async function uploadVault(name, files, onProgress) {
  const blob = await packFolder(files, onProgress)
  const safe = String(name || 'vault').replace(/[\\/:*?"<>|]/g, '_')
  return vaultsApi.upload(name, blob, `${safe}.zip`)
}

/**
 * 重新上传文件，整包替换已有 uploaded vault 的内容。
 *
 * 与 uploadVault 的区别只在目标端点：这里是「更新已有库」，不新建实体，
 * 因此不需要 name。上传成功后调用方仍需提交一次 sync 才能让索引跟上。
 *
 * @param {{id: number, name: string}} vault 目标 vault
 * @param {FileList|File[]} files `<input type="file" webkitdirectory>` 的选择结果
 * @param {(done: number, total: number) => void} [onProgress] 打包进度（按文件数）
 * @returns {Promise<object>} 后端响应体（VaultOut）
 */
export async function updateVaultFiles(vault, files, onProgress) {
  const blob = await packFolder(files, onProgress)
  const safe = String(vault?.name || `vault-${vault?.id}`).replace(/[\\/:*?"<>|]/g, '_')
  return vaultsApi.replaceUpload(vault.id, blob, `${safe}.zip`)
}

export const uploadTransport = {
  uploadVault,
  updateVaultFiles,
}
