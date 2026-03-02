<template>
  <div class="visualization">
    <el-row :gutter="20">
      <!-- Left Panel - Controls -->
      <el-col :span="6">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>Graph Controls</span>
            </div>
          </template>
          
          <!-- Graph Selection -->
          <div class="control-section">
            <h4>Select Graph</h4>
            <el-select
              v-model="selectedGraphId"
              placeholder="Choose a knowledge graph"
              style="width: 100%;"
              @change="loadGraphVisualization"
            >
              <el-option
                v-for="graph in knowledgeGraphs"
                :key="graph.id"
                :label="graph.name"
                :value="graph.id"
              />
            </el-select>
          </div>
          
          <!-- Layout Controls -->
          <div class="control-section" v-if="selectedGraphId">
            <h4>Layout</h4>
            <el-radio-group v-model="selectedLayout" @change="updateLayout">
              <el-radio label="spring">Spring</el-radio>
              <el-radio label="circular">Circular</el-radio>
              <el-radio label="random">Random</el-radio>
              <el-radio label="shell">Shell</el-radio>
            </el-radio-group>
          </div>
          
          <!-- Graph Statistics -->
          <div class="control-section" v-if="graphStats">
            <h4>Statistics</h4>
            <div class="stats-item">
              <span>Nodes:</span>
              <el-tag>{{ graphStats.statistics.node_count }}</el-tag>
            </div>
            <div class="stats-item">
              <span>Edges:</span>
              <el-tag>{{ graphStats.statistics.edge_count }}</el-tag>
            </div>
            <div class="stats-item">
              <span>Density:</span>
              <el-tag>{{ (graphStats.statistics.density * 100).toFixed(2) }}%</el-tag>
            </div>
            <div class="stats-item">
              <span>Components:</span>
              <el-tag>{{ graphStats.statistics.connected_components }}</el-tag>
            </div>
          </div>
          
          <!-- Actions -->
          <div class="control-section" v-if="selectedGraphId">
            <h4>Actions</h4>
            <el-button type="primary" size="small" @click="detectCommunities" style="width: 100%; margin-bottom: 10px;">
              Detect Communities
            </el-button>
            <el-button type="success" size="small" @click="exportGraph" style="width: 100%; margin-bottom: 10px;">
              Export Graph
            </el-button>
            <el-button type="info" size="small" @click="showNetworkAnalysis" style="width: 100%;">
              Network Analysis
            </el-button>
          </div>
        </el-card>
      </el-col>
      
      <!-- Right Panel - Visualization -->
      <el-col :span="18">
        <el-card style="height: 700px;">
          <template #header>
            <div class="card-header">
              <span>Knowledge Graph Visualization</span>
            </div>
          </template>
          
          <div
            id="graph-container"
            ref="graphContainer"
            style="width: 100%; height: 600px; border: 1px solid #ddd;"
            v-loading="graphLoading"
          >
            <div v-if="!selectedGraphId" class="empty-state">
              <el-icon size="64" color="#ccc"><pie-chart /></el-icon>
              <p>Select a knowledge graph to visualize</p>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- Network Analysis Dialog -->
    <el-dialog
      v-model="showAnalysisDialog"
      title="Network Analysis"
      width="60%"
    >
      <div v-if="networkAnalysis">
        <el-tabs type="card">
          <el-tab-pane label="Centrality">
            <div class="analysis-section">
              <h4>Top Nodes by Degree Centrality</h4>
              <el-table :data="networkAnalysis.centrality.top_degree" size="small">
                <el-table-column prop="0" label="Node" />
                <el-table-column prop="1" label="Score" width="120">
                  <template #default="scope">
                    {{ scope.row[1].toFixed(4) }}
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-tab-pane>
          <el-tab-pane label="Clustering">
            <div class="analysis-section">
              <p><strong>Average Clustering:</strong> {{ networkAnalysis.clustering.average?.toFixed(4) || 'N/A' }}</p>
              <h4>Top Nodes by Clustering Coefficient</h4>
              <el-table :data="networkAnalysis.clustering.top_nodes" size="small">
                <el-table-column prop="0" label="Node" />
                <el-table-column prop="1" label="Coefficient" width="120">
                  <template #default="scope">
                    {{ scope.row[1].toFixed(4) }}
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>
    
    <!-- Communities Dialog -->
    <el-dialog
      v-model="showCommunitiesDialog"
      title="Community Detection"
      width="50%"
    >
      <div v-if="communities">
        <p><strong>Algorithm:</strong> {{ communities.algorithm }}</p>
        <p><strong>Modularity:</strong> {{ communities.modularity?.toFixed(4) || 'N/A' }}</p>
        <h4>Communities ({{ communities.communities.length }})</h4>
        <el-card
          v-for="(community, index) in communities.communities"
          :key="index"
          style="margin-bottom: 10px;"
        >
          <template #header>
            <span>Community {{ community.id }} ({{ community.nodes.length }} nodes)</span>
          </template>
          <div class="community-nodes">
            <el-tag
              v-for="node in community.nodes"
              :key="node"
              style="margin: 2px;"
              size="small"
            >
              {{ node }}
            </el-tag>
          </div>
        </el-card>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import { knowledgeAPI, visualizationAPI } from '@/services/api'
import * as d3 from 'd3'

export default {
  name: 'Visualization',
  data() {
    return {
      knowledgeGraphs: [],
      selectedGraphId: null,
      selectedLayout: 'spring',
      graphData: null,
      graphStats: null,
      graphLoading: false,
      showAnalysisDialog: false,
      showCommunitiesDialog: false,
      networkAnalysis: null,
      communities: null,
      simulation: null,
    }
  },
  mounted() {
    this.loadKnowledgeGraphs()
    
    // Check if graph ID is provided in query params
    const graphId = this.$route.query.graph
    if (graphId) {
      this.selectedGraphId = graphId
      this.loadGraphVisualization()
    }
  },
  methods: {
    async loadKnowledgeGraphs() {
      try {
        const response = await knowledgeAPI.getGraphs()
        this.knowledgeGraphs = response.data
      } catch (error) {
        this.$message.error('Failed to load knowledge graphs')
        console.error(error)
      }
    },
    
    async loadGraphVisualization() {
      if (!this.selectedGraphId) return
      
      this.graphLoading = true
      try {
        const response = await visualizationAPI.getGraphVisualization(this.selectedGraphId, this.selectedLayout)
        this.graphData = response.data
        this.graphStats = response.data
        this.renderGraph()
      } catch (error) {
        this.$message.error('Failed to load graph visualization')
        console.error(error)
      } finally {
        this.graphLoading = false
      }
    },
    
    async updateLayout() {
      if (!this.selectedGraphId) return
      
      try {
        await visualizationAPI.updateGraphLayout(this.selectedGraphId, this.selectedLayout)
        this.loadGraphVisualization()
      } catch (error) {
        this.$message.error('Failed to update layout')
        console.error(error)
      }
    },
    
    renderGraph() {
      if (!this.graphData || !this.graphData.nodes) return
      
      // Clear previous visualization
      d3.select('#graph-container').selectAll('*').remove()
      
      const container = d3.select('#graph-container')
      const width = 800
      const height = 600
      
      const svg = container
        .append('svg')
        .attr('width', width)
        .attr('height', height)
        .style('border', '1px solid #ddd')
      
      // Create zoom behavior
      const zoom = d3.zoom()
        .scaleExtent([0.1, 10])
        .on('zoom', (event) => {
          g.attr('transform', event.transform)
        })
      
      svg.call(zoom)
      
      const g = svg.append('g')
      
      // Create simulation
      this.simulation = d3.forceSimulation(this.graphData.nodes)
        .force('link', d3.forceLink(this.graphData.edges).id(d => d.id).distance(100))
        .force('charge', d3.forceManyBody().strength(-300))
        .force('center', d3.forceCenter(width / 2, height / 2))
      
      // Add edges
      const links = g.selectAll('.link')
        .data(this.graphData.edges)
        .enter()
        .append('line')
        .attr('class', 'link')
        .style('stroke', d => d.color || '#999')
        .style('stroke-opacity', 0.6)
        .style('stroke-width', d => Math.sqrt(d.weight || 1))
      
      // Add nodes
      const nodes = g.selectAll('.node')
        .data(this.graphData.nodes)
        .enter()
        .append('circle')
        .attr('class', 'node')
        .attr('r', d => d.size || 10)
        .style('fill', d => d.color || '#1f77b4')
        .style('stroke', '#fff')
        .style('stroke-width', 2)
        .call(d3.drag()
          .on('start', (event, d) => {
            if (!event.active) this.simulation.alphaTarget(0.3).restart()
            d.fx = d.x
            d.fy = d.y
          })
          .on('drag', (event, d) => {
            d.fx = event.x
            d.fy = event.y
          })
          .on('end', (event, d) => {
            if (!event.active) this.simulation.alphaTarget(0)
            d.fx = null
            d.fy = null
          })
        )
      
      // Add labels
      const labels = g.selectAll('.label')
        .data(this.graphData.nodes)
        .enter()
        .append('text')
        .attr('class', 'label')
        .text(d => d.label || d.id)
        .style('font-size', '12px')
        .style('text-anchor', 'middle')
        .style('fill', '#333')
        .style('pointer-events', 'none')
      
      // Add tooltips
      nodes.append('title')
        .text(d => `${d.label || d.id}\nType: ${d.type || 'Unknown'}`)
      
      // Update positions on simulation tick
      this.simulation.on('tick', () => {
        links
          .attr('x1', d => d.source.x)
          .attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x)
          .attr('y2', d => d.target.y)
        
        nodes
          .attr('cx', d => d.x)
          .attr('cy', d => d.y)
        
        labels
          .attr('x', d => d.x)
          .attr('y', d => d.y + 4)
      })
    },
    
    async showNetworkAnalysis() {
      if (!this.selectedGraphId) return
      
      try {
        const response = await visualizationAPI.getNetworkStats(this.selectedGraphId)
        this.networkAnalysis = response.data
        this.showAnalysisDialog = true
      } catch (error) {
        this.$message.error('Failed to load network analysis')
        console.error(error)
      }
    },
    
    async detectCommunities() {
      if (!this.selectedGraphId) return
      
      try {
        const response = await visualizationAPI.detectCommunities(this.selectedGraphId)
        this.communities = response.data
        this.showCommunitiesDialog = true
      } catch (error) {
        this.$message.error('Failed to detect communities')
        console.error(error)
      }
    },
    
    async exportGraph() {
      if (!this.selectedGraphId) return
      
      try {
        const response = await visualizationAPI.exportGraph(this.selectedGraphId, 'json')
        const dataStr = JSON.stringify(response.data, null, 2)
        const dataBlob = new Blob([dataStr], { type: 'application/json' })
        const url = URL.createObjectURL(dataBlob)
        
        const link = document.createElement('a')
        link.href = url
        link.download = `knowledge_graph_${this.selectedGraphId}.json`
        link.click()
        
        URL.revokeObjectURL(url)
        this.$message.success('Graph exported successfully')
      } catch (error) {
        this.$message.error('Failed to export graph')
        console.error(error)
      }
    },
  },
  
  beforeUnmount() {
    if (this.simulation) {
      this.simulation.stop()
    }
  },
}
</script>

<style scoped>
.visualization {
  max-width: 1400px;
  margin: 0 auto;
}

.control-section {
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 1px solid #f0f0f0;
}

.control-section:last-child {
  border-bottom: none;
}

.control-section h4 {
  margin-bottom: 10px;
  color: #303133;
  font-size: 14px;
}

.stats-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.stats-item span {
  font-size: 13px;
  color: #666;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #999;
}

.empty-state p {
  margin-top: 15px;
  font-size: 16px;
}

.analysis-section {
  margin-bottom: 20px;
}

.analysis-section h4 {
  margin-bottom: 10px;
  color: #303133;
}

.community-nodes {
  line-height: 1.8;
}

.card-header {
  display: flex;
  justify-content: center;
  align-items: center;
}

/* D3 Graph Styles */
:deep(.node) {
  cursor: pointer;
}

:deep(.node:hover) {
  stroke: #ff7f0e !important;
  stroke-width: 3px !important;
}

:deep(.link) {
  cursor: pointer;
}

:deep(.label) {
  font-family: sans-serif;
}
</style>