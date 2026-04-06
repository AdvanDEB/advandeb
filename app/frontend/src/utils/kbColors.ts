/**
 * Shared color palette for the Knowledge Builder graph.
 *
 * NODE_TYPE_COLORS  — RGBA in 0.0–1.0 float range for cosmos.gl setPointColors()
 * NODE_TYPE_HEX     — CSS hex strings for UI swatches (SchemaPanel, badges, etc.)
 * EDGE_TYPE_COLORS  — RGBA in 0.0–1.0 float range for cosmos.gl setLinkColors()
 * EDGE_TYPE_HEX     — CSS hex strings for UI swatches
 *
 * Keep these two representations in sync.  Adding a new type requires one entry
 * in the float palette and one in the hex palette.
 */

// ---- Nodes ------------------------------------------------------------------

export const NODE_TYPE_COLORS: Record<string, [number, number, number, number]> = {
  document:          [96/255,  165/255, 250/255, 1.0],   // blue-400
  external_document: [148/255, 163/255, 184/255, 0.71],  // slate-400 (faded)
  fact:              [52/255,  211/255, 153/255, 1.0],   // emerald-400
  stylized_fact:     [251/255, 191/255,  36/255, 1.0],   // amber-400
  taxon:             [167/255, 139/255, 250/255, 1.0],   // violet-400
  species:           [192/255, 132/255, 252/255, 1.0],   // purple-400
  genus:             [167/255, 139/255, 250/255, 1.0],   // violet-400
  family:            [139/255,  92/255, 246/255, 1.0],   // violet-500
  order:             [109/255,  40/255, 217/255, 0.86],  // violet-700
  class:             [ 91/255,  33/255, 182/255, 0.78],  // violet-800
  phylum:            [255/255, 145/255,  77/255, 0.86],  // orange
  kingdom:           [255/255,  80/255,  80/255, 0.86],  // red
}

export const NODE_TYPE_HEX: Record<string, string> = {
  document:          '#60a5fa',  // blue-400
  external_document: '#94a3b8',  // slate-400
  fact:              '#34d399',  // emerald-400
  stylized_fact:     '#fbbf24',  // amber-400
  taxon:             '#a78bfa',  // violet-400
  species:           '#c084fc',  // purple-400
  genus:             '#a78bfa',  // violet-400
  family:            '#8b5cf6',  // violet-500
  order:             '#6d28d9',  // violet-700
  class:             '#5b21b6',  // violet-800
  phylum:            '#f97316',  // orange-500
  kingdom:           '#ef4444',  // red-500
}

export const DEFAULT_NODE_COLOR: [number, number, number, number] = [244/255, 114/255, 182/255, 1.0] // pink-400
export const DEFAULT_NODE_HEX = '#f472b6'

// ---- Edges ------------------------------------------------------------------

export const EDGE_TYPE_COLORS: Record<string, [number, number, number, number]> = {
  supports:       [ 34/255, 197/255,  94/255, 0.72],  // green-500  #22c55e
  extracted_from: [ 59/255, 130/255, 246/255, 0.72],  // blue-500   #3b82f6
  opposes:        [239/255,  68/255,  68/255, 0.72],  // red-500    #ef4444
  is_child_of:    [180/255, 180/255, 180/255, 0.31],
  studies:        [200/255, 150/255,  80/255, 0.59],
  cites:          [100/255, 180/255, 255/255, 0.59],
  regulates:      [255/255, 160/255,  60/255, 0.51],
  depends_on:     [ 60/255, 180/255, 220/255, 0.51],
  exhibited_by:   [180/255,  60/255, 220/255, 0.51],
}

export const EDGE_TYPE_HEX: Record<string, string> = {
  supports:       '#22c55e',  // green-500
  extracted_from: '#3b82f6',  // blue-500
  opposes:        '#ef4444',  // red-500
  is_child_of:    '#b4b4b4',
  studies:        '#c89650',
  cites:          '#64b4ff',
  regulates:      '#ffa03c',
  depends_on:     '#3cb4dc',
  exhibited_by:   '#b43cdc',
}

export const DEFAULT_EDGE_COLOR: [number, number, number, number] = [128/255, 128/255, 128/255, 0.39]
export const DEFAULT_EDGE_HEX = '#94a3b8'
