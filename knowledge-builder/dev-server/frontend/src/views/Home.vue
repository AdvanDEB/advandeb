<template>
  <div class="home">
    <el-row :gutter="20">
      <el-col :span="24">
        <el-card class="welcome-card">
          <template #header>
            <div class="card-header">
              <h1>Welcome to AdvandEB Knowledge Builder</h1>
            </div>
          </template>
          <div class="welcome-content">
            <p class="description">
              AdvandEB Knowledge Builder is an advanced knowledge base builder for agglomeration of knowledge on 
              physiology, morphology, anatomy, and bioenergetics of organisms. The system provides 
              powerful tools for data collection, fact extraction, and knowledge visualization.
            </p>
            
            <el-row :gutter="20" style="margin-top: 30px;">
              <el-col :span="6">
                <el-card class="feature-card" shadow="hover" @click="$router.push('/knowledge')">
                  <el-icon class="feature-icon" size="48" color="#409EFF"><collection /></el-icon>
                  <h3>Knowledge Base</h3>
                  <p>Browse and manage facts, stylized facts, and knowledge graphs</p>
                </el-card>
              </el-col>
              
              <el-col :span="6">
                <el-card class="feature-card" shadow="hover" @click="$router.push('/data')">
                  <el-icon class="feature-icon" size="48" color="#67C23A"><document /></el-icon>
                  <h3>Data Processing</h3>
                  <p>Upload PDFs, browse web content, and extract facts automatically</p>
                </el-card>
              </el-col>
              
              <el-col :span="6">
                <el-card class="feature-card" shadow="hover" @click="$router.push('/visualization')">
                  <el-icon class="feature-icon" size="48" color="#E6A23C"><pie-chart /></el-icon>
                  <h3>Visualization</h3>
                  <p>Create and explore interactive knowledge graphs and networks</p>
                </el-card>
              </el-col>
              
              <el-col :span="6">
                <el-card class="feature-card" shadow="hover" @click="$router.push('/agents')">
                  <el-icon class="feature-icon" size="48" color="#F56C6C"><cpu /></el-icon>
                  <h3>AI Agents</h3>
                  <p>Leverage locally hosted Ollama models for intelligent fact extraction</p>
                </el-card>
              </el-col>
            </el-row>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>System Features</span>
            </div>
          </template>
          <ul class="feature-list">
            <li>📚 MongoDB-based knowledge storage</li>
            <li>🦙 Ollama LLM hosting support</li>
            <li>🌐 Web browsing capabilities</li>
            <li>📄 PDF document ingestion</li>
            <li>✨ Stylized fact extraction</li>
            <li>📊 Interactive graph visualization</li>
            <li>🔍 Semantic search and discovery</li>
          </ul>
        </el-card>
      </el-col>
      
      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>Getting Started</span>
            </div>
          </template>
          <ol class="getting-started">
            <li>Ensure Ollama is running and models are pulled</li>
            <li>Upload documents or browse web content for data collection</li>
            <li>Extract facts using AI-powered natural language processing</li>
            <li>Create knowledge graphs to visualize relationships</li>
            <li>Explore and analyze your knowledge base</li>
          </ol>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
export default {
  name: 'Home',
}
</script>

<style scoped>
.home {
  max-width: 1200px;
  margin: 0 auto;
}

.welcome-card {
  text-align: center;
}

.description {
  font-size: 16px;
  line-height: 1.6;
  color: #666;
  max-width: 800px;
  margin: 0 auto;
}

.feature-card {
  text-align: center;
  cursor: pointer;
  height: 200px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  transition: transform 0.2s;
}

.feature-card:hover {
  transform: translateY(-5px);
}

.feature-icon {
  margin-bottom: 15px;
}

.feature-card h3 {
  margin: 10px 0;
  color: #303133;
}

.feature-card p {
  color: #666;
  font-size: 14px;
  line-height: 1.4;
  padding: 0 10px;
}

.feature-list {
  list-style: none;
  padding: 0;
}

.feature-list li {
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.feature-list li:last-child {
  border-bottom: none;
}

.getting-started {
  padding-left: 20px;
}

.getting-started li {
  padding: 8px 0;
  line-height: 1.5;
}

.card-header {
  display: flex;
  justify-content: center;
  align-items: center;
}

.card-header h1 {
  margin: 0;
  color: #303133;
}
</style>