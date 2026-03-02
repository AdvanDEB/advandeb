<template>
  <div class="knowledge-base">
    <el-tabs v-model="activeTab" type="card">
      <!-- Facts Tab -->
      <el-tab-pane label="Facts" name="facts">
        <div class="tab-content">
          <div class="actions-bar">
            <el-button type="primary" @click="showCreateFactDialog = true">
              <el-icon><plus /></el-icon>
              Add Fact
            </el-button>
            <el-input
              v-model="searchQuery"
              placeholder="Search facts..."
              style="width: 300px; margin-left: 10px;"
              @input="searchFacts"
            >
              <template #prefix>
                <el-icon><search /></el-icon>
              </template>
            </el-input>
          </div>
          
          <el-table :data="facts" v-loading="factsLoading" stripe style="margin-top: 20px;">
            <el-table-column prop="content" label="Content" min-width="300">
              <template #default="scope">
                <div class="fact-content">{{ scope.row.content }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="source" label="Source" width="150" />
            <el-table-column prop="confidence" label="Confidence" width="100">
              <template #default="scope">
                <el-tag :type="getConfidenceType(scope.row.confidence)">
                  {{ (scope.row.confidence * 100).toFixed(0) }}%
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="tags" label="Tags" width="200">
              <template #default="scope">
                <el-tag v-for="tag in scope.row.tags" :key="tag" size="small" style="margin-right: 5px;">
                  {{ tag }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="Created" width="120">
              <template #default="scope">
                {{ formatDate(scope.row.created_at) }}
              </template>
            </el-table-column>
          </el-table>
          
          <el-pagination
            v-model:current-page="currentPage"
            :page-size="pageSize"
            :total="totalFacts"
            @current-change="loadFacts"
            style="margin-top: 20px; text-align: center;"
          />
        </div>
      </el-tab-pane>
      
      <!-- Stylized Facts Tab -->
      <el-tab-pane label="Stylized Facts" name="stylized">
        <div class="tab-content">
          <el-table :data="stylizedFacts" v-loading="stylizedLoading" stripe>
            <el-table-column prop="summary" label="Summary" min-width="250" />
            <el-table-column prop="importance" label="Importance" width="120">
              <template #default="scope">
                <el-progress :percentage="scope.row.importance * 100" />
              </template>
            </el-table-column>
            <el-table-column prop="relationships" label="Relationships" width="150">
              <template #default="scope">
                <el-tag type="info">{{ scope.row.relationships.length }} relations</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="Created" width="120">
              <template #default="scope">
                {{ formatDate(scope.row.created_at) }}
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
      
      <!-- Knowledge Graphs Tab -->
      <el-tab-pane label="Knowledge Graphs" name="graphs">
        <div class="tab-content">
          <div class="actions-bar">
            <el-button type="primary" @click="showCreateGraphDialog = true">
              <el-icon><plus /></el-icon>
              Create Graph
            </el-button>
          </div>
          
          <el-row :gutter="20" style="margin-top: 20px;">
            <el-col :span="8" v-for="graph in knowledgeGraphs" :key="graph.id">
              <el-card class="graph-card" shadow="hover">
                <template #header>
                  <div class="card-header">
                    <span>{{ graph.name }}</span>
                    <el-button type="primary" size="small" @click="viewGraph(graph)">
                      View
                    </el-button>
                  </div>
                </template>
                <div class="graph-info">
                  <p>{{ graph.description }}</p>
                  <div class="graph-stats">
                    <span>Nodes: {{ graph.nodes.length }}</span>
                    <span>Edges: {{ graph.edges.length }}</span>
                  </div>
                  <div class="graph-date">
                    Created: {{ formatDate(graph.created_at) }}
                  </div>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>
    </el-tabs>
    
    <!-- Create Fact Dialog -->
    <el-dialog v-model="showCreateFactDialog" title="Add New Fact" width="600px">
      <el-form :model="newFact" label-width="120px">
        <el-form-item label="Content">
          <el-input
            v-model="newFact.content"
            type="textarea"
            :rows="4"
            placeholder="Enter the fact content..."
          />
        </el-form-item>
        <el-form-item label="Source">
          <el-input v-model="newFact.source" placeholder="Source of the fact" />
        </el-form-item>
        <el-form-item label="Confidence">
          <el-slider v-model="newFact.confidence" :max="1" :step="0.1" show-tooltip />
        </el-form-item>
        <el-form-item label="Tags">
          <el-input v-model="tagInput" placeholder="Enter tags separated by commas" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateFactDialog = false">Cancel</el-button>
        <el-button type="primary" @click="createFact">Create</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { knowledgeAPI } from '@/services/api'

export default {
  name: 'KnowledgeBase',
  data() {
    return {
      activeTab: 'facts',
      facts: [],
      stylizedFacts: [],
      knowledgeGraphs: [],
      factsLoading: false,
      stylizedLoading: false,
      graphsLoading: false,
      currentPage: 1,
      pageSize: 10,
      totalFacts: 0,
      searchQuery: '',
      showCreateFactDialog: false,
      showCreateGraphDialog: false,
      newFact: {
        content: '',
        source: '',
        confidence: 0.8,
      },
      tagInput: '',
    }
  },
  mounted() {
    this.loadFacts()
    this.loadStylizedFacts()
    this.loadKnowledgeGraphs()
  },
  methods: {
    async loadFacts() {
      this.factsLoading = true
      try {
        const response = await knowledgeAPI.getFacts({
          skip: (this.currentPage - 1) * this.pageSize,
          limit: this.pageSize,
        })
        this.facts = response.data
        // In a real app, you'd get the total count from the API
        this.totalFacts = this.facts.length * 10 // Mock total
      } catch (error) {
        this.$message.error('Failed to load facts')
        console.error(error)
      } finally {
        this.factsLoading = false
      }
    },
    
    async loadStylizedFacts() {
      this.stylizedLoading = true
      try {
        const response = await knowledgeAPI.getStylizedFacts()
        this.stylizedFacts = response.data
      } catch (error) {
        this.$message.error('Failed to load stylized facts')
        console.error(error)
      } finally {
        this.stylizedLoading = false
      }
    },
    
    async loadKnowledgeGraphs() {
      this.graphsLoading = true
      try {
        const response = await knowledgeAPI.getGraphs()
        this.knowledgeGraphs = response.data
      } catch (error) {
        this.$message.error('Failed to load knowledge graphs')
        console.error(error)
      } finally {
        this.graphsLoading = false
      }
    },
    
    async createFact() {
      try {
        const fact = {
          ...this.newFact,
          tags: this.tagInput.split(',').map(tag => tag.trim()).filter(tag => tag),
          entities: [],
        }
        
        await knowledgeAPI.createFact(fact)
        this.$message.success('Fact created successfully')
        this.showCreateFactDialog = false
        this.resetNewFact()
        this.loadFacts()
      } catch (error) {
        this.$message.error('Failed to create fact')
        console.error(error)
      }
    },
    
    resetNewFact() {
      this.newFact = {
        content: '',
        source: '',
        confidence: 0.8,
      }
      this.tagInput = ''
    },
    
    searchFacts() {
      // Implement search functionality
      console.log('Searching for:', this.searchQuery)
    },
    
    viewGraph(graph) {
      this.$router.push(`/visualization?graph=${graph.id}`)
    },
    
    getConfidenceType(confidence) {
      if (confidence >= 0.8) return 'success'
      if (confidence >= 0.6) return 'warning'
      return 'danger'
    },
    
    formatDate(dateString) {
      if (!dateString) return ''
      return new Date(dateString).toLocaleDateString()
    },
  },
}
</script>

<style scoped>
.knowledge-base {
  max-width: 1200px;
  margin: 0 auto;
}

.tab-content {
  padding: 20px 0;
}

.actions-bar {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
}

.fact-content {
  max-width: 300px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.graph-info p {
  margin-bottom: 10px;
  color: #666;
}

.graph-stats {
  display: flex;
  gap: 15px;
  margin-bottom: 10px;
}

.graph-stats span {
  font-size: 14px;
  color: #409EFF;
}

.graph-date {
  font-size: 12px;
  color: #999;
}
</style>