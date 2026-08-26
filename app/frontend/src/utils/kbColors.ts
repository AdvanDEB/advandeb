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

/**
 * Taxon ranks are coloured on a violet → pink ramp rather than a categorical
 * palette. Two reasons: rank is ordinal, so a ramp says something true about
 * the data; and staying inside the violet family keeps "purple = organism"
 * legible in the mixed knowledge_graph view, where taxa sit alongside
 * blue documents, green facts and amber stylized facts.
 *
 * `clade` (NCBI's unranked lineage nodes) is deliberately desaturated — those
 * nodes are scaffolding that connects the tree, not findings.
 */
export const NODE_TYPE_COLORS: Record<string, [number, number, number, number]> = {
  document:          [99/255,  179/255, 255/255, 1.0],   // vivid sky-blue
  external_document: [148/255, 163/255, 184/255, 0.55],  // slate-400 (faded)
  fact:              [52/255,  231/255, 158/255, 1.0],   // bright emerald
  stylized_fact:     [255/255, 200/255,  40/255, 1.0],   // bright amber
  taxon:             [179/255, 148/255, 255/255, 1.0],   // bright violet
  user:              [255/255, 115/255, 115/255, 1.0],   // vivid red
  chat_session:      [125/255, 221/255, 255/255, 1.0],   // sky-300
  // Taxon ranks, innermost ring → outermost.
  kingdom:           [106/255,  92/255, 255/255, 1.0],
  phylum:            [138/255,  92/255, 255/255, 1.0],
  class:             [165/255,  92/255, 245/255, 1.0],
  order:             [189/255,  92/255, 224/255, 1.0],
  family:            [209/255,  92/255, 196/255, 1.0],
  genus:             [224/255,  92/255, 163/255, 1.0],
  species:           [238/255, 107/255, 143/255, 1.0],
  clade:             [123/255, 116/255, 150/255, 0.7],
}

export const NODE_TYPE_HEX: Record<string, string> = {
  document:          '#63b3ff',
  external_document: '#94a3b8',
  fact:              '#34e79e',
  stylized_fact:     '#ffc828',
  taxon:             '#b394ff',
  user:              '#ff7373',
  chat_session:      '#7dddff',
  kingdom:           '#6a5cff',
  phylum:            '#8a5cff',
  class:             '#a55cf5',
  order:             '#bd5ce0',
  family:            '#d15cc4',
  genus:             '#e05ca3',
  species:           '#ee6b8f',
  clade:             '#7b7496',
}

export const DEFAULT_NODE_COLOR: [number, number, number, number] = [176/255, 180/255, 200/255, 1.0] // neutral slate
export const DEFAULT_NODE_HEX = '#b0b4c8'

// ---- Edges ------------------------------------------------------------------

export const EDGE_TYPE_COLORS: Record<string, [number, number, number, number]> = {
  supports:       [ 52/255, 231/255, 120/255, 0.75],  // bright green
  extracted_from: [ 99/255, 179/255, 255/255, 0.65],  // sky-blue
  opposes:        [255/255,  80/255,  80/255, 0.72],  // vivid red
  // In the taxonomy view the edges *are* the structure, so they carry more
  // weight than the incidental link types in the other graphs.
  is_child_of:    [168/255, 150/255, 220/255, 0.40],  // muted violet
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
  is_child_of:    '#a896dc',
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
