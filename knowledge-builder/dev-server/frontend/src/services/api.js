import axios from 'axios'

const API_BASE_URL = '/api'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
})

// Knowledge Base API
export const knowledgeAPI = {
  // Facts
  getFacts: (params = {}) => api.get('/knowledge/facts', { params }),
  createFact: (fact) => api.post('/knowledge/facts', fact),
  getFact: (id) => api.get(`/knowledge/facts/${id}`),
  
  // Stylized Facts
  getStylizedFacts: (params = {}) => api.get('/knowledge/stylized-facts', { params }),
  createStylizedFact: (fact) => api.post('/knowledge/stylized-facts', fact),
  
  // Knowledge Graphs
  getGraphs: (params = {}) => api.get('/knowledge/graphs', { params }),
  createGraph: (graph) => api.post('/knowledge/graphs', graph),
  getGraph: (id) => api.get(`/knowledge/graphs/${id}`),
  
  // Search
  searchKnowledge: (query) => api.post('/knowledge/search', query),
}

// Data Processing API
export const dataAPI = {
  uploadPDF: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/data/upload-pdf', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  browseURL: (url, extractFacts = true) => 
    api.post('/data/browse-url', null, { params: { url, extract_facts: extractFacts } }),
  extractEntities: (text) => api.post('/data/extract-entities', { text }),
  processText: (text, extractFacts = true, extractEntities = true) =>
    api.post('/data/process-text', { text, extract_facts: extractFacts, extract_entities: extractEntities }),
  getDocuments: (params = {}) => api.get('/data/documents', { params }),
  getDocument: (id) => api.get(`/data/documents/${id}`),
}

// Agents API
export const agentsAPI = {
  // Legacy chat (backward compatibility)
  chat: (messages, model = 'llama2') =>
    api.post('/agents/chat', { messages, model }),
  
  // New agent-specific chat endpoints
  knowledgeBuilderChat: (messages, model = 'llama2', stream = false) =>
    api.post('/agents/knowledge-builder/chat', { messages, model, stream }),
  
  modelingAgentChat: (messages, model = 'llama2', stream = false) => {
    if (stream) {
      // Return a custom streaming handler
      return api.post('/agents/modeling/chat', { messages, model, stream: true }, {
        responseType: 'stream'
      })
    } else {
      return api.post('/agents/modeling/chat', { messages, model, stream })
    }
  },
  
  // Agent run endpoint
  runAgent: (agentType, message, model = 'llama2', sessionId = null, enableTools = true, maxToolCalls = 10) =>
    api.post('/agents/run', {
      agent_type: agentType,
      message,
      model,
      session_id: sessionId,
      enable_tools: enableTools,
      max_tool_calls: maxToolCalls
    }),
  
  // Document processing
  processDocument: (documentText, title = 'Unknown Document', authors = [], bibtex = null) =>
    api.post('/agents/process-document', {
      document_text: documentText,
      title,
      authors,
      bibtex
    }),
  
  // Biological model building
  buildModel: (organism, modelType, parameters = {}) =>
    api.post('/agents/build-model', {
      organism,
      model_type: modelType,
      parameters
    }),
  
  // Session management
  listSessions: (agentType = null) =>
    api.get('/agents/sessions', { params: { agent_type: agentType } }),
  
  deleteSession: (sessionId) =>
    api.delete(`/agents/sessions/${sessionId}`),
  
  // Legacy fact extraction and stylization (using new agents under the hood)
  extractFacts: (text, model = 'llama2') =>
    api.post('/agents/extract-facts', { text, model }),
  
  stylizeFacts: (facts, model = 'llama2') =>
    api.post('/agents/stylize-facts', { facts, model }),
  
  // Tool and model information
  getTools: () => api.get('/agents/tools'),
  getModels: () => api.get('/agents/models'),
}

// Visualization API
export const visualizationAPI = {
  getGraphVisualization: (graphId, layout = 'spring') =>
    api.get(`/viz/graph/${graphId}`, { params: { layout } }),
  createGraphFromFacts: (factIds, graphName, description = '') =>
    api.post('/viz/graph/create', { fact_ids: factIds, graph_name: graphName, description }),
  getNetworkStats: (graphId) => api.get(`/viz/network-stats/${graphId}`),
  updateGraphLayout: (graphId, layoutType, layoutParams = null) =>
    api.post(`/viz/layout/${graphId}`, { layout_type: layoutType, layout_params: layoutParams }),
  getEntityRelationships: (entity, depth = 2) =>
    api.get(`/viz/relationships/${entity}`, { params: { depth } }),
  detectCommunities: (graphId, algorithm = 'louvain') =>
    api.get(`/viz/cluster/${graphId}`, { params: { algorithm } }),
  exportGraph: (graphId, format = 'json') =>
    api.get(`/viz/export/${graphId}`, { params: { format } }),
}

// Ingestion API
export const ingestionAPI = {
  // List available source folders
  getSources: () => api.get('/ingestion/sources'),
  
  // Scan folders and create batch + jobs
  scanFolders: (folders) => api.post('/ingestion/scan', folders),
  
  // Run ingestion for a batch
  runBatch: (batchId) => api.post('/ingestion/run', { batch_id: batchId }),
  
  // List batches
  getBatches: (limit = 20) => api.get('/ingestion/batches', { params: { limit } }),
  
  // Get batch details
  getBatch: (batchId) => api.get(`/ingestion/batches/${batchId}`),
  
  // List jobs
  getJobs: (params = {}) => api.get('/ingestion/jobs', { params }),
  
  // Get job details
  getJob: (jobId) => api.get(`/ingestion/jobs/${jobId}`),
}

export default api
