<template>
  <div class="ingestion-container">
    <h1>PDF Ingestion Wizard</h1>
    
    <el-tabs v-model="activeTab" type="card">
      <!-- Wizard Tab -->
      <el-tab-pane label="Wizard" name="wizard">
        <div class="wizard-container">
          <el-steps :active="currentStep" finish-status="success" align-center>
            <el-step title="Select Folders" />
            <el-step title="Review Scan" />
            <el-step title="Run Ingestion" />
          </el-steps>
          
          <!-- Step 1: Select Folders -->
          <div v-if="currentStep === 0" class="step-content">
            <h2>Select Folders to Ingest</h2>
            <el-alert
              v-if="sourcesError"
              type="error"
              :title="sourcesError"
              :closable="false"
              style="margin-bottom: 20px;"
            />
            
            <div v-loading="loadingSources" style="min-height: 200px;">
              <div v-if="sources.length > 0">
                <p style="margin-bottom: 10px;">
                  <strong>Papers Root:</strong> {{ papersRoot }}
                </p>
                
                <el-table
                  :data="sources"
                  @selection-change="handleSelectionChange"
                  style="width: 100%;"
                >
                  <el-table-column type="selection" width="55" />
                  <el-table-column prop="name" label="Folder" width="200" />
                  <el-table-column prop="path" label="Path" min-width="200" />
                  <el-table-column prop="pdf_count" label="PDF Count" width="120" align="center">
                    <template #default="scope">
                      <el-tag>{{ scope.row.pdf_count }}</el-tag>
                    </template>
                  </el-table-column>
                </el-table>
                
                <div class="wizard-actions">
                  <el-button type="primary" @click="scanFolders" :disabled="selectedFolders.length === 0">
                    Next: Scan {{ selectedFolders.length }} folder(s)
                  </el-button>
                </div>
              </div>
            </div>
          </div>
          
          <!-- Step 2: Review Scan -->
          <div v-if="currentStep === 1" class="step-content">
            <h2>Review Scan Results</h2>
            <el-alert
              v-if="scanError"
              type="error"
              :title="scanError"
              :closable="false"
              style="margin-bottom: 20px;"
            />
            
            <div v-loading="scanning">
              <div v-if="scanResult">
                <el-descriptions :column="2" border>
                  <el-descriptions-item label="Batch ID">{{ scanResult.batch_id }}</el-descriptions-item>
                  <el-descriptions-item label="Files Found">
                    <el-tag type="success" size="large">{{ scanResult.num_files }} PDFs</el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="Source Root" :span="2">{{ scanResult.source_root }}</el-descriptions-item>
                  <el-descriptions-item label="Folders" :span="2">
                    <el-tag v-for="folder in scanResult.folders" :key="folder" style="margin-right: 5px;">
                      {{ folder }}
                    </el-tag>
                  </el-descriptions-item>
                </el-descriptions>
                
                <div class="wizard-actions">
                  <el-button @click="currentStep = 0">Back</el-button>
                  <el-button type="primary" @click="runIngestion">
                    Confirm & Run Ingestion
                  </el-button>
                </div>
              </div>
            </div>
          </div>
          
          <!-- Step 3: Running -->
          <div v-if="currentStep === 2" class="step-content">
            <h2>Ingestion Started</h2>
            <el-result
              icon="success"
              title="Batch Ingestion Running"
              :sub-title="`${runResult.jobs_enqueued} jobs have been queued for processing`"
            >
              <template #extra>
                <el-button type="primary" @click="viewBatch(runResult.batch_id)">
                  View Batch Progress
                </el-button>
                <el-button @click="resetWizard">Start New Ingestion</el-button>
              </template>
            </el-result>
          </div>
        </div>
      </el-tab-pane>
      
      <!-- Batches Tab -->
      <el-tab-pane label="Batches" name="batches">
        <div class="batches-container">
          <div class="actions-bar">
            <el-button type="primary" @click="loadBatches" :loading="loadingBatches">
              <el-icon><refresh /></el-icon>
              Refresh
            </el-button>
          </div>
          
          <el-table :data="batches" v-loading="loadingBatches" style="margin-top: 20px;">
            <el-table-column prop="name" label="Name" width="150">
              <template #default="scope">
                {{ scope.row.name || 'Unnamed' }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="Status" width="120">
              <template #default="scope">
                <el-tag :type="getStatusType(scope.row.status)">
                  {{ scope.row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="num_files" label="Files" width="100" align="center" />
            <el-table-column prop="folders" label="Folders" min-width="200">
              <template #default="scope">
                <el-tag v-for="folder in scope.row.folders.slice(0, 3)" :key="folder" size="small" style="margin-right: 5px;">
                  {{ folder }}
                </el-tag>
                <span v-if="scope.row.folders.length > 3">+{{ scope.row.folders.length - 3 }} more</span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="Created" width="180">
              <template #default="scope">
                {{ formatDate(scope.row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="Actions" width="150">
              <template #default="scope">
                <el-button size="small" @click="viewBatch(scope.row._id)">View Jobs</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
      
      <!-- Jobs Tab -->
      <el-tab-pane label="Jobs" name="jobs">
        <div class="jobs-container">
          <div class="actions-bar">
            <el-input
              v-model="jobsFilter.batchId"
              placeholder="Filter by Batch ID"
              style="width: 250px; margin-right: 10px;"
              clearable
              @change="loadJobs"
            />
            <el-select
              v-model="jobsFilter.status"
              placeholder="Filter by Status"
              style="width: 150px; margin-right: 10px;"
              clearable
              @change="loadJobs"
            >
              <el-option label="Pending" value="pending" />
              <el-option label="Queued" value="queued" />
              <el-option label="Running" value="running" />
              <el-option label="Completed" value="completed" />
              <el-option label="Failed" value="failed" />
            </el-select>
            <el-button type="primary" @click="loadJobs" :loading="loadingJobs">
              <el-icon><refresh /></el-icon>
              Refresh
            </el-button>
          </div>
          
          <el-table :data="jobs" v-loading="loadingJobs" style="margin-top: 20px;">
            <el-table-column prop="source_path_or_url" label="File" min-width="300" />
            <el-table-column prop="status" label="Status" width="120">
              <template #default="scope">
                <el-tag :type="getStatusType(scope.row.status)">
                  {{ scope.row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="stage" label="Stage" width="150" />
            <el-table-column prop="progress" label="Progress" width="120">
              <template #default="scope">
                <el-progress :percentage="scope.row.progress" />
              </template>
            </el-table-column>
            <el-table-column prop="error_message" label="Error" min-width="200">
              <template #default="scope">
                <span v-if="scope.row.error_message" class="error-text">
                  {{ scope.row.error_message }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="Created" width="180">
              <template #default="scope">
                {{ formatDate(scope.row.created_at) }}
              </template>
            </el-table-column>
          </el-table>
          
          <el-pagination
            v-model:current-page="jobsFilter.page"
            :page-size="jobsFilter.limit"
            :total="totalJobs"
            @current-change="loadJobs"
            style="margin-top: 20px; text-align: center;"
          />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script>
import { ingestionAPI } from '@/services/api'

export default {
  name: 'Ingestion',
  data() {
    return {
      activeTab: 'wizard',
      
      // Wizard state
      currentStep: 0,
      sources: [],
      papersRoot: '',
      selectedFolders: [],
      scanResult: null,
      runResult: null,
      
      // Loading states
      loadingSources: false,
      scanning: false,
      running: false,
      loadingBatches: false,
      loadingJobs: false,
      
      // Error states
      sourcesError: null,
      scanError: null,
      
      // Batches
      batches: [],
      
      // Jobs
      jobs: [],
      totalJobs: 0,
      jobsFilter: {
        batchId: '',
        status: '',
        page: 1,
        limit: 50,
      },
    }
  },
  
  mounted() {
    this.loadSources()
    this.loadBatches()
  },
  
  methods: {
    async loadSources() {
      this.loadingSources = true
      this.sourcesError = null
      try {
        const response = await ingestionAPI.getSources()
        this.papersRoot = response.data.root
        this.sources = response.data.entries
      } catch (error) {
        console.error('Failed to load sources:', error)
        this.sourcesError = error.response?.data?.detail || 'Failed to load source folders'
      } finally {
        this.loadingSources = false
      }
    },
    
    handleSelectionChange(selected) {
      this.selectedFolders = selected.map(s => s.path)
    },
    
    async scanFolders() {
      if (this.selectedFolders.length === 0) {
        this.$message.warning('Please select at least one folder')
        return
      }
      
      this.scanning = true
      this.scanError = null
      try {
        const response = await ingestionAPI.scanFolders(this.selectedFolders)
        this.scanResult = response.data
        this.currentStep = 1
      } catch (error) {
        console.error('Scan failed:', error)
        this.scanError = error.response?.data?.detail || 'Failed to scan folders'
      } finally {
        this.scanning = false
      }
    },
    
    async runIngestion() {
      if (!this.scanResult?.batch_id) {
        this.$message.error('No batch to run')
        return
      }
      
      this.running = true
      try {
        const response = await ingestionAPI.runBatch(this.scanResult.batch_id)
        this.runResult = response.data
        this.currentStep = 2
        this.$message.success(`${response.data.jobs_enqueued} jobs enqueued successfully`)
      } catch (error) {
        console.error('Failed to run batch:', error)
        this.$message.error(error.response?.data?.detail || 'Failed to start ingestion')
      } finally {
        this.running = false
      }
    },
    
    resetWizard() {
      this.currentStep = 0
      this.selectedFolders = []
      this.scanResult = null
      this.runResult = null
      this.scanError = null
      this.loadSources()
    },
    
    async loadBatches() {
      this.loadingBatches = true
      try {
        const response = await ingestionAPI.getBatches(20)
        this.batches = response.data.batches
      } catch (error) {
        console.error('Failed to load batches:', error)
        this.$message.error('Failed to load batches')
      } finally {
        this.loadingBatches = false
      }
    },
    
    async loadJobs() {
      this.loadingJobs = true
      try {
        const params = {
          limit: this.jobsFilter.limit,
          skip: (this.jobsFilter.page - 1) * this.jobsFilter.limit,
        }
        
        if (this.jobsFilter.batchId) {
          params.batch_id = this.jobsFilter.batchId
        }
        if (this.jobsFilter.status) {
          params.status = this.jobsFilter.status
        }
        
        const response = await ingestionAPI.getJobs(params)
        this.jobs = response.data.jobs
        // For now, use a mock total; backend could return it
        this.totalJobs = this.jobs.length * 10
      } catch (error) {
        console.error('Failed to load jobs:', error)
        this.$message.error('Failed to load jobs')
      } finally {
        this.loadingJobs = false
      }
    },
    
    viewBatch(batchId) {
      this.activeTab = 'jobs'
      this.jobsFilter.batchId = batchId
      this.jobsFilter.status = ''
      this.jobsFilter.page = 1
      this.loadJobs()
    },
    
    getStatusType(status) {
      const statusMap = {
        pending: 'info',
        queued: 'warning',
        running: 'primary',
        completed: 'success',
        failed: 'danger',
        cancelled: 'info',
      }
      return statusMap[status] || 'info'
    },
    
    formatDate(dateString) {
      if (!dateString) return ''
      return new Date(dateString).toLocaleString()
    },
  },
}
</script>

<style scoped>
.ingestion-container {
  max-width: 1400px;
  margin: 0 auto;
}

.wizard-container {
  padding: 20px 0;
}

.step-content {
  margin-top: 40px;
  min-height: 400px;
}

.step-content h2 {
  margin-bottom: 20px;
  color: #303133;
}

.wizard-actions {
  margin-top: 30px;
  text-align: center;
}

.wizard-actions .el-button {
  margin: 0 10px;
}

.actions-bar {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
}

.error-text {
  color: #f56c6c;
  font-size: 12px;
}

.batches-container,
.jobs-container {
  padding: 20px 0;
}
</style>
