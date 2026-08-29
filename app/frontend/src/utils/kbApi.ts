/**
 * Typed helpers for the Knowledge Builder API (/api/kb/*)
 */
import api from './api'
import type { GraphArtifact, GraphArtifactMeta } from '@/types/graphArtifact'

export interface GraphSchema {
  _id: string
  name: string
  description?: string
  is_builtin?: boolean
  node_types?: unknown[]
  edge_types?: unknown[]
  artifact?: GraphArtifactMeta
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
  supports?: number
  opposes?: number
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

export interface GraphSnapshotView extends GraphData {
  schema: string
  mode: 'root' | 'expanded_cluster' | string
  expanded_cluster_id: string | null
  snapshot_version: number
  built_at?: string
  stats: GraphStats & { cluster_count?: number }
  type_counts: TypeCounts
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
  num_files?: number
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

// Field names must match GET /kb/kg/stats exactly. They previously read
// total/suggested/confirmed, none of which the endpoint returns, so every stat
// card fell through its `?? 0` and displayed zero while 6,003 relations existed.
export interface KgStats {
  total_documents: number
  linked_documents: number
  unlinked_documents: number
  total_relations: number
  confirmed_relations: number
  suggested_relations: number
  index_entries: number
  index_root_taxid: number | null
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

export async function fetchArtifactStatus(schemaId: string): Promise<GraphArtifactMeta> {
  const { data } = await api.get(`/kb/viz/schema/${schemaId}/status`)
  return data
}

export async function fetchGraphArtifact(schemaId: string, buildId?: string): Promise<GraphArtifact> {
  // The build id makes each rebuild its own URL. Belt-and-braces alongside the
  // endpoint's Cache-Control: it means no cache anywhere in the chain can hand
  // back a previous build, while unchanged builds still hit cache on revisit.
  const { data } = await api.get(`/kb/viz/schema/${schemaId}/artifact`, {
    params: buildId ? { build: buildId } : undefined,
  })
  return data
}

// ---- Graph data -------------------------------------------------------------

export async function fetchOverview(schemaId: string, limit = 200): Promise<GraphData> {
  const { data } = await api.get(`/kb/viz/schema/${schemaId}/overview`, {
    params: { limit },
  })
  return data
}

export async function fetchGraphWithLayout(
  schemaId: string,
  limit = 50_000,
  layout = 'force',
): Promise<GraphData> {
  const { data } = await api.get(`/kb/viz/schema/${schemaId}`, {
    params: { limit, layout },
  })
  return data
}

export async function fetchSnapshotView(
  schemaId: string,
  expandCluster?: string | null,
  rebuild = false,
): Promise<GraphSnapshotView> {
  const { data } = await api.get(`/kb/viz/schema/${schemaId}/snapshot`, {
    params: {
      expand_cluster: expandCluster ?? undefined,
      rebuild: rebuild || undefined,
    },
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

export interface ReviewQueues {
  facts_pending: number
  facts_total: number
  sf_support_suggested: number
  sf_support_total: number
  studies_suggested: number
  studies_confirmed: number
  documents_off_domain: number
  documents_gated: number
}

/** Pipeline output awaiting review — distinct from user submissions. */
export async function fetchReviewQueues(): Promise<ReviewQueues> {
  const { data } = await api.get('/kb/db/review-queues')
  return data
}

export interface ResetPreview {
  clears: { name: string; count: number }[]
  keeps: { name: string; count: number }[]
  total_rows: number
}

/** What a reset would clear, straight from the list the reset itself uses. */
export async function fetchResetPreview(): Promise<ResetPreview> {
  const { data } = await api.get('/kb/db/reset/preview')
  return data
}

// NOTE: the response key is `cleared`, not `deleted`. This interface previously
// declared `deleted`, so the success dialog rendered "Deleted: undefined" after
// every reset — a hand-written type can't be checked against the server.
export async function resetKnowledgeBase(): Promise<{ status: string; cleared: Record<string, number> }> {
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

export async function fetchJobs(batchId?: string, status?: string, limit = 2000): Promise<IngestionJob[]> {
  const { data } = await api.get('/kb/ingestion/jobs', {
    params: { batch_id: batchId, status, limit },
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

// ---- KB Document metadata ---------------------------------------------------

export interface KbDocumentMeta {
  _id: string
  title?: string | null
  doi?: string | null
  authors?: string[]
  year?: number | null
  journal?: string | null
  abstract?: string | null
  keywords?: string[] | string | null
  volume?: string | number | null
  issue?: string | number | null
  pages?: string | null
  isbn?: string | null
  // OpenAlex-sourced fields
  openalex_id?: string | null
  pmid?: string | null
  cited_by_count?: number | null
  is_retracted?: boolean | null
  source_type?: string | null
  source_path?: string | null
  general_domain?: string | null
  processing_status?: string | null
  references?: string[]
  created_at?: string | null
  updated_at?: string | null
}

export async function fetchKbDocument(documentId: string): Promise<KbDocumentMeta | null> {
  try {
    const { data } = await api.get(`/kb/documents/${documentId}`)
    return data as KbDocumentMeta
  } catch (err: any) {
    const status = err?.response?.status
    // 404 → document not in DB (normal for external citations)
    // 422 → invalid ObjectId (external_document nodes whose entity_id is a DOI string)
    if (status === 404 || status === 422) return null
    console.error('[fetchKbDocument] unexpected error for id', documentId, err)
    throw err
  }
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

// ---- KG relation review -----------------------------------------------------

export interface KgRelation {
  _key: string
  document_id: string
  document_title: string | null
  document_domain_relevant: boolean | null
  tax_id: number
  taxon_name: string | null
  taxon_rank: string | null
  relation_type: string
  confidence: number
  evidence: string
  status: string
  created_by: string
  created_at: string
  updated_at: string
}

export interface KgRelationFilter {
  status?: string
  min_confidence?: number
  max_confidence?: number
  created_by?: string
}

export async function fetchKgRelations(
  filter: KgRelationFilter = {},
  options: { sample?: boolean; limit?: number; skip?: number } = {},
): Promise<{ total: number; relations: KgRelation[] }> {
  const { data } = await api.get('/kb/kg/relations', {
    params: { ...filter, ...options },
  })
  return data
}

export interface AutoResolveRule {
  rule: string
  action: 'confirmed' | 'rejected'
  description: string
  matched: number
  applied: number
}

export interface AutoResolveResult {
  dry_run: boolean
  rules: AutoResolveRule[]
  total: number
  remaining_suggested: number
}

/**
 * Apply the deterministic link rules. Defaults to a dry run: most of this queue
 * needs no judgement, so the rules do the bulk of the work and a human only
 * sees what genuinely turns on one.
 */
export async function autoResolveKgRelations(dryRun = true): Promise<AutoResolveResult> {
  const { data } = await api.post('/kb/kg/relations/auto-resolve', { dry_run: dryRun })
  return data
}

export async function updateKgRelation(
  relationKey: string,
  status: 'confirmed' | 'rejected',
): Promise<unknown> {
  const { data } = await api.put(`/kb/kg/relations/${relationKey}`, { status })
  return data
}

/**
 * Confirm or reject every relation matching `filter`.
 *
 * `dryRun` defaults to true — the caller is expected to show the matched count
 * and have the user confirm before applying, because a bulk status change can
 * touch thousands of rows and cannot be undone from the UI.
 */
export async function bulkUpdateKgRelations(
  status: 'confirmed' | 'rejected',
  filter: KgRelationFilter,
  dryRun = true,
): Promise<{ matched: number; updated: number; dry_run: boolean; status: string }> {
  const { data } = await api.post('/kb/kg/relations/bulk', { status, filter, dry_run: dryRun })
  return data
}

// ---- Suggestions (documents & facts) ----------------------------------------

export interface DocumentSuggestion {
  _id: string
  title: string
  source_type: string
  status: string
  uploader_id?: string
  extracted_facts_count?: number
  metadata?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export interface FactSuggestion {
  _id: string
  statement: string
  status: string
  tags?: string[]
  confidence?: number | null
  source_document_id?: string | null
  creator_id?: string
  review_comment?: string | null
  created_at?: string
  updated_at?: string
}

export interface StylizedFactSuggestion {
  _id: string
  summary: string
  status: string
  tags?: string[]
  supporting_fact_ids?: string[]
  creator_id?: string
  review_comment?: string | null
  created_at?: string
  updated_at?: string
}

export async function fetchDocumentSuggestions(status = 'suggestion', limit = 100): Promise<DocumentSuggestion[]> {
  const { data } = await api.get('/documents', { params: { status, limit } })
  return data
}

export async function approveDocument(
  documentId: string,
  action: 'approve' | 'reject',
  comment?: string,
): Promise<{ updated: boolean; status: string; batch_id?: string }> {
  const { data } = await api.patch(`/documents/${documentId}/approve`, { action, comment })
  return data
}

export async function fetchFactSuggestions(statusFilter = 'suggestion', limit = 100): Promise<FactSuggestion[]> {
  const { data } = await api.get('/facts', { params: { status_filter: statusFilter, limit } })
  return data
}

export async function reviewFact(
  factId: string,
  status: 'published' | 'rejected' | 'pending_review',
  reviewComment?: string,
): Promise<{ updated: boolean; status: string }> {
  const { data } = await api.patch(`/facts/${factId}/review`, { status, review_comment: reviewComment })
  return data
}

export async function fetchStylizedFactSuggestions(statusFilter = 'suggestion', limit = 100): Promise<StylizedFactSuggestion[]> {
  const { data } = await api.get('/facts/stylized/', { params: { status_filter: statusFilter, limit } })
  return data
}

export async function reviewStylizedFact(
  sfId: string,
  status: 'published' | 'rejected',
  reviewComment?: string,
): Promise<{ updated: boolean; status: string }> {
  const { data } = await api.patch(`/facts/stylized/${sfId}/review`, { status, review_comment: reviewComment })
  return data
}
