<script setup>
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <strong class="brand">notes-rag</strong>
      <nav>
        <RouterLink to="/vaults">Vaults</RouterLink>
        <RouterLink to="/search">Search</RouterLink>
        <RouterLink to="/chat">Chat</RouterLink>
        <RouterLink to="/models">Models</RouterLink>
        <RouterLink to="/login">Login</RouterLink>
      </nav>
    </header>
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style>
.layout { font-family: system-ui, sans-serif; max-width: 960px; margin: 0 auto; padding: 16px; }
.topbar { display: flex; align-items: center; gap: 16px; border-bottom: 1px solid #eee; padding-bottom: 8px; }
.brand { font-size: 16px; }
.topbar nav a { margin-right: 12px; color: #185fa5; text-decoration: none; }
.content { margin-top: 16px; }
</style>
