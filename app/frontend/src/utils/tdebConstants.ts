/**
 * Shared presentation constants for the tDEB simulator.
 *
 * Node colours mirror the backend's node factories so a template renders with
 * the same palette it was authored with.
 */
import type { NodeTypeId, SolverMethod, TransportTypeId } from './tdebApi'

export const NODE_COLORS: Record<string, string> = {
  food: '#66BB6A',
  assimilation: '#9CCC65',
  reserve: '#FFA726',
  structure: '#42A5F5',
  maturity: '#AB47BC',
  reproduction: '#EF5350',
  gonad: '#EC407A',
  toxicant: '#26C6DA',
  damage: '#78909C',
  custom: '#90A4AE',
}

export const NODE_RADIUS: Record<string, number> = {
  food: 20,
  assimilation: 22,
  reserve: 28,
  structure: 26,
  maturity: 22,
  reproduction: 24,
  gonad: 20,
  toxicant: 18,
  damage: 18,
  custom: 20,
}

export const DEFAULT_NODE_COLOR = '#90A4AE'
export const DEFAULT_NODE_RADIUS = 20

export function nodeColor(type: string): string {
  return NODE_COLORS[type] || DEFAULT_NODE_COLOR
}

export function nodeRadius(type: string): number {
  return NODE_RADIUS[type] ?? DEFAULT_NODE_RADIUS
}

export const NODE_TYPES: { value: NodeTypeId; label: string }[] = [
  { value: 'food', label: 'Food (X)' },
  { value: 'reserve', label: 'Reserve (E)' },
  { value: 'structure', label: 'Structure (V)' },
  { value: 'maturity', label: 'Maturity (E_H)' },
  { value: 'reproduction', label: 'Reproduction (E_R)' },
  { value: 'gonad', label: 'Gonad' },
  { value: 'toxicant', label: 'Toxicant' },
  { value: 'damage', label: 'Damage' },
  { value: 'custom', label: 'Custom' },
]

export const TRANSPORT_TYPES: { value: TransportTypeId; label: string }[] = [
  { value: 'linear', label: 'Linear (J = k·X)' },
  { value: 'michaelis_menten', label: 'Michaelis–Menten' },
  { value: 'gradient', label: 'Gradient (J = k·ΔX)' },
  { value: 'kappa_split', label: 'κ-split' },
  { value: 'regulated', label: 'Regulated (signal)' },
  { value: 'threshold', label: 'Threshold' },
  { value: 'fixed', label: 'Fixed flux' },
  { value: 'custom', label: 'Custom formula' },
]

export const SOLVER_METHODS: { value: SolverMethod; label: string }[] = [
  { value: 'RK45', label: 'RK45 (Runge–Kutta)' },
  { value: 'RK23', label: 'RK23' },
  { value: 'Radau', label: 'Radau (stiff)' },
  { value: 'BDF', label: 'BDF (stiff)' },
  { value: 'LSODA', label: 'LSODA (auto)' },
]

/** Plot series colours, cycled in order. */
export const PLOT_COLORS = [
  '#FFA726', '#42A5F5', '#AB47BC', '#EF5350', '#66BB6A',
  '#EC407A', '#26C6DA', '#FBC02D', '#78909C', '#FF7043',
]

export const FORMULA_VARIABLES =
  'X_source, X_target, T_corr, T, signal, k, V_max, K_m, kappa, threshold, eta, n, s'
export const FORMULA_FUNCTIONS = 'sin, cos, tan, exp, log, log10, sqrt, abs, min, max, pi'

export const KELVIN_OFFSET = 273.15

/** Format a number for compact display in equations and labels. */
export function formatNumber(v: number | undefined | null): string {
  if (v === undefined || v === null || Number.isNaN(v)) return '?'
  const abs = Math.abs(v)
  if (abs === 0) return '0'
  if (abs >= 1e5 || abs < 1e-3) return v.toExponential(3)
  return String(parseFloat(v.toPrecision(4)))
}
