import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'

// Import views
import Home from './views/Home.vue'
import KnowledgeBase from './views/KnowledgeBase.vue'
import DataProcessing from './views/DataProcessing.vue'
import Visualization from './views/Visualization.vue'
import Agents from './views/Agents.vue'
import Ingestion from './views/Ingestion.vue'

const routes = [
  { path: '/', name: 'Home', component: Home },
  { path: '/knowledge', name: 'KnowledgeBase', component: KnowledgeBase },
  { path: '/data', name: 'DataProcessing', component: DataProcessing },
  { path: '/ingestion', name: 'Ingestion', component: Ingestion },
  { path: '/visualization', name: 'Visualization', component: Visualization },
  { path: '/agents', name: 'Agents', component: Agents },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

const app = createApp(App)
app.use(router)
app.use(ElementPlus)
app.mount('#app')