import axios from 'axios'

// KB API is now served by the main app backend under /api/kb/.
// JWT auth is required — same token as the rest of the app.
const kbApi = axios.create({
  baseURL: '/api/kb',
  timeout: 60000,
})

kbApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ── Visualization API ──────────────────────────────────────────────────────────
export const vizAPI = {
  listSchemas: () => kbApi.get('/viz/schemas'),
  seedSchemas: () => kbApi.post('/viz/seed'),
  getSchemaGraph: (id: string, limit = 100000) =>
    kbApi.get(`/viz/schema/${id}`, { params: { limit } }),
  getSchemaStats: (id: string) => kbApi.get(`/viz/schema/${id}/stats`),
  rebuildSchema: (id: string, body: Record<string, unknown> = {}) =>
    kbApi.post(`/viz/schema/${id}/rebuild`, body),

  // Virtual graph / on-demand loading
  getSchemaOverview: (schemaId: string, limit = 200) =>
    kbApi.get(`/viz/schema/${schemaId}/overview`, { params: { limit } }),
  expandNode: (schemaId: string, nodeId: string, loadedIds: string[]) =>
    kbApi.post(`/viz/schema/${schemaId}/expand/${nodeId}`, { loaded_node_ids: loadedIds }),
  expandType: (schemaId: string, nodeType: string, loadedIds: string[]) =>
    kbApi.post(`/viz/schema/${schemaId}/type/${nodeType}`, { loaded_node_ids: loadedIds }),
}

// ── Database API ───────────────────────────────────────────────────────────────
export const dbAPI = {
  listCollections: () => kbApi.get('/db/collections'),
  getCollectionDocs: (name: string, limit = 20, skip = 0) =>
    kbApi.get(`/db/${name}`, { params: { limit, skip } }),
}

// ── Filesystem API ─────────────────────────────────────────────────────────────
export const fsAPI = {
  browse: (path: string) => kbApi.get('/fs/browse', { params: { path } }),
}

// ── KG Builder API ─────────────────────────────────────────────────────────────
export const kgAPI = {
  getStats: () => kbApi.get('/kg/stats'),
  linkSync: (rootTaxid = 40674, limit = 200, skip = 0, overwrite = false) =>
    kbApi.post('/kg/link/sync', null, {
      params: { root_taxid: rootTaxid, limit, skip, overwrite },
    }),
  linkAsync: (rootTaxid = 40674, limit = 1000, skip = 0) =>
    kbApi.post('/kg/link', null, {
      params: { root_taxid: rootTaxid, limit, skip },
    }),
  listRelations: (params: Record<string, unknown> = {}) =>
    kbApi.get('/kg/relations', { params }),
  updateRelation: (id: string, body: Record<string, unknown>) =>
    kbApi.put(`/kg/relations/${id}`, body),
  linkAgentSync: (model = 'mistral', limit = 20, skip = 0, overwrite = false) =>
    kbApi.post('/kg/link/agent/sync', null, {
      params: { model, limit, skip, overwrite },
    }),
  linkAgentAsync: (model = 'mistral', limit = 500, skip = 0) =>
    kbApi.post('/kg/link/agent', null, { params: { model, limit, skip } }),
}

// ── Agents API ────────────────────────────────────────────────────────────────
export const agentsAPI = {
  getModels: () => kbApi.get('/agents/models'),
}

// ── Ingestion API ─────────────────────────────────────────────────────────────
export const ingestionAPI = {
  getSources: () => kbApi.get('/ingestion/sources'),
  scanFolders: (folders: string[]) => kbApi.post('/ingestion/scan', folders),
  runBatch: (batchId: string) =>
    kbApi.post('/ingestion/run', null, { params: { batch_id: batchId } }),
  getBatches: (limit = 20) =>
    kbApi.get('/ingestion/batches', { params: { limit } }),
  getBatch: (batchId: string) => kbApi.get(`/ingestion/batches/${batchId}`),
  getJobs: (params: Record<string, unknown> = {}) =>
    kbApi.get('/ingestion/jobs', { params }),
  getJob: (jobId: string) => kbApi.get(`/ingestion/jobs/${jobId}`),
  uploadPdf: (file: File, generalDomain?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (generalDomain) form.append('general_domain', generalDomain)
    return kbApi.post('/ingestion/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  // SSE: JWT passed as ?token= because EventSource doesn't support custom headers
  streamBatchProgress: (batchId: string): EventSource => {
    const token = localStorage.getItem('access_token') ?? ''
    return new EventSource(
      `/api/kb/ingestion/batches/${batchId}/stream?token=${encodeURIComponent(token)}`
    )
  },
}

export default kbApi
