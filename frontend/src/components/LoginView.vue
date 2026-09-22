<script setup>
// 登录页（仅 ENABLE_MULTIUSER=true 时启用）：账号密码 → POST /api/v1/auth/login → 存 JWT。
// 单用户模式不需登录，在设置里填一次 API Key 即可（见 api.js setApiKey）。
import { ref } from 'vue'
import { apiFetch, setToken } from '../api'

const username = ref('')
const password = ref('')
const error = ref('')

async function login() {
  error.value = ''
  try {
    const res = await apiFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: username.value, password: password.value }),
    })
    setToken(res.access_token)
    location.href = '/vaults'
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <section>
    <h2>Login</h2>
    <div class="form">
      <input v-model="username" placeholder="用户名" />
      <input v-model="password" type="password" placeholder="密码" @keyup.enter="login" />
      <button @click="login">登录</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
  </section>
</template>

<style scoped>
.form { display: flex; gap: 8px; }
.error { color: #a32d2d; }
</style>
