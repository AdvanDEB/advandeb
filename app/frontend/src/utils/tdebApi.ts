/**
 * Typed helpers for the tDEB simulator API (/api/tdeb/*)
 */
import api from './api'

export type NodeTypeId =
  | 'food' | 'assimilation' | 'reserve' | 'structure' | 'maturity'
  | 'reproduction' | 'gonad' | 'damage' | 'toxicant' | 'custom'

export type TransportTypeId =
  | 'linear' | 'michaelis_menten' | 'gradient' | 'kappa_split'
  | 'regulated' | 'threshold' | 'fixed' | 'custom'

export type SolverMethod = 'RK45' | 'RK23' | 'Radau' | 'BDF' | 'LSODA'

export interface TDebNodeParams {
  maintenance_rate: number
  specific_cost: number
  max_capacity: number
  T_ref: number
  T_A: number
  kappa: number
  efficiency: number
}

export interface TDebNode {
  id: string
  name: string
  node_type: NodeTypeId
  value: number
  initial_value: number
  x: number
  y: number
  color: string
  params: TDebNodeParams
}

export interface TDebEdgeParams {
  rate_constant: number
  V_max: number
  K_m: number
  kappa: number
  threshold: number
  efficiency: number
  hill_coeff: number
  signal_strength: number
  custom_formula: string
  T_ref: number
  T_A: number
}

export interface TDebEdge {
  id: string
  source_id: string
  target_id: string
  name: string
  transport_type: TransportTypeId
  current_flux: number
  params: TDebEdgeParams
  /** Present when a custom formula was saved but does not evaluate. */
  formula_error?: string
}

export interface TDebEnvironment {
  temperature: number
  food_density: number
  toxicant_conc: number
}

export interface TDebNetwork {
  id: string
  name: string
  nodes: Record<string, TDebNode>
  edges: Record<string, TDebEdge>
  environment: TDebEnvironment
}

export interface TDebModelSummary {
  id: string
  name: string
  n_nodes: number
  n_edges: number
  template_id: string | null
  created_at: string
  updated_at: string
}

export interface TDebTemplate {
  id: string
  name: string
  description: string
  category: 'template' | 'organism'
}

export interface SimulationResult {
  time: number[]
  states: Record<string, number[]>
  fluxes: Record<string, number[]>
  success: boolean
  message: string
  n_points: number
}

export interface SimulationRequest {
  t_end: number
  dt_output: number
  method: SolverMethod
  /** Kelvin. */
  temperature: number
  food_density: number
}

export interface EquationEntry {
  formula: string
  description?: string
  latex?: string
  variables?: string[]
  enabled?: boolean
  note?: string
}

export interface EquationDocument {
  transport: Record<string, EquationEntry>
  arrhenius: EquationEntry
  maintenance: EquationEntry
  efficiency: EquationEntry
  non_negativity: EquationEntry
  ode_rule?: EquationEntry
  [key: string]: unknown
}

/** A streamed snapshot from /ws/simulate. */
export interface StreamSnapshot {
  time?: number
  progress?: number
  nodes?: Record<string, { value: number; name: string }>
  flows?: Record<string, { flux: number; name: string }>
  done?: boolean
  error?: string
}

const BASE = '/tdeb'

// ─── Templates & models ──────────────────────────────────────────────

export async function listTemplates(): Promise<TDebTemplate[]> {
  const { data } = await api.get<TDebTemplate[]>(`${BASE}/templates`)
  return data
}

export async function listModels(): Promise<TDebModelSummary[]> {
  const { data } = await api.get<TDebModelSummary[]>(`${BASE}/models`)
  return data
}

/** Create from a template id, an imported document, or an empty named model. */
export async function createModel(payload: {
  template?: string
  network?: unknown
  name?: string
}): Promise<TDebNetwork> {
  const { data } = await api.post<TDebNetwork>(`${BASE}/models`, payload)
  return data
}

export async function getModel(modelId: string): Promise<TDebNetwork> {
  const { data } = await api.get<TDebNetwork>(`${BASE}/models/${modelId}`)
  return data
}

export async function renameModel(modelId: string, name: string): Promise<TDebNetwork> {
  const { data } = await api.put<TDebNetwork>(`${BASE}/models/${modelId}`, { name })
  return data
}

export async function deleteModel(modelId: string): Promise<void> {
  await api.delete(`${BASE}/models/${modelId}`)
}

export async function exportModel(modelId: string): Promise<TDebNetwork> {
  const { data } = await api.get<TDebNetwork>(`${BASE}/models/${modelId}/export`)
  return data
}

// ─── Nodes & edges ───────────────────────────────────────────────────

export async function addNode(modelId: string, payload: {
  name: string
  node_type: NodeTypeId
  x: number
  y: number
  initial_value: number
  color: string
  params?: Partial<TDebNodeParams>
}): Promise<TDebNode> {
  const { data } = await api.post<TDebNode>(`${BASE}/models/${modelId}/nodes`, payload)
  return data
}

export async function updateNode(
  modelId: string, nodeId: string, payload: Partial<Omit<TDebNode, 'id' | 'params'>> & {
    params?: Partial<TDebNodeParams>
  },
): Promise<TDebNode> {
  const { data } = await api.put<TDebNode>(`${BASE}/models/${modelId}/nodes/${nodeId}`, payload)
  return data
}

export async function deleteNode(modelId: string, nodeId: string): Promise<void> {
  await api.delete(`${BASE}/models/${modelId}/nodes/${nodeId}`)
}

export async function addEdge(modelId: string, payload: {
  source_id: string
  target_id: string
  name: string
  transport_type: TransportTypeId
  params?: Partial<TDebEdgeParams>
}): Promise<TDebEdge> {
  const { data } = await api.post<TDebEdge>(`${BASE}/models/${modelId}/edges`, payload)
  return data
}

export async function updateEdge(
  modelId: string, edgeId: string, payload: {
    name?: string
    transport_type?: TransportTypeId
    params?: Partial<TDebEdgeParams>
  },
): Promise<TDebEdge> {
  const { data } = await api.put<TDebEdge>(`${BASE}/models/${modelId}/edges/${edgeId}`, payload)
  return data
}

export async function deleteEdge(modelId: string, edgeId: string): Promise<void> {
  await api.delete(`${BASE}/models/${modelId}/edges/${edgeId}`)
}

// ─── Simulation ──────────────────────────────────────────────────────

export async function simulate(
  modelId: string, request: SimulationRequest,
): Promise<SimulationResult> {
  const { data } = await api.post<SimulationResult>(
    `${BASE}/models/${modelId}/simulate`, request,
  )
  return data
}

/**
 * Open the streaming-simulation socket.
 *
 * The JWT rides as a query param because the browser WebSocket API cannot set
 * an Authorization header on the upgrade request — the same approach the chat
 * socket already uses.
 */
export function openSimulationSocket(modelId: string): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = localStorage.getItem('access_token') || ''
  const url = `${protocol}//${window.location.host}/api/tdeb/ws/simulate/${modelId}`
    + `?token=${encodeURIComponent(token)}`
  return new WebSocket(url)
}

// ─── Equations ───────────────────────────────────────────────────────

export async function getEquations(): Promise<EquationDocument> {
  const { data } = await api.get<EquationDocument>(`${BASE}/equations`)
  return data
}

export async function updateEquation(
  section: string, key: string | null, payload: Record<string, unknown>,
): Promise<EquationDocument> {
  const { data } = await api.put<EquationDocument>(`${BASE}/equations`, {
    section, key, data: payload,
  })
  return data
}

export async function resetEquations(): Promise<EquationDocument> {
  const { data } = await api.post<EquationDocument>(`${BASE}/equations/reset`)
  return data
}

export async function validateFormula(
  formula: string,
): Promise<{ valid: boolean; error: string; variables: string[] }> {
  const { data } = await api.post<{ valid: boolean; error: string; variables: string[] }>(
    `${BASE}/equations/validate`, { formula },
  )
  return data
}
