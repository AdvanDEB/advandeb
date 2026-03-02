<template>
  <div id="app">
    <el-container style="height: 100vh">
      <!-- Header -->
      <el-header style="text-align: center; font-size: 20px; background-color: #409EFF; color: white;">
        <div style="line-height: 60px;">
          <strong>AdvandEB Knowledge Builder</strong>
        </div>
      </el-header>
      
      <!-- Main Layout -->
      <el-container>
        <!-- Sidebar Navigation -->
        <el-aside width="200px" style="background-color: #f5f5f5;">
          <el-menu
            :default-active="$route.path"
            router
            class="el-menu-vertical"
            style="height: 100%;"
          >
            <el-menu-item index="/">
              <el-icon><house /></el-icon>
              <span>Home</span>
            </el-menu-item>
            <el-menu-item index="/knowledge">
              <el-icon><collection /></el-icon>
              <span>Knowledge Base</span>
            </el-menu-item>
            <el-menu-item index="/data">
              <el-icon><document /></el-icon>
              <span>Data Processing</span>
            </el-menu-item>
            <el-menu-item index="/ingestion">
              <el-icon><upload /></el-icon>
              <span>Batch Ingestion</span>
            </el-menu-item>
            <el-menu-item index="/visualization">
              <el-icon><pie-chart /></el-icon>
              <span>Visualization</span>
            </el-menu-item>
            <el-menu-item index="/agents">
              <el-icon><cpu /></el-icon>
              <span>AI Agents</span>
            </el-menu-item>
          </el-menu>
        </el-aside>
        
        <!-- Main Content Area -->
        <el-main style="padding: 20px;">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script>
export default {
  name: 'App',
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', SimSun, sans-serif;
}

.el-menu-vertical {
  border-right: none !important;
}
</style>