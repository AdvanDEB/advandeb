import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

// Visualization API
export const vizAPI = {
  listSchemas: () => api.get('/viz/schemas'),
  seedSchemas: () => api.post('/viz/seed'),
  getSchemaGraph: (id, limit = 5000) => api.get(`/viz/schema/${id}`, { params: { limit } }),
  getSchemaStats: (id) => api.get(`/viz/schema/${id}/stats`),
  rebuildSchema: (id, body = {}) => api.post(`/viz/schema/${id}/rebuild`, body),
}

// Database API
export const dbAPI = {
  listCollections: () => api.get('/db/collections'),
  getCollectionDocs: (name, limit = 20, skip = 0) =>
    api.get(`/db/${name}`, { params: { limit, skip } }),
}

// Filesystem API
export const fsAPI = {
  browse: (path) => api.get('/fs/browse', { params: { path } }),
}

// KG Builder API
export const kgAPI = {
  getStats: () => api.get('/kg/stats'),
  linkSync: (rootTaxid = 40674, limit = 200, skip = 0, overwrite = false) =>
    api.post('/kg/link/sync', null, { params: { root_taxid: rootTaxid, limit, skip, overwrite } }),
  linkAsync: (rootTaxid = 40674, limit = 1000, skip = 0) =>
    api.post('/kg/link', null, { params: { root_taxid: rootTaxid, limit, skip } }),
  listRelations: (params = {}) => api.get('/kg/relations', { params }),
  updateRelation: (id, body) => api.put(`/kg/relations/${id}`, body),
  linkAgentSync: (model = 'mistral', limit = 20, skip = 0, overwrite = false) =>
    api.post('/kg/link/agent/sync', null, { params: { model, limit, skip, overwrite } }),
  linkAgentAsync: (model = 'mistral', limit = 500, skip = 0) =>
    api.post('/kg/link/agent', null, { params: { model, limit, skip } }),
}

// Agents API
export const agentsAPI = {
  getModels: () => api.get('/agents/models'),
}

// Ingestion API — unchanged
export const ingestionAPI = {
  getSources: () => api.get('/ingestion/sources'),
  scanFolders: (folders) => api.post('/ingestion/scan', folders),
  runBatch: (batchId) => api.post('/ingestion/run', null, { params: { batch_id: batchId } }),
  getBatches: (limit = 20) => api.get('/ingestion/batches', { params: { limit } }),
  getBatch: (batchId) => api.get(`/ingestion/batches/${batchId}`),
  getJobs: (params = {}) => api.get('/ingestion/jobs', { params }),
  getJob: (jobId) => api.get(`/ingestion/jobs/${jobId}`),
}

export default api
