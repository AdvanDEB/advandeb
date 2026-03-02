<template>
  <div class="agents">
    <el-tabs v-model="activeTab" type="card">
      <!-- Knowledge Builder Agent Tab -->
      <el-tab-pane label="Knowledge Builder" name="knowledge_builder">
        <div class="tab-content">
          <el-row :gutter="20">
            <el-col :span="16">
              <el-card style="height: 600px;">
                <template #header>
                  <div class="card-header">
                    <span>Knowledge Builder Agent</span>
                    <div class="model-selector">
                      <el-tag type="success" size="small">Ollama</el-tag>
                      <el-select
                        v-model="selectedModel"
                        placeholder="Select model"
                        size="small"
                        style="width: 150px; margin-left: 10px;"
                      >
                        <el-option
                          v-for="model in availableModels"
                          :key="model"
                          :label="model"
                          :value="model"
                        />
                      </el-select>
                    </div>
                  </div>
                </template>
                
                <div class="chat-container">
                  <div class="messages" ref="knowledgeMessagesContainer">
                    <div
                      v-for="(message, index) in knowledgeChatMessages"
                      :key="index"
                      :class="['message', message.role]"
                    >
                      <div class="message-content">
                        <div class="message-header">
                          <span class="role">{{ message.role === 'user' ? 'You' : 'Knowledge Builder' }}</span>
                          <span class="timestamp">{{ formatTime(message.timestamp) }}</span>
                        </div>
                        <div class="message-text">{{ message.content }}</div>
                        <div v-if="message.tool_calls && message.tool_calls.length" class="tool-calls">
                          <el-tag v-for="tool in message.tool_calls" :key="tool.call_id" size="small" type="info">
                            Used: {{ tool.tool_name }}
                          </el-tag>
                        </div>
                      </div>
                    </div>
                  </div>
                  
                  <div class="input-area">
                    <el-input
                      v-model="knowledgeCurrentMessage"
                      type="textarea"
                      :rows="3"
                      placeholder="Ask about literature analysis, fact extraction, or knowledge graph construction..."
                      @keydown.ctrl.enter="sendKnowledgeMessage"
                    >
                      <template #append>
                        <el-button
                          type="primary"
                          @click="sendKnowledgeMessage"
                          :loading="knowledgeChatLoading"
                          :disabled="!knowledgeCurrentMessage.trim()"
                        >
                          Send
                        </el-button>
                      </template>
                    </el-input>
                    <div class="input-hint">Press Ctrl+Enter to send</div>
                  </div>
                </div>
              </el-card>
            </el-col>
            
            <el-col :span="8">
              <el-card>
                <template #header>
                  <div class="card-header">
                    <span>Knowledge Actions</span>
                  </div>
                </template>
                
                <div class="quick-actions">
                  <el-button
                    v-for="action in knowledgeActions"
                    :key="action.id"
                    @click="useKnowledgeAction(action)"
                    style="width: 100%; margin-bottom: 10px; text-align: left;"
                    size="small"
                  >
                    {{ action.title }}
                  </el-button>
                </div>
              </el-card>
              
              <el-card style="margin-top: 20px;">
                <template #header>
                  <div class="card-header">
                    <span>Session Info</span>
                  </div>
                </template>
                
                <div class="session-info">
                  <p><strong>Session ID:</strong> {{ knowledgeSessionId || 'New Session' }}</p>
                  <p><strong>Tool Calls:</strong> {{ knowledgeToolCallsCount }}</p>
                  <el-button size="small" @click="clearKnowledgeSession">New Session</el-button>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>
      
      <!-- Modeling Agent Tab -->
      <el-tab-pane label="Modeling Agent" name="modeling_agent">
        <div class="tab-content">
          <el-row :gutter="20">
            <el-col :span="16">
              <el-card style="height: 600px;">
                <template #header>
                  <div class="card-header">
                    <span>Modeling & Inference Agent</span>
                    <div class="model-selector">
                      <el-tag type="warning" size="small">Ollama</el-tag>
                      <el-switch
                        v-model="enableStreaming"
                        size="small"
                        active-text="Stream"
                        inactive-text="Batch"
                        style="margin-left: 10px;"
                      />
                      <el-select
                        v-model="selectedModel"
                        placeholder="Select model"
                        size="small"
                        style="width: 150px; margin-left: 10px;"
                      >
                        <el-option
                          v-for="model in availableModels"
                          :key="model"
                          :label="model"
                          :value="model"
                        />
                      </el-select>
                    </div>
                  </div>
                </template>
                
                <div class="chat-container">
                  <div class="messages" ref="modelingMessagesContainer">
                    <div
                      v-for="(message, index) in modelingChatMessages"
                      :key="index"
                      :class="['message', message.role]"
                    >
                      <div class="message-content">
                        <div class="message-header">
                          <span class="role">{{ message.role === 'user' ? 'You' : 'Modeling Agent' }}</span>
                          <span class="timestamp">{{ formatTime(message.timestamp) }}</span>
                        </div>
                        <div class="message-text">{{ message.content }}</div>
                        <div v-if="message.context_nodes && message.context_nodes.length" class="context-nodes">
                          <small>Knowledge nodes accessed: {{ message.context_nodes.length }}</small>
                        </div>
                      </div>
                    </div>
                  </div>
                  
                  <div class="input-area">
                    <el-input
                      v-model="modelingCurrentMessage"
                      type="textarea"
                      :rows="3"
                      placeholder="Ask about bioenergetic modeling, organism analysis, or biological processes..."
                      @keydown.ctrl.enter="sendModelingMessage"
                    >
                      <template #append>
                        <el-button
                          type="primary"
                          @click="sendModelingMessage"
                          :loading="modelingChatLoading"
                          :disabled="!modelingCurrentMessage.trim()"
                        >
                          Send
                        </el-button>
                      </template>
                    </el-input>
                    <div class="input-hint">Press Ctrl+Enter to send</div>
                  </div>
                </div>
              </el-card>
            </el-col>
            
            <el-col :span="8">
              <el-card>
                <template #header>
                  <div class="card-header">
                    <span>Modeling Actions</span>
                  </div>
                </template>
                
                <div class="quick-actions">
                  <el-button
                    v-for="action in modelingActions"
                    :key="action.id"
                    @click="useModelingAction(action)"
                    style="width: 100%; margin-bottom: 10px; text-align: left;"
                    size="small"
                  >
                    {{ action.title }}
                  </el-button>
                </div>
              </el-card>
              
              <el-card style="margin-top: 20px;">
                <template #header>
                  <div class="card-header">
                    <span>Knowledge Path</span>
                  </div>
                </template>
                
                <div class="knowledge-path">
                  <div v-if="currentReasoningPath.length" class="reasoning-steps">
                    <el-tag 
                      v-for="(step, index) in currentReasoningPath" 
                      :key="index" 
                      size="small"
                      style="margin: 2px;"
                    >
                      {{ step }}
                    </el-tag>
                  </div>
                  <div v-else class="no-path">
                    No reasoning path yet
                  </div>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>

      <!-- Legacy Chat Tab -->
      <el-tab-pane label="Legacy Chat" name="chat">
        <div class="tab-content">
          <el-row :gutter="20">
            <el-col :span="16">
              <el-card style="height: 600px;">
                <template #header>
                  <div class="card-header">
                    <span>Legacy AI Assistant</span>
                    <div class="model-selector">
                      <el-tag type="info" size="small">Ollama</el-tag>
                      <el-select
                        v-model="selectedModel"
                        placeholder="Select model"
                        size="small"
                        style="width: 150px; margin-left: 10px;"
                      >
                        <el-option
                          v-for="model in availableModels"
                          :key="model"
                          :label="model"
                          :value="model"
                        />
                      </el-select>
                    </div>
                  </div>
                </template>
                
                <div class="chat-container">
                  <div class="messages" ref="messagesContainer">
                    <div
                      v-for="(message, index) in chatMessages"
                      :key="index"
                      :class="['message', message.role]"
                    >
                      <div class="message-content">
                        <div class="message-header">
                          <span class="role">{{ message.role === 'user' ? 'You' : 'AI' }}</span>
                          <span class="timestamp">{{ formatTime(message.timestamp) }}</span>
                        </div>
                        <div class="message-text">{{ message.content }}</div>
                      </div>
                    </div>
                  </div>
                  
                  <div class="input-area">
                    <el-input
                      v-model="currentMessage"
                      type="textarea"
                      :rows="3"
                      placeholder="Ask about knowledge extraction, fact analysis, or biological concepts..."
                      @keydown.ctrl.enter="sendMessage"
                    >
                      <template #append>
                        <el-button
                          type="primary"
                          @click="sendMessage"
                          :loading="chatLoading"
                          :disabled="!currentMessage.trim()"
                        >
                          Send
                        </el-button>
                      </template>
                    </el-input>
                    <div class="input-hint">Press Ctrl+Enter to send</div>
                  </div>
                </div>
              </el-card>
            </el-col>
            
            <el-col :span="8">
              <el-card>
                <template #header>
                  <div class="card-header">
                    <span>Quick Actions</span>
                  </div>
                </template>
                
                <div class="quick-actions">
                  <el-button
                    v-for="action in quickActions"
                    :key="action.id"
                    @click="useQuickAction(action)"
                    style="width: 100%; margin-bottom: 10px; text-align: left;"
                    size="small"
                  >
                    {{ action.title }}
                  </el-button>
                </div>
              </el-card>
              
              <el-card style="margin-top: 20px;">
                <template #header>
                  <div class="card-header">
                    <span>Model Status</span>
                  </div>
                </template>
                
                <div class="model-status">
                  <div class="status-item">
                    <span>Ollama:</span>
                    <el-tag :type="ollamaStatus ? 'success' : 'danger'">
                      {{ ollamaStatus ? 'Available' : 'Unavailable' }}
                    </el-tag>
                  </div>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>
      
      <!-- Fact Extraction Tab -->
      <el-tab-pane label="Fact Extraction" name="extraction">
        <div class="tab-content">
          <el-card>
            <template #header>
              <div class="card-header">
                <span>Extract Facts from Text</span>
              </div>
            </template>
            
            <el-form :model="extractionForm" label-width="120px">
              <el-form-item label="Input Text">
                <el-input
                  v-model="extractionForm.text"
                  type="textarea"
                  :rows="8"
                  placeholder="Paste text content for fact extraction..."
                />
              </el-form-item>
              <el-form-item label="Model">
                <el-select v-model="extractionForm.model" placeholder="Select model">
                  <el-option
                    v-for="model in availableModels"
                    :key="model"
                    :label="model"
                    :value="model"
                  />
                </el-select>
              </el-form-item>
              <el-form-item>
                <el-button
                  type="primary"
                  @click="extractFacts"
                  :loading="extractionLoading"
                  :disabled="!extractionForm.text.trim()"
                >
                  Extract Facts
                </el-button>
              </el-form-item>
            </el-form>
            
            <div v-if="extractedFacts.length" class="extraction-results">
              <h3>Extracted Facts ({{ extractedFacts.length }})</h3>
              <el-card
                v-for="(fact, index) in extractedFacts"
                :key="index"
                class="fact-result"
                shadow="hover"
              >
                <div class="fact-content">{{ fact }}</div>
                <div class="fact-actions">
                  <el-button size="small" @click="saveFact(fact)">Save to KB</el-button>
                  <el-button size="small" type="success" @click="stylizeFact(fact)">Stylize</el-button>
                </div>
              </el-card>
            </div>
          </el-card>
        </div>
      </el-tab-pane>
      
      <!-- Fact Stylization Tab -->
      <el-tab-pane label="Fact Stylization" name="stylization">
        <div class="tab-content">
          <el-card>
            <template #header>
              <div class="card-header">
                <span>Convert Facts to Stylized Facts</span>
              </div>
            </template>
            
            <el-form :model="stylizationForm" label-width="120px">
              <el-form-item label="Facts to Stylize">
                <el-input
                  v-model="stylizationForm.factsText"
                  type="textarea"
                  :rows="6"
                  placeholder="Enter facts (one per line) to convert to stylized facts..."
                />
              </el-form-item>
              <el-form-item label="Model">
                <el-select v-model="stylizationForm.model" placeholder="Select model">
                  <el-option
                    v-for="model in availableModels"
                    :key="model"
                    :label="model"
                    :value="model"
                  />
                </el-select>
              </el-form-item>
              <el-form-item>
                <el-button
                  type="primary"
                  @click="stylizeFacts"
                  :loading="stylizationLoading"
                  :disabled="!stylizationForm.factsText.trim()"
                >
                  Stylize Facts
                </el-button>
              </el-form-item>
            </el-form>
            
            <div v-if="stylizedFacts.length" class="stylization-results">
              <h3>Stylized Facts ({{ stylizedFacts.length }})</h3>
              <el-card
                v-for="(fact, index) in stylizedFacts"
                :key="index"
                class="fact-result"
                shadow="hover"
              >
                <div class="fact-header">
                  <span class="fact-summary">{{ fact.summary }}</span>
                  <el-rate
                    v-model="fact.importance"
                    disabled
                    show-score
                    text-color="#ff9900"
                    score-template="Importance: {value}"
                  />
                </div>
                <div class="fact-relationships" v-if="fact.relationships && fact.relationships.length">
                  <strong>Relationships:</strong>
                  <el-tag
                    v-for="rel in fact.relationships"
                    :key="rel"
                    size="small"
                    style="margin: 2px;"
                  >
                    {{ rel }}
                  </el-tag>
                </div>
                <div class="fact-entities" v-if="fact.entities && fact.entities.length">
                  <strong>Entities:</strong>
                  <div>
                    <el-tag
                      v-for="entity in fact.entities"
                      :key="entity"
                      type="info"
                      size="small"
                      style="margin: 2px;"
                    >
                      {{ entity }}
                    </el-tag>
                  </div>
                </div>
                <div class="fact-actions">
                  <el-button size="small" @click="saveStylizedFact(fact)">Save to KB</el-button>
                </div>
              </el-card>
            </div>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script>
import { agentsAPI, knowledgeAPI } from '@/services/api'

export default {
  name: 'Agents',
  data() {
    return {
      activeTab: 'knowledge_builder',
      selectedModel: '',
      availableModels: [],
      ollamaStatus: false,
      enableStreaming: false,
      
      // Legacy Chat
      chatMessages: [],
      currentMessage: '',
      chatLoading: false,
      
      // Knowledge Builder Agent
      knowledgeChatMessages: [],
      knowledgeCurrentMessage: '',
      knowledgeChatLoading: false,
      knowledgeSessionId: null,
      knowledgeToolCallsCount: 0,
      
      // Modeling Agent
      modelingChatMessages: [],
      modelingCurrentMessage: '',
      modelingChatLoading: false,
      modelingSessionId: null,
      currentReasoningPath: [],
      
      // Fact Extraction
      extractionForm: {
        text: '',
        model: '',
      },
      extractedFacts: [],
      extractionLoading: false,
      
      // Fact Stylization
      stylizationForm: {
        factsText: '',
        model: '',
      },
      stylizedFacts: [],
      stylizationLoading: false,
      
      quickActions: [
        {
          id: 'extract_help',
          title: 'How to extract facts?',
          message: 'How can I effectively extract facts from biological texts using your system?'
        },
        {
          id: 'stylize_help',
          title: 'What are stylized facts?',
          message: 'What are stylized facts and how do they help in knowledge organization?'
        },
        {
          id: 'graph_help',
          title: 'Knowledge graphs',
          message: 'How do you create knowledge graphs from extracted facts?'
        },
        {
          id: 'best_practices',
          title: 'Best practices',
          message: 'What are the best practices for organizing biological knowledge?'
        },
      ],
      
      knowledgeActions: [
        {
          id: 'process_literature',
          title: 'Process Literature',
          message: 'How do I process scientific literature to extract and organize biological knowledge?'
        },
        {
          id: 'extract_facts_help',
          title: 'Fact Extraction Guide',
          message: 'Guide me through extracting high-quality facts from biological texts.'
        },
        {
          id: 'build_knowledge_graph',
          title: 'Build Knowledge Graph',
          message: 'How do I build a knowledge graph from extracted facts and stylized facts?'
        },
        {
          id: 'document_sources',
          title: 'Document Sources',
          message: 'How should I document sources and create bibtex entries for extracted knowledge?'
        },
      ],
      
      modelingActions: [
        {
          id: 'build_bioenergetic_model',
          title: 'Bioenergetic Model',
          message: 'Help me build a bioenergetic model for an organism using available knowledge.'
        },
        {
          id: 'individual_based_model',
          title: 'Individual-Based Model',
          message: 'How do I create individual-based models incorporating physiological data?'
        },
        {
          id: 'query_knowledge_base',
          title: 'Query Knowledge Base',
          message: 'How can I effectively query the knowledge base for modeling purposes?'
        },
        {
          id: 'analyze_organism',
          title: 'Analyze Organism',
          message: 'Analyze the available knowledge about a specific organism for modeling.'
        },
      ],
    }
  },
  mounted() {
    this.checkModelAvailability()
    this.initChat()
  },
  methods: {
    async checkModelAvailability() {
      try {
        await agentsAPI.getModels()
        this.ollamaStatus = true
      } catch (error) {
        this.ollamaStatus = false
      }
      this.loadModels()
    },
    
    async loadModels() {
      try {
        if (this.ollamaStatus) {
          const response = await agentsAPI.getModels()
          this.availableModels = response.data.models
          this.selectedModel = this.availableModels[0] || ''
          if (!this.extractionForm.model) this.extractionForm.model = this.selectedModel
          if (!this.stylizationForm.model) this.stylizationForm.model = this.selectedModel
        }
      } catch (error) {
        console.error('Error loading models:', error)
      }
    },
    
    initChat() {
      this.chatMessages = []
      this.knowledgeChatMessages = []
      this.modelingChatMessages = []
    },
    
    async sendMessage() {
      if (!this.currentMessage.trim()) return
      
      const userMessage = {
        role: 'user',
        content: this.currentMessage,
        timestamp: new Date()
      }
      
      this.chatMessages.push(userMessage)
      this.chatLoading = true
      
      try {
        const response = await agentsAPI.chat([userMessage], this.selectedModel)
        
        this.chatMessages.push({
          role: 'assistant',
          content: response.data.response,
          timestamp: new Date()
        })
        
        this.currentMessage = ''
        this.scrollToBottom('messagesContainer')
      } catch (error) {
        console.error('Chat error:', error)
        this.$message.error('Failed to send message')
      } finally {
        this.chatLoading = false
      }
    },
    
    async sendKnowledgeMessage() {
      if (!this.knowledgeCurrentMessage.trim()) return
      
      const userMessage = {
        role: 'user',
        content: this.knowledgeCurrentMessage,
        timestamp: new Date()
      }
      
      this.knowledgeChatMessages.push(userMessage)
      this.knowledgeChatLoading = true
      
      try {
        const response = await agentsAPI.knowledgeBuilderChat([userMessage], this.selectedModel)
        
        this.knowledgeChatMessages.push({
          role: 'assistant',
          content: response.data.response,
          timestamp: new Date(),
          tool_calls: response.data.tool_calls || [],
          session_id: response.data.session_id
        })
        
        this.knowledgeSessionId = response.data.session_id
        this.knowledgeToolCallsCount += (response.data.tool_calls || []).length
        this.knowledgeCurrentMessage = ''
        this.scrollToBottom('knowledgeMessagesContainer')
      } catch (error) {
        console.error('Knowledge Builder chat error:', error)
        this.$message.error('Failed to send message to Knowledge Builder')
      } finally {
        this.knowledgeChatLoading = false
      }
    },
    
    async sendModelingMessage() {
      if (!this.modelingCurrentMessage.trim()) return
      
      const userMessage = {
        role: 'user',
        content: this.modelingCurrentMessage,
        timestamp: new Date()
      }
      
      this.modelingChatMessages.push(userMessage)
      this.modelingChatLoading = true
      
      try {
        const response = await agentsAPI.modelingAgentChat([userMessage], this.selectedModel)
        
        this.modelingChatMessages.push({
          role: 'assistant',
          content: response.data.response,
          timestamp: new Date(),
          context_nodes: response.data.context_nodes || [],
          session_id: response.data.session_id
        })
        
        this.modelingSessionId = response.data.session_id
        this.currentReasoningPath = response.data.reasoning_path || []
        this.modelingCurrentMessage = ''
        this.scrollToBottom('modelingMessagesContainer')
      } catch (error) {
        console.error('Modeling Agent chat error:', error)
        this.$message.error('Failed to send message to Modeling Agent')
      } finally {
        this.modelingChatLoading = false
      }
    },
    
    clearKnowledgeSession() {
      this.knowledgeSessionId = null
      this.knowledgeToolCallsCount = 0
      this.knowledgeChatMessages = []
    },
    
    useQuickAction(action) {
      this.currentMessage = action.message
      this.sendMessage()
    },
    
    useKnowledgeAction(action) {
      this.knowledgeCurrentMessage = action.message
      this.sendKnowledgeMessage()
    },
    
    useModelingAction(action) {
      this.modelingCurrentMessage = action.message
      this.sendModelingMessage()
    },
    
    async extractFacts() {
      if (!this.extractionForm.text.trim()) return
      
      this.extractionLoading = true
      try {
        const response = await agentsAPI.extractFacts(this.extractionForm.text, this.extractionForm.model)
        this.extractedFacts = response.data.facts || []
        this.$message.success(`Extracted ${this.extractedFacts.length} facts`)
      } catch (error) {
        console.error('Fact extraction error:', error)
        this.$message.error('Failed to extract facts')
      } finally {
        this.extractionLoading = false
      }
    },
    
    async stylizeFacts() {
      if (!this.stylizationForm.factsText.trim()) return
      
      this.stylizationLoading = true
      try {
        const facts = this.stylizationForm.factsText.split('\n').filter(line => line.trim())
        const response = await agentsAPI.stylizeFacts(facts, this.stylizationForm.model)
        this.stylizedFacts = response.data.stylized_facts || []
        this.$message.success(`Stylized ${this.stylizedFacts.length} facts`)
      } catch (error) {
        console.error('Fact stylization error:', error)
        this.$message.error('Failed to stylize facts')
      } finally {
        this.stylizationLoading = false
      }
    },
    
    async stylizeFact(fact) {
      try {
        const response = await agentsAPI.stylizeFacts([fact], this.selectedModel)
        if (response.data.stylized_facts && response.data.stylized_facts.length > 0) {
          this.stylizedFacts.push(response.data.stylized_facts[0])
          this.$message.success('Fact stylized successfully')
        }
      } catch (error) {
        console.error('Single fact stylization error:', error)
        this.$message.error('Failed to stylize fact')
      }
    },
    
    async saveFact(fact) {
      try {
        await knowledgeAPI.createFact({
          text: fact,
          source: 'Agent Extraction',
          confidence: 0.8
        })
        this.$message.success('Fact saved to knowledge base')
      } catch (error) {
        console.error('Save fact error:', error)
        this.$message.error('Failed to save fact')
      }
    },
    
    async saveStylizedFact(fact) {
      try {
        await knowledgeAPI.createStylizedFact(fact)
        this.$message.success('Stylized fact saved to knowledge base')
      } catch (error) {
        console.error('Save stylized fact error:', error)
        this.$message.error('Failed to save stylized fact')
      }
    },
    
    scrollToBottom(containerId) {
      this.$nextTick(() => {
        const container = this.$refs[containerId]
        if (container) {
          container.scrollTop = container.scrollHeight
        }
      })
    },
    
    formatTime(timestamp) {
      return new Date(timestamp).toLocaleTimeString()
    },
  },
}
</script>

<style scoped>
.agents {
  padding: 20px;
}

.tab-content {
  margin-top: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.model-selector {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chat-container {
  height: 520px;
  display: flex;
  flex-direction: column;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  background: #f5f5f5;
  border-radius: 4px;
  margin-bottom: 10px;
}

.message {
  margin-bottom: 15px;
}

.message-content {
  background: white;
  padding: 10px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.message.user .message-content {
  background: #e3f2fd;
  margin-left: 20px;
}

.message.assistant .message-content {
  background: #f3e5f5;
  margin-right: 20px;
}

.message-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 12px;
  color: #666;
}

.role {
  font-weight: bold;
}

.message-text {
  line-height: 1.5;
}

.tool-calls, .context-nodes {
  margin-top: 8px;
  font-size: 12px;
}

.input-area {
  margin-top: 10px;
}

.input-hint {
  font-size: 12px;
  color: #999;
  margin-top: 5px;
}

.quick-actions .el-button {
  margin-bottom: 8px;
}

.status-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.session-info p {
  margin: 5px 0;
  font-size: 14px;
}

.knowledge-path {
  max-height: 200px;
  overflow-y: auto;
}

.reasoning-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.no-path {
  color: #999;
  font-style: italic;
}

.extraction-results, .stylization-results {
  margin-top: 20px;
}

.fact-result {
  margin-bottom: 10px;
}

.fact-content {
  margin-bottom: 10px;
  line-height: 1.5;
}

.fact-actions {
  display: flex;
  gap: 10px;
}

.fact-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.fact-summary {
  font-weight: bold;
  flex: 1;
}

.fact-relationships, .fact-entities {
  margin: 8px 0;
}

.fact-relationships strong, .fact-entities strong {
  margin-right: 8px;
}
</style>