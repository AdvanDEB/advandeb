/**
 * Shared color palette for the Knowledge Builder graph.
 *
 * Designed for Obsidian-style dark canvas: vivid, high-contrast colors that
 * appear to glow against a near-black background.
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
  document:          [99/255,  179/255, 255/255, 1.0],   // vivid sky-blue
  external_document: [148/255, 163/255, 184/255, 0.55],  // slate-400 (faded)
  fact:              [52/255,  231/255, 158/255, 1.0],   // bright emerald
  stylized_fact:     [255/255, 200/255,  40/255, 1.0],   // bright amber
  taxon:             [179/255, 148/255, 255/255, 1.0],   // bright violet
  user:              [255/255, 115/255, 115/255, 1.0],   // vivid red
  chat_session:      [125/255, 221/255, 255/255, 1.0],   // sky-300
  species:           [210/255, 140/255, 255/255, 1.0],   // bright purple
  genus:             [185/255, 155/255, 255/255, 1.0],   // violet-400+
  family:            [160/255, 110/255, 255/255, 1.0],   // violet-500+
  order:             [130/255,  70/255, 240/255, 0.9],   // deeper violet
  class:             [110/255,  50/255, 210/255, 0.85],  // deep violet
  phylum:            [255/255, 155/255,  70/255, 0.9],   // vivid orange
  kingdom:           [255/255,  90/255,  90/255, 0.9],   // vivid red
}

export const NODE_TYPE_HEX: Record<string, string> = {
  document:          '#63b3ff',
  external_document: '#94a3b8',
  fact:              '#34e79e',
  stylized_fact:     '#ffc828',
  taxon:             '#b394ff',
  user:              '#ff7373',
  chat_session:      '#7dddff',
  species:           '#d28cff',
  genus:             '#b99bff',
  family:            '#a06eff',
  order:             '#8246f0',
  class:             '#6e32d2',
  phylum:            '#ff9b46',
  kingdom:           '#ff5a5a',
}

export const DEFAULT_NODE_COLOR: [number, number, number, number] = [255/255, 140/255, 210/255, 1.0] // vivid pink
export const DEFAULT_NODE_HEX = '#ff8cd2'

// ---- Edges ------------------------------------------------------------------

export const EDGE_TYPE_COLORS: Record<string, [number, number, number, number]> = {
  supports:       [ 52/255, 231/255, 120/255, 0.75],  // bright green
  extracted_from: [ 99/255, 179/255, 255/255, 0.65],  // sky-blue
  opposes:        [255/255,  80/255,  80/255, 0.72],  // vivid red
  is_child_of:    [200/255, 200/255, 200/255, 0.22],  // subtle gray
  studies:        [220/255, 165/255,  90/255, 0.60],  // amber
  cites:          [100/255, 195/255, 255/255, 0.55],  // sky
  regulates:      [255/255, 170/255,  60/255, 0.55],  // orange
  depends_on:     [ 60/255, 195/255, 230/255, 0.55],  // cyan
  exhibited_by:   [200/255,  70/255, 240/255, 0.55],  // purple
  has_session:    [255/255, 115/255, 115/255, 0.45],  // red
  references_document: [125/255, 221/255, 255/255, 0.45],
}

export const EDGE_TYPE_HEX: Record<string, string> = {
  supports:       '#34e778',
  extracted_from: '#63b3ff',
  opposes:        '#ff5050',
  is_child_of:    '#c8c8c8',
  studies:        '#dca55a',
  cites:          '#64c3ff',
  regulates:      '#ffaa3c',
  depends_on:     '#3cc3e6',
  exhibited_by:   '#c846f0',
  has_session:    '#ff7373',
  references_document: '#7dddff',
}

export const DEFAULT_EDGE_COLOR: [number, number, number, number] = [140/255, 140/255, 160/255, 0.30]
export const DEFAULT_EDGE_HEX = '#8c8ca0'
