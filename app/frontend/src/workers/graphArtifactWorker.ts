/// <reference lib="webworker" />

import {
  NODE_TYPE_COLORS,
  DEFAULT_NODE_COLOR,
  EDGE_TYPE_COLORS,
  DEFAULT_EDGE_COLOR,
} from '@/utils/kbColors'
import type {
  GraphArtifact,
  GraphArtifactEdge,
  GraphArtifactNode,
  GraphArtifactWorkerRequest,
  GraphArtifactWorkerResponse,
  GraphRenderBundle,
} from '@/types/graphArtifact'

function nodeSizeFromDegree(degree: number): number {
  return Math.min(20, 2 + Math.log2((degree ?? 0) + 1) * 2.5)
}

function edgeColor(edge: GraphArtifactEdge): [number, number, number, number] {
  if (edge.type === 'cites' && edge.props?.internal === false) {
    return [150 / 255, 150 / 255, 150 / 255, 0.31]
  }
  return EDGE_TYPE_COLORS[edge.type] ?? DEFAULT_EDGE_COLOR
}

function buildRenderBundle(artifact: GraphArtifact): GraphRenderBundle {
  const nodeCount = artifact.nodes.length
  const pointPositions = new Float32Array(nodeCount * 2)
  const pointColors = new Float32Array(nodeCount * 4)
  const pointSizes = new Float32Array(nodeCount)
  const nodeIds = new Array<string>(nodeCount)
  const hoverLabels = new Array<string>(nodeCount)
  const nodeSummaries = new Array(nodeCount)
  const idToIndex = new Map<string, number>()

  for (let i = 0; i < nodeCount; i++) {
    const node: GraphArtifactNode = artifact.nodes[i]
    idToIndex.set(node.id, i)
    nodeIds[i] = node.id
    hoverLabels[i] = node.label
    nodeSummaries[i] = {
      id: node.id,
      type: node.type,
      label: node.label,
      degree: node.degree,
      entity_collection: node.entity_collection,
      entity_id: node.entity_id,
      props: node.props,
    }

    pointPositions[i * 2] = node.x2d
    pointPositions[i * 2 + 1] = node.y2d
    const [r, g, b, a] = NODE_TYPE_COLORS[node.type] ?? DEFAULT_NODE_COLOR
    pointColors[i * 4] = r
    pointColors[i * 4 + 1] = g
    pointColors[i * 4 + 2] = b
    pointColors[i * 4 + 3] = a
    pointSizes[i] = nodeSizeFromDegree(node.degree)
  }

  const validEdges = artifact.edges.filter((edge) => idToIndex.has(edge.source) && idToIndex.has(edge.target))
  const linkIndices = new Float32Array(validEdges.length * 2)
  const linkColors = new Float32Array(validEdges.length * 4)
  const linkWidths = new Float32Array(validEdges.length)

  for (let i = 0; i < validEdges.length; i++) {
    const edge = validEdges[i]
    linkIndices[i * 2] = idToIndex.get(edge.source) as number
    linkIndices[i * 2 + 1] = idToIndex.get(edge.target) as number
    const [r, g, b, a] = edgeColor(edge)
    linkColors[i * 4] = r
    linkColors[i * 4 + 1] = g
    linkColors[i * 4 + 2] = b
    linkColors[i * 4 + 3] = a
    linkWidths[i] = Math.max(1.5, (edge.weight ?? 1) * 4.5)
  }

  return {
    schemaId: artifact.schema_id,
    schemaName: artifact.schema_name,
    buildId: artifact.build_id,
    nodeCount,
    edgeCount: validEdges.length,
    pointPositions,
    pointColors,
    pointSizes,
    linkIndices,
    linkColors,
    linkWidths,
    nodeIds,
    hoverLabels,
    nodeSummaries,
    typeCounts: artifact.type_counts,
    stats: artifact.stats,
    bounds2d: {
      minX: artifact.stats.bounds_2d.min_x,
      maxX: artifact.stats.bounds_2d.max_x,
      minY: artifact.stats.bounds_2d.min_y,
      maxY: artifact.stats.bounds_2d.max_y,
    },
  }
}

self.onmessage = (event: MessageEvent<GraphArtifactWorkerRequest>) => {
  try {
    if (event.data.type !== 'build-render-bundle') {
      throw new Error(`Unknown graph artifact worker request: ${String(event.data)}`)
    }
    const bundle = buildRenderBundle(event.data.artifact)
    const response: GraphArtifactWorkerResponse = { type: 'ready', bundle }
    self.postMessage(response, [
      bundle.pointPositions.buffer,
      bundle.pointColors.buffer,
      bundle.pointSizes.buffer,
      bundle.linkIndices.buffer,
      bundle.linkColors.buffer,
      bundle.linkWidths.buffer,
    ])
  } catch (error) {
    const response: GraphArtifactWorkerResponse = {
      type: 'error',
      error: error instanceof Error ? error.message : String(error),
    }
    self.postMessage(response)
  }
}
