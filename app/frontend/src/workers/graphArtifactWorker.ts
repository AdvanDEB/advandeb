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
  const nodeTypes = new Array<string>(nodeCount)
  const hoverLabels = new Array<string>(nodeCount)
  const nodeSummaries = new Array(nodeCount)
  const idToIndex = new Map<string, number>()
  // Per-node tallies of supporting/opposing edges (sf_support graph), indexed
  // to match artifact.nodes. Each edge increments both endpoints.
  const supportsCounts = new Int32Array(nodeCount)
  const opposesCounts = new Int32Array(nodeCount)

  for (let i = 0; i < nodeCount; i++) {
    const node: GraphArtifactNode = artifact.nodes[i]
    idToIndex.set(node.id, i)
    nodeIds[i] = node.id
    nodeTypes[i] = node.type
    hoverLabels[i] = node.label
    nodeSummaries[i] = {
      id: node.id,
      type: node.type,
      label: node.label,
      degree: node.degree,
      entity_collection: node.entity_collection,
      entity_id: node.entity_id,
      props: node.props,
      supports: 0,
      opposes: 0,
    }

    // Spread nodes in a sunflower spiral within a small coordinate range so
    // cosmos can rescale them into its spaceSize. Using radius ≤ 100 ensures
    // the bounding box stays well under spaceSize (4096) for any realistic graph.
    const angle = i * 2.399963  // golden angle
    const radius = Math.sqrt(i + 1)  // grows slowly, stays bounded
    pointPositions[i * 2]     = Math.cos(angle) * radius
    pointPositions[i * 2 + 1] = Math.sin(angle) * radius
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
  const edgeTypes = new Array<string>(validEdges.length)

  for (let i = 0; i < validEdges.length; i++) {
    const edge = validEdges[i]
    edgeTypes[i] = edge.type
    const sourceIdx = idToIndex.get(edge.source) as number
    const targetIdx = idToIndex.get(edge.target) as number
    linkIndices[i * 2] = sourceIdx
    linkIndices[i * 2 + 1] = targetIdx
    if (edge.type === 'supports') {
      supportsCounts[sourceIdx]++
      supportsCounts[targetIdx]++
    } else if (edge.type === 'opposes') {
      opposesCounts[sourceIdx]++
      opposesCounts[targetIdx]++
    }
    const [r, g, b, a] = edgeColor(edge)
    linkColors[i * 4] = r
    linkColors[i * 4 + 1] = g
    linkColors[i * 4 + 2] = b
    linkColors[i * 4 + 3] = a
    linkWidths[i] = Math.max(1.5, (edge.weight ?? 1) * 4.5)
  }

  for (let i = 0; i < nodeCount; i++) {
    nodeSummaries[i].supports = supportsCounts[i]
    nodeSummaries[i].opposes = opposesCounts[i]
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
    nodeTypes,
    edgeTypes,
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
