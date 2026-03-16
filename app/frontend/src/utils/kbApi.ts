import axios from 'axios'

// Dedicated Axios instance for the Knowledge Builder dev-server backend.
// This backend runs separately (default: port 8500) and has no authentication —
// access is enforced at the frontend router level (requiresKB role guard).
const kbApi = axios.create({
  baseURL: import.meta.env.VITE_KB_API_URL ?? 'http://localhost:8500/api',
  timeout: 60000,
})

// ── Visualization API ──────────────────────────────────────────────────────────
export const vizAPI = {
  listSchemas: () => kbApi.get('/viz/schemas'),
  seedSchemas: () => kbApi.post('/viz/seed'),
  getSchemaGraph: (id: string, limit = 5000) =>
    kbApi.get(`/viz/schema/${id}`, { params: { limit } }),
  getSchemaStats: (id: string) => kbApi.get(`/viz/schema/${id}/stats`),
  rebuildSchema: (id: string, body: Record<string, unknown> = {}) =>
    kbApi.post(`/viz/schema/${id}/rebuild`, body),
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
  streamBatchProgress: (batchId: string): EventSource => {
    const base = (import.meta.env.VITE_KB_API_URL ?? 'http://localhost:8500/api').replace(/\/$/, '')
    return new EventSource(`${base}/ingestion/batches/${batchId}/stream`)
  },
}

export default kbApi
