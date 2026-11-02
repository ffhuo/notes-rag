import { computed, onScopeDispose, ref, watch } from 'vue'
import { vaultsApi } from '../api'

const PAGE_SIZE = 20

export function useVaultFiles(vaultId) {
  const search = ref('')
  const status = ref('all')
  const page = ref(1)
  const result = ref({ files: [], total: 0, counts: {}, scan_complete: true })
  const loading = ref(false)
  const error = ref('')
  let requestId = 0
  let debounceTimer

  async function load() {
    const id = vaultId.value
    if (!id) {
      result.value = { files: [], total: 0, counts: {}, scan_complete: true }
      error.value = ''
      return
    }

    const currentRequestId = ++requestId
    loading.value = true
    error.value = ''
    try {
      const response = await vaultsApi.listFiles(id, {
        page: page.value,
        page_size: PAGE_SIZE,
        search: search.value,
        status: status.value,
      })
      if (currentRequestId === requestId) result.value = response
    } catch (cause) {
      if (currentRequestId === requestId) {
        error.value = cause?.message || '无法读取文件清单'
      }
    } finally {
      if (currentRequestId === requestId) loading.value = false
    }
  }

  watch(
    [vaultId, page, search, status],
    ([id], previous) => {
      if (previous && id !== previous[0]) {
        page.value = 1
        search.value = ''
        status.value = 'all'
      }
      requestId += 1
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(load, search.value ? 250 : 0)
    },
    { immediate: true },
  )

  onScopeDispose(() => {
    clearTimeout(debounceTimer)
    requestId += 1
  })

  return {
    files: computed(() => result.value.files),
    total: computed(() => result.value.total),
    counts: computed(() => result.value.counts),
    scanComplete: computed(() => result.value.scan_complete),
    page,
    pageSize: PAGE_SIZE,
    search,
    status,
    loading,
    error,
    refresh: load,
  }
}
