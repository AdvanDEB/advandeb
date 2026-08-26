/**
 * Per-schema description of how the graph is arranged, and whether the
 * backend's precomputed layout is worth using for it.
 *
 * Mirrors `SCHEMA_LAYOUT_MAP` in
 * `knowledge-builder/advandeb_kb/services/graph_query_layouts.py`. Keep the two
 * in step: if a schema's layout function changes shape, its entry here changes
 * with it.
 *
 * Why this distinction exists: the backend lays every schema out, but the
 * layouts are not equally informative. A radial taxonomy tree and modularity
 * communities encode real structure and should be shown as computed. Schemas
 * that merely bucket nodes by type produce a handful of dense balls with every
 * edge running between them — for those the client-side force simulation says
 * more, because it pulls each fact towards the stylized facts it actually
 * supports rather than into an undifferentiated "facts" pile.
 */

export type LayoutKind = 'tree' | 'community' | 'grouped'

export interface SchemaLayoutInfo {
  kind: LayoutKind
  /** Headline for the explanation panel. */
  title: string
  /** What decides which nodes end up near each other. */
  grouping: string
  /** What a node's position on the canvas encodes. */
  position: string
  /** Anything else worth knowing — colour meaning, link meaning. */
  notes: string[]
  /**
   * Whether the precomputed layout is the better default for this schema.
   * False means the force simulation is the better default; the user can still
   * override either way from the Layout control.
   */
  prefersServerLayout: boolean
}

const SCHEMA_LAYOUTS: Record<string, SchemaLayoutInfo> = {
  taxonomical: {
    kind: 'tree',
    title: 'Radial taxonomy tree',
    grouping: 'Not clustered — this is the taxonomy itself, so position is the hierarchy.',
    position:
      'Root at the centre, one ring per level. Sibling branches split the circle in proportion to how many descendants each contains, so no two branches overlap.',
    notes: [
      'Colour runs kingdom → species; grey-violet nodes are unranked clades.',
      'Larger nodes are taxa the corpus actually studies. The rest is the lineage that connects them back to the root.',
    ],
    prefersServerLayout: true,
  },
  citation: {
    kind: 'community',
    title: 'Citation communities',
    grouping:
      'Papers are grouped into communities by modularity — each blob is a set of papers that cite each other more than they cite the rest.',
    position: 'One blob per community, largest at the centre.',
    notes: [
      'Faded grey links are citations to papers outside the knowledge base.',
      'Node size grows with citation degree.',
    ],
    prefersServerLayout: true,
  },
  reproduction: {
    kind: 'community',
    title: 'Reproduction sub-corpus, by community',
    grouping:
      'Same modularity communities as the citation view, restricted to documents whose domain is reproduction, plus the facts and taxa derived from them.',
    position: 'One blob per community, largest at the centre.',
    notes: ['Node size grows with degree.'],
    prefersServerLayout: true,
  },
  sf_support: {
    kind: 'grouped',
    title: 'Evidence network',
    grouping:
      'The stored layout only buckets nodes by type — documents, facts, stylized facts — which says little, so this view is force-simulated by default.',
    position:
      'Under the simulation, facts settle next to the stylized facts they support and near the documents they came from. Clusters that emerge are bodies of evidence, not categories.',
    notes: [
      'Green links support a stylized fact, red links oppose it.',
      'Blue links join a fact to the document it was extracted from.',
    ],
    prefersServerLayout: false,
  },
  knowledge_graph: {
    kind: 'grouped',
    title: 'Integrated graph',
    grouping:
      'The stored layout groups by attribute — stylized facts by category, documents by domain, taxa by rank — which collapses into a few dense balls at this size, so it is force-simulated by default.',
    position:
      'Under the simulation, position reflects what each node is actually connected to across all four entity types.',
    notes: [
      'Blue documents, green facts, amber stylized facts, violet-to-pink taxa by rank.',
      'The largest graph here — expect the layout to take a few seconds to settle.',
    ],
    prefersServerLayout: false,
  },
  physiological_process: {
    kind: 'grouped',
    title: 'Process relationships',
    grouping:
      'Stored layout buckets by node type — stylized facts and the taxa that exhibit them — so this view is force-simulated by default.',
    position: 'Under the simulation, taxa settle beside the processes they exhibit.',
    notes: ['Amber stylized facts, violet-to-pink taxa by rank.'],
    prefersServerLayout: false,
  },
  chatbot: {
    kind: 'grouped',
    title: 'Chat activity',
    grouping:
      'Stored layout buckets by node type — users, chat sessions, and the knowledge-base entities those conversations cited — so this view is force-simulated by default.',
    position:
      'Under the simulation, sessions pull towards the documents and facts they referenced.',
    notes: ['Rebuilt as conversations accumulate, so it changes between visits.'],
    prefersServerLayout: false,
  },
}

const FALLBACK: SchemaLayoutInfo = {
  kind: 'grouped',
  title: 'Graph layout',
  grouping: 'Nodes are grouped by community detection.',
  position: 'One blob per community, largest at the centre.',
  notes: [],
  prefersServerLayout: false,
}

export function schemaLayoutInfo(schemaName: string): SchemaLayoutInfo {
  return SCHEMA_LAYOUTS[schemaName] ?? FALLBACK
}

export function prefersServerLayout(schemaName: string): boolean {
  return schemaLayoutInfo(schemaName).prefersServerLayout
}
