<template>
  <div class="data-processing">
    <el-tabs v-model="activeTab" type="card">
      <!-- PDF Upload Tab -->
      <el-tab-pane label="PDF Upload" name="pdf">
        <div class="tab-content">
          <el-card>
            <template #header>
              <div class="card-header">
                <span>Upload PDF Documents</span>
              </div>
            </template>
            
            <el-upload
              class="upload-demo"
              drag
              :before-upload="handlePDFUpload"
              :show-file-list="false"
              accept=".pdf"
            >
              <el-icon class="el-icon--upload" size="67"><upload-filled /></el-icon>
              <div class="el-upload__text">
                Drop PDF file here or <em>click to upload</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">
                  PDF files only, max size 50MB
                </div>
              </template>
            </el-upload>
            
            <div v-if="uploadProgress.show" class="upload-progress">
              <el-progress
                :percentage="uploadProgress.percentage"
                :status="uploadProgress.status"
              />
              <p style="margin-top: 10px;">{{ uploadProgress.message }}</p>
            </div>
          </el-card>
        </div>
      </el-tab-pane>
      
      <!-- Web Browsing Tab -->
      <el-tab-pane label="Web Browsing" name="web">
        <div class="tab-content">
          <el-card>
            <template #header>
              <div class="card-header">
                <span>Browse Web Content</span>
              </div>
            </template>
            
            <el-form :model="webForm" label-width="120px">
              <el-form-item label="URL">
                <el-input
                  v-model="webForm.url"
                  placeholder="Enter URL to browse..."
                  style="width: 100%;"
                >
                  <template #append>
                    <el-button
                      type="primary"
                      @click="browseURL"
                      :loading="webLoading"
                    >
                      Browse
                    </el-button>
                  </template>
                </el-input>
              </el-form-item>
              <el-form-item label="Extract Facts">
                <el-switch v-model="webForm.extractFacts" />
              </el-form-item>
            </el-form>
            
            <div v-if="webResult" class="web-result">
              <h3>{{ webResult.title }}</h3>
              <p><strong>Word Count:</strong> {{ webResult.word_count }}</p>
              <div class="content-preview">
                <h4>Content Preview:</h4>
                <p>{{ webResult.content.substring(0, 500) }}...</p>
              </div>
              <div v-if="webResult.facts" class="extracted-facts">
                <h4>Extracted Facts ({{ webResult.facts.length }}):</h4>
                <el-tag
                  v-for="(fact, index) in webResult.facts.slice(0, 5)"
                  :key="index"
                  style="margin: 5px; display: block;"
                >
                  {{ fact }}
                </el-tag>
                <span v-if="webResult.facts.length > 5">
                  ... and {{ webResult.facts.length - 5 }} more
                </span>
              </div>
            </div>
          </el-card>
        </div>
      </el-tab-pane>
      
      <!-- Text Processing Tab -->
      <el-tab-pane label="Text Processing" name="text">
        <div class="tab-content">
          <el-card>
            <template #header>
              <div class="card-header">
                <span>Process Raw Text</span>
              </div>
            </template>
            
            <el-form :model="textForm" label-width="120px">
              <el-form-item label="Text Content">
                <el-input
                  v-model="textForm.text"
                  type="textarea"
                  :rows="8"
                  placeholder="Enter or paste text content to process..."
                />
              </el-form-item>
              <el-form-item label="Extract Facts">
                <el-switch v-model="textForm.extractFacts" />
              </el-form-item>
              <el-form-item label="Extract Entities">
                <el-switch v-model="textForm.extractEntities" />
              </el-form-item>
              <el-form-item>
                <el-button
                  type="primary"
                  @click="processText"
                  :loading="textLoading"
                >
                  Process Text
                </el-button>
              </el-form-item>
            </el-form>
            
            <div v-if="textResult" class="text-result">
              <el-row :gutter="20">
                <el-col :span="12" v-if="textResult.facts">
                  <h4>Extracted Facts:</h4>
                  <el-card v-for="(fact, index) in textResult.facts" :key="index" class="fact-card">
                    {{ fact }}
                  </el-card>
                </el-col>
                <el-col :span="12" v-if="textResult.entities">
                  <h4>Extracted Entities:</h4>
                  <div class="entities-list">
                    <el-tag
                      v-for="(entity, index) in textResult.entities"
                      :key="index"
                      :type="getEntityTagType(entity.type)"
                      style="margin: 5px;"
                    >
                      {{ entity.text }}
                    </el-tag>
                  </div>
                </el-col>
              </el-row>
            </div>
          </el-card>
        </div>
      </el-tab-pane>
      
      <!-- Documents Tab -->
      <el-tab-pane label="Documents" name="documents">
        <div class="tab-content">
          <el-table :data="documents" v-loading="documentsLoading" stripe>
            <el-table-column prop="filename" label="Filename" width="200" />
            <el-table-column prop="file_type" label="Type" width="80" />
            <el-table-column prop="file_size" label="Size" width="100">
              <template #default="scope">
                {{ formatFileSize(scope.row.file_size) }}
              </template>
            </el-table-column>
            <el-table-column prop="processing_status" label="Status" width="120">
              <template #default="scope">
                <el-tag :type="getStatusType(scope.row.processing_status)">
                  {{ scope.row.processing_status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="facts_extracted" label="Facts" width="80">
              <template #default="scope">
                {{ scope.row.facts_extracted.length }}
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="Created" width="120">
              <template #default="scope">
                {{ formatDate(scope.row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="Actions" width="100">
              <template #default="scope">
                <el-button
                  size="small"
                  @click="viewDocument(scope.row)"
                >
                  View
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script>
import { dataAPI } from '@/services/api'

export default {
  name: 'DataProcessing',
  data() {
    return {
      activeTab: 'pdf',
      uploadProgress: {
        show: false,
        percentage: 0,
        status: '',
        message: '',
      },
      webForm: {
        url: '',
        extractFacts: true,
      },
      webResult: null,
      webLoading: false,
      textForm: {
        text: '',
        extractFacts: true,
        extractEntities: true,
      },
      textResult: null,
      textLoading: false,
      documents: [],
      documentsLoading: false,
    }
  },
  mounted() {
    this.loadDocuments()
  },
  methods: {
    async handlePDFUpload(file) {
      this.uploadProgress = {
        show: true,
        percentage: 0,
        status: 'active',
        message: 'Uploading PDF...',
      }
      
      try {
        // Simulate upload progress
        const progressInterval = setInterval(() => {
          if (this.uploadProgress.percentage < 50) {
            this.uploadProgress.percentage += 10
          }
        }, 200)
        
        const response = await dataAPI.uploadPDF(file)
        
        clearInterval(progressInterval)
        this.uploadProgress = {
          show: true,
          percentage: 100,
          status: 'success',
          message: `PDF processed successfully! ${response.data.facts_extracted} facts extracted.`,
        }
        
        // Hide progress after 3 seconds
        setTimeout(() => {
          this.uploadProgress.show = false
        }, 3000)
        
        this.loadDocuments()
        
      } catch (error) {
        this.uploadProgress = {
          show: true,
          percentage: 0,
          status: 'exception',
          message: 'Failed to upload PDF: ' + (error.response?.data?.detail || error.message),
        }
        console.error(error)
      }
      
      return false // Prevent default upload
    },
    
    async browseURL() {
      if (!this.webForm.url) {
        this.$message.warning('Please enter a URL')
        return
      }
      
      this.webLoading = true
      try {
        const response = await dataAPI.browseURL(this.webForm.url, this.webForm.extractFacts)
        this.webResult = response.data
        this.$message.success('URL browsed successfully')
      } catch (error) {
        this.$message.error('Failed to browse URL: ' + (error.response?.data?.detail || error.message))
        console.error(error)
      } finally {
        this.webLoading = false
      }
    },
    
    async processText() {
      if (!this.textForm.text) {
        this.$message.warning('Please enter some text')
        return
      }
      
      this.textLoading = true
      try {
        const response = await dataAPI.processText(
          this.textForm.text,
          this.textForm.extractFacts,
          this.textForm.extractEntities
        )
        this.textResult = response.data
        this.$message.success('Text processed successfully')
      } catch (error) {
        this.$message.error('Failed to process text: ' + (error.response?.data?.detail || error.message))
        console.error(error)
      } finally {
        this.textLoading = false
      }
    },
    
    async loadDocuments() {
      this.documentsLoading = true
      try {
        const response = await dataAPI.getDocuments()
        this.documents = response.data.documents || []
      } catch (error) {
        this.$message.error('Failed to load documents')
        console.error(error)
      } finally {
        this.documentsLoading = false
      }
    },
    
    viewDocument(document) {
      console.log('View document:', document)
      // Implement document viewing logic
    },
    
    getEntityTagType(type) {
      const typeMap = {
        'BIOLOGICAL': 'success',
        'PERSON': 'primary',
        'ORGANIZATION': 'warning',
        'LOCATION': 'info',
      }
      return typeMap[type] || 'default'
    },
    
    getStatusType(status) {
      const statusMap = {
        'completed': 'success',
        'processing': 'warning',
        'pending': 'info',
        'failed': 'danger',
      }
      return statusMap[status] || 'default'
    },
    
    formatFileSize(bytes) {
      if (bytes === 0) return '0 B'
      const k = 1024
      const sizes = ['B', 'KB', 'MB', 'GB']
      const i = Math.floor(Math.log(bytes) / Math.log(k))
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
    },
    
    formatDate(dateString) {
      if (!dateString) return ''
      return new Date(dateString).toLocaleDateString()
    },
  },
}
</script>

<style scoped>
.data-processing {
  max-width: 1200px;
  margin: 0 auto;
}

.tab-content {
  padding: 20px 0;
}

.upload-demo {
  margin-bottom: 20px;
}

.upload-progress {
  margin-top: 20px;
}

.web-result,
.text-result {
  margin-top: 20px;
  padding: 20px;
  background-color: #f5f5f5;
  border-radius: 6px;
}

.content-preview {
  margin: 15px 0;
}

.extracted-facts {
  margin-top: 15px;
}

.fact-card {
  margin-bottom: 10px;
  font-size: 14px;
}

.entities-list {
  max-height: 200px;
  overflow-y: auto;
}

.card-header {
  display: flex;
  justify-content: center;
  align-items: center;
}
</style>