<script setup>
// 鉴权弹窗（docs/design.md §17.3）—— 覆盖三种必须提供凭据的情形：
//   多用户未登录 → 登录 / 注册
//   单用户配了 API_KEY → 填 Key
//   模式探测失败 → 提示重试
//
// 单用户且未配 KEY 时不会出现（后端本机免鉴权，直接进主界面）。
// 弹窗**不可关闭**：没有凭据时页面任何请求都会 401，放行只会让用户满屏报错。
import { computed, ref, watch } from 'vue'
import { authState, initAuth, login, register, useApiKey } from '../auth'
import AppButton from './AppButton.vue'
import AppInput from './AppInput.vue'
import AppOverlay from './AppOverlay.vue'

const visible = computed(() => authState.status !== 'ok')
const isApiKey = computed(() => authState.status === 'api-key')
const isError = computed(() => authState.status === 'error')
const isMultiuser = computed(() => authState.multiuser)

/** 多用户下的两种表单；单用户模式只会用到 API Key 分支。 */
const tab = ref('login') // login | register
const isRegister = computed(() => isMultiuser.value && tab.value === 'register')

const username = ref('')
const password = ref('')
const confirm = ref('')
const apiKey = ref('')
const submitting = ref(false)
const error = ref('')

const title = computed(() => {
  if (isError.value) return '连接失败'
  if (isApiKey.value) return '填写 API Key'
  return isRegister.value ? '注册账号' : '登录'
})

const submitText = computed(() => {
  if (isError.value) return '重试'
  if (isApiKey.value) return '确认'
  return isRegister.value ? '注册并进入' : '登录'
})

/** 把 HTTP 状态翻译成用户能照做的说明，而不是抛一串英文。 */
function messageOf(e) {
  const status = e?.status
  if (status === 401) return isApiKey.value ? 'API Key 不正确' : '用户名或密码错误'
  if (status === 403) return '服务端不是多用户模式，请刷新页面重新探测'
  if (status === 409) return '用户名已存在，换一个试试'
  if (status === 500) return '服务端未配置 JWT_SECRET，无法签发登录令牌'
  return e?.message || '请求失败，请稍后重试'
}

watch([tab, () => authState.status], () => {
  error.value = ''
})

async function submit() {
  if (submitting.value) return
  error.value = ''

  if (isError.value) {
    submitting.value = true
    await initAuth()
    submitting.value = false
    return
  }

  if (isApiKey.value) {
    if (!apiKey.value.trim()) {
      error.value = '请输入 API Key'
      return
    }
    submitting.value = true
    try {
      await useApiKey(apiKey.value)
      apiKey.value = ''
    } catch (e) {
      error.value = messageOf(e)
    } finally {
      submitting.value = false
    }
    return
  }

  if (!username.value.trim()) {
    error.value = '请输入用户名'
    return
  }
  if (!password.value) {
    error.value = '请输入密码'
    return
  }
  if (isRegister.value && password.value !== confirm.value) {
    error.value = '两次输入的密码不一致'
    return
  }

  submitting.value = true
  try {
    if (isRegister.value) await register(username.value.trim(), password.value)
    else await login(username.value.trim(), password.value)
    username.value = ''
    password.value = ''
    confirm.value = ''
  } catch (e) {
    error.value = messageOf(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppOverlay
    :model-value="visible"
    :title="title"
    :width="360"
    :persistent="true"
    :close-on-mask="false"
    :show-close="false"
  >
    <div class="auth">
      <p class="auth__slogan">知识库智能检索与问答</p>

      <div v-if="isApiKey" class="auth__fields">
        <AppInput
          v-model="apiKey"
          label="API Key"
          type="password"
          mono
          placeholder="服务端 API_KEY"
          @enter="submit"
        />
        <p class="auth__note">
          服务端已配置 API_KEY，填入后才能访问。仅保存在本机浏览器，不会上传。
        </p>
      </div>

      <div v-else-if="!isError" class="auth__fields">
        <AppInput v-model="username" label="用户名" placeholder="用户名" @enter="submit" />
        <AppInput v-model="password" label="密码" type="password" placeholder="密码" @enter="submit" />
        <AppInput
          v-if="isRegister"
          v-model="confirm"
          label="确认密码"
          type="password"
          placeholder="再输一次"
          @enter="submit"
        />
      </div>

      <p v-if="isError" class="auth__alert">{{ authState.error }}</p>
      <p v-else-if="error" class="auth__alert">{{ error }}</p>

      <AppButton variant="primary" :loading="submitting" class="auth__submit" @click="submit">
        {{ submitText }}
      </AppButton>

      <p v-if="isMultiuser && !isError" class="auth__switch">
        <span class="auth__switch-text">{{ isRegister ? '已有账号？' : '还没有账号？' }}</span>
        <button
          type="button"
          class="auth__link"
          @click="tab = isRegister ? 'login' : 'register'"
        >
          {{ isRegister ? '去登录' : '去注册' }}
        </button>
      </p>
    </div>
  </AppOverlay>
</template>

<style scoped>
.auth {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.auth__slogan {
  margin: 0;
  text-align: center;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.auth__fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.auth__note {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
}

.auth__alert {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-bg-subtle);
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.auth__submit {
  width: 100%;
}

.auth__switch {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  margin: 0;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
}

.auth__switch-text {
  color: var(--color-text-muted);
}

.auth__link {
  padding: 0;
  border: none;
  background: transparent;
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-sm);
  font-family: inherit;
  cursor: pointer;
}
.auth__link:hover {
  text-decoration: underline;
}
</style>
