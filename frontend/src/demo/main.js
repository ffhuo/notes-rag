import { createApp } from 'vue'
import DemoApp from './DemoApp.vue'
import '../styles/tokens.css'
import '../styles/base.css'
import './demo.css'
import { initTheme } from '../theme'

initTheme()
createApp(DemoApp).mount('#demo-app')
