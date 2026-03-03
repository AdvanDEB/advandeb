import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

// Visualization API
export const vizAPI = {
  listSchemas: () => api.get('/viz/schemas'),
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
