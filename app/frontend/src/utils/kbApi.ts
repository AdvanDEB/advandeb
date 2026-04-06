/**
 * Typed helpers for the Knowledge Builder API (/api/kb/*)
 */
import api from './api'

export interface GraphSchema {
  _id: string
  name: string
  node_types?: unknown[]
  edge_types?: unknown[]
}

export interface GraphNode {
  _id: string
  schema_id: string
  node_type: string
  entity_collection: string
  entity_id: string
  label: string
  properties: Record<string, unknown>
  x2d?: number
  y2d?: number
  degree?: number
}

export interface GraphEdge {
  _id: string
  schema_id: string
  edge_type: string
  source_node_id: string
  target_node_id: string
  weight: number
  properties: Record<string, unknown>
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface GraphStats {
  // The API returns node_count / edge_count; nodes / edges are kept as
  // aliases so existing template bindings continue to work after mapping.
  node_count?: number
  edge_count?: number
  nodes?: number
  edges?: number
  density?: number
}

export interface TypeCounts {
  node_types: Record<string, number>
  edge_types: Record<string, number>
}

export interface IngestionBatch {
  _id: string
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'mixed' | 'stopped' | string
  general_domain?: string
  source_root?: string
  created_at?: string
  updated_at?: string
}

export interface UploadResult {
  batch_id: string
  job_id: string
  filename: string
  status: string
}

export interface ScanResult {
  batch_id: string
  num_files: number
}

export interface KgStats {
  total: number
  suggested: number
  confirmed: number
  rejected: number
}

export interface IngestionJob {
  _id: string
  batch_id: string
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | string
  stage?: string
  progress?: number
  error_message?: string
  source_path_or_url?: string
  already_processed?: boolean
  created_at?: string
}

// ---- Schemas ----------------------------------------------------------------

export async function fetchSchemas(): Promise<GraphSchema[]> {
  const { data } = await api.get('/kb/viz/schemas')
  return data
}

// ---- Graph data -------------------------------------------------------------

export async function fetchOverview(schemaId: string, limit = 200): Promise<GraphData> {
  const { data } = await api.get(`/kb/viz/schema/${schemaId}/overview`, {
    params: { limit },
  })
  return data
}

export async function fetchAllEdges(schemaId: string): Promise<GraphEdge[]> {
  const { data } = await api.get(`/kb/viz/schema/${schemaId}/edges`)
  return data
}

export async function expandNode(
  schemaId: string,
  nodeId: string,
  loadedNodeIds: string[],
): Promise<GraphData> {
  const { data } = await api.post(`/kb/viz/schema/${schemaId}/expand/${nodeId}`, {
    loaded_node_ids: loadedNodeIds,
  })
  return data
}

export interface PagedNodes {
  nodes: GraphNode[]
  edges: GraphEdge[]
  page: number
  page_size: number
  total: number
  has_more: boolean
}

export async function fetchNodeTypesPaged(
  schemaId: string,
  nodeType: string,
  page = 0,
  pageSize = 500,
): Promise<PagedNodes> {
  const { data } = await api.get(`/kb/viz/schema/${schemaId}/type/${nodeType}/page`, {
    params: { page, page_size: pageSize },
  })
  return data
}

// ---- Stats ------------------------------------------------------------------

export async function fetchStats(schemaId: string): Promise<GraphStats> {
  const { data } = await api.get(`/kb/viz/schema/${schemaId}/stats`)
  // Normalise: the API returns node_count / edge_count; expose them as
  // both the original keys AND the shorter nodes / edges aliases so that
  // all template bindings resolve correctly regardless of key name used.
  return {
    ...data,
    nodes: data.nodes ?? data.node_count,
    edges: data.edges ?? data.edge_count,
  }
}

export async function fetchTypeCounts(schemaId: string): Promise<TypeCounts> {
  const { data } = await api.get(`/kb/viz/schema/${schemaId}/stats/types`)
  return data
}

// ---- Control ----------------------------------------------------------------

export async function rebuildSchema(schemaId: string): Promise<unknown> {
  const { data } = await api.post(`/kb/viz/schema/${schemaId}/rebuild`)
  return data
}

export async function seedSchemas(): Promise<unknown> {
  const { data } = await api.post('/kb/viz/seed')
  return data
}

export async function resetKnowledgeBase(): Promise<{ status: string; deleted: Record<string, number> }> {
  const { data } = await api.post('/kb/db/reset')
  return data
}

// ---- Database browser -------------------------------------------------------

export interface CollectionInfo {
  name: string
  count: number
}

export async function fetchCollections(): Promise<CollectionInfo[]> {
  const { data } = await api.get('/kb/db/collections')
  return data
}

export async function fetchCollectionDocs(
  collection: string,
  limit = 20,
  skip = 0,
): Promise<unknown[]> {
  const { data } = await api.get(`/kb/db/${collection}`, { params: { limit, skip } })
  return data
}

// ---- Ingestion --------------------------------------------------------------

export async function fetchBatches(limit = 20): Promise<IngestionBatch[]> {
  const { data } = await api.get('/kb/ingestion/batches', { params: { limit } })
  return data?.batches ?? data
}

export async function fetchJobs(batchId?: string, status?: string): Promise<IngestionJob[]> {
  const { data } = await api.get('/kb/ingestion/jobs', {
    params: { batch_id: batchId, status },
  })
  return data?.jobs ?? data
}

export interface SourceEntry {
  name: string
  path: string
  pdf_count: number
}

export interface SourcesResponse {
  entries: SourceEntry[]
}

export async function fetchFolderFiles(folder: string): Promise<unknown> {
  const { data } = await api.get(`/kb/ingestion/sources/${encodeURIComponent(folder)}`)
  return data
}

export async function scanFolders(folders: string[], files: string[] = [], generalDomain?: string): Promise<ScanResult> {
  const { data } = await api.post('/kb/ingestion/scan', { folders, files, general_domain: generalDomain })
  return data
}

export async function uploadPdf(file: File, generalDomain?: string): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  const params = generalDomain ? { general_domain: generalDomain } : {}
  const { data } = await api.post('/kb/ingestion/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    params,
  })
  return data
}

export async function runBatch(batchId: string): Promise<unknown> {
  const { data } = await api.post('/kb/ingestion/run', { batch_id: batchId })
  return data
}

export async function deleteBatch(batchId: string): Promise<void> {
  await api.delete(`/kb/ingestion/batches/${batchId}`)
}

export async function stopBatch(batchId: string): Promise<IngestionBatch> {
  const { data } = await api.post(`/kb/ingestion/batches/${batchId}/stop`)
  return data
}

export async function fetchSources(): Promise<SourcesResponse> {
  const { data } = await api.get('/kb/ingestion/sources')
  return data
}

// ---- KG Builder -------------------------------------------------------------

export async function linkDocuments(limit = 1000, overwrite = false): Promise<unknown> {
  const { data } = await api.post('/kb/kg/link', { limit, overwrite })
  return data
}

export async function fetchKgStats(): Promise<KgStats> {
  const { data } = await api.get('/kb/kg/stats')
  return data
}
