export interface GraphArtifactMeta {
  schema_id: string
  schema_name: string
  format: 'advandeb-graph-artifact'
  format_version: number
  build_id: string
  source_revision: string
  status: 'missing' | 'ready' | 'building' | 'failed' | 'stale' | 'too_large_for_browser'
  built_at: string | null
  layout_name: string | null
  node_count: number
  edge_count: number
  density: number
  type_counts: {
    node_types: Record<string, number>
    edge_types: Record<string, number>
  }
  bounds_2d: {
    min_x: number
    max_x: number
    min_y: number
    max_y: number
  }
  size_bytes: number
  sha256: string
  storage_path: string
  error: string | null
}

export interface GraphArtifactNode {
  id: string
  type: string
  label: string
  entity_collection: string
  entity_id: string
  degree: number
  x2d: number
  y2d: number
  cluster_id: string | null
  props: Record<string, unknown>
}

export interface GraphArtifactEdge {
  id: string
  type: string
  source: string
  target: string
  weight: number
  props: Record<string, unknown>
}

export interface GraphArtifact {
  format: 'advandeb-graph-artifact'
  format_version: number
  schema_id: string
  schema_name: string
  build_id: string
  built_at: string
  source_revision: string
  layout_name: string
  stats: {
    node_count: number
    edge_count: number
    density: number
    bounds_2d: {
      min_x: number
      max_x: number
      min_y: number
      max_y: number
    }
  }
  type_counts: {
    node_types: Record<string, number>
    edge_types: Record<string, number>
  }
  nodes: GraphArtifactNode[]
  edges: GraphArtifactEdge[]
}

export interface GraphRenderNodeSummary {
  id: string
  type: string
  label: string
  degree: number
  entity_collection: string
  entity_id: string
  props: Record<string, unknown>
  /** Count of incident `supports` edges (sf_support graph). */
  supports: number
  /** Count of incident `opposes` edges (sf_support graph). */
  opposes: number
}

export interface GraphRenderBundle {
  schemaId: string
  schemaName: string
  buildId: string
  nodeCount: number
  edgeCount: number
  /**
   * True when `pointPositions` carries the layout the backend computed for this
   * schema (rescaled into cosmos space). False means the artifact had no usable
   * layout and the positions are a placeholder spiral for the simulation to
   * untangle.
   */
  hasLayout: boolean
  pointPositions: Float32Array
  pointColors: Float32Array
  pointSizes: Float32Array
  linkIndices: Float32Array
  linkColors: Float32Array
  linkWidths: Float32Array
  nodeIds: string[]
  nodeTypes: string[]
  edgeTypes: string[]
  hoverLabels: string[]
  nodeSummaries: GraphRenderNodeSummary[]
  typeCounts: {
    node_types: Record<string, number>
    edge_types: Record<string, number>
  }
  stats: {
    node_count: number
    edge_count: number
    density: number
  }
  bounds2d: {
    minX: number
    maxX: number
    minY: number
    maxY: number
  }
}

export type GraphArtifactWorkerRequest = {
  type: 'build-render-bundle'
  artifact: GraphArtifact
}

export type GraphArtifactWorkerResponse =
  | {
      type: 'ready'
      bundle: GraphRenderBundle
    }
  | {
      type: 'error'
      error: string
    }
