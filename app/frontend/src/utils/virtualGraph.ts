export interface VNode {
  id: string
  label: string
  nodeType: string
  properties: Record<string, any>
  entityCollection?: string
  cluster_id?: string | number | null
  __degree?: number
  __val?: number
  [key: string]: any
}

export interface VEdge {
  source: string
  target: string
  edgeType: string
}

export class VirtualGraph {
  nodes = new Map<string, VNode>()
  edges = new Map<string, VEdge>()  // key: `${src}→${tgt}→${type}`
  expanded = new Set<string>()      // node IDs whose neighbors are fully loaded

  addNodes(nodes: VNode[]): void {
    for (const n of nodes) {
      if (!this.nodes.has(n.id)) {
        this.nodes.set(n.id, n)
      }
    }
    // Recompute degrees after adding new nodes
    this._recomputeDegrees()
  }

  addEdges(edges: VEdge[]): void {
    for (const e of edges) {
      const key = `${e.source}\u2192${e.target}\u2192${e.edgeType}`
      if (!this.edges.has(key)) {
        this.edges.set(key, e)
      }
    }
    this._recomputeDegrees()
  }

  markExpanded(nodeId: string): void {
    this.expanded.add(nodeId)
  }

  isExpanded(nodeId: string): boolean {
    return this.expanded.has(nodeId)
  }

  /**
   * Boundary nodes: present in the graph but NOT yet expanded.
   * These may have more neighbors on the server that haven't been loaded.
   */
  boundaryNodeIds(): string[] {
    const result: string[] = []
    for (const id of this.nodes.keys()) {
      if (!this.expanded.has(id)) {
        result.push(id)
      }
    }
    return result
  }

  /**
   * Returns the data object accepted by force-graph's graphData().
   */
  toGraphData(): { nodes: VNode[]; links: VEdge[] } {
    return {
      nodes: [...this.nodes.values()],
      links: [...this.edges.values()],
    }
  }

  clear(): void {
    this.nodes.clear()
    this.edges.clear()
    this.expanded.clear()
  }

  private _recomputeDegrees(): void {
    const degreeMap = new Map<string, number>()
    for (const e of this.edges.values()) {
      degreeMap.set(e.source, (degreeMap.get(e.source) || 0) + 1)
      degreeMap.set(e.target, (degreeMap.get(e.target) || 0) + 1)
    }
    for (const [id, node] of this.nodes) {
      const deg = degreeMap.get(id) || 1
      node.__degree = deg
      node.__val = Math.max(0.4, Math.log(deg + 1) * 1.6)
    }
  }
}
