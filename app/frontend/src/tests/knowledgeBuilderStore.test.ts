import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { isProxy, isReactive } from 'vue'
import { storeToRefs } from 'pinia'
import { useKnowledgeBuilderStore } from '@/stores/knowledgeBuilder'
import { fetchArtifactStatus, fetchGraphArtifact, fetchSchemas } from '@/utils/kbApi'
import type { GraphSchema } from '@/utils/kbApi'

vi.mock('@/utils/kbApi', () => ({
  fetchSchemas: vi.fn(),
  fetchArtifactStatus: vi.fn(),
  fetchGraphArtifact: vi.fn(),
}))

// Stands in for the Vite ?worker import: answers every request with a bundle
// built from the artifact it was sent, after a tick, like the real worker.
// Hoisted because vi.mock factories run before the module body.
const { FakeWorker, workers } = vi.hoisted(() => {
  function makeBundle(schemaId: string, nodeCount: number) {
    return {
      schemaId,
      schemaName: schemaId,
      nodeCount,
      edgeCount: 1,
      hasLayout: false,
      stats: { density: 0.5 },
      typeCounts: { node_types: { fact: nodeCount }, edge_types: {} },
      nodeIds: Array.from({ length: nodeCount }, (_, i) => `n${i}`),
      positions: new Float32Array(nodeCount * 2),
      nodeSummaries: Array.from({ length: nodeCount }, (_, i) => ({ id: `n${i}`, type: 'fact', label: `N${i}`, props: {} })),
    }
  }

  const workers: FakeWorker[] = []
  class FakeWorker {
    onmessage: ((ev: { data: unknown }) => void) | null = null
    onerror: ((ev: { message?: string }) => void) | null = null
    terminated = false
    constructor() { workers.push(this) }
    postMessage(msg: { artifact: { schema_id: string; nodes: unknown[] } }) {
      setTimeout(() => {
        if (this.terminated) return
        this.onmessage?.({ data: { type: 'ready', bundle: makeBundle(msg.artifact.schema_id, msg.artifact.nodes.length) } })
      }, 0)
    }
    terminate() { this.terminated = true }
  }
  return { FakeWorker, workers }
})
vi.mock('@/workers/graphArtifactWorker?worker', () => ({ default: FakeWorker }))

function schema(id: string, artifactStatus?: string): GraphSchema {
  return {
    _id: id,
    name: `Schema ${id}`,
    ...(artifactStatus
      ? { artifact: { status: artifactStatus, node_count: 10, edge_count: 4, density: 0.1 } }
      : {}),
  } as unknown as GraphSchema
}

function artifact(schemaId: string, nodes = 3) {
  return { schema_id: schemaId, nodes: Array.from({ length: nodes }, () => ({})), edges: [] }
}

/** Let the schema watcher run and the load (fetches + worker tick) finish. */
async function settle() {
  await flushPromises()
  await new Promise(r => setTimeout(r, 0))
  await flushPromises()
}

beforeEach(() => {
  workers.length = 0
  vi.mocked(fetchSchemas).mockReset()
  vi.mocked(fetchArtifactStatus).mockReset().mockResolvedValue({ status: 'ready', build_id: 'b1' } as never)
  vi.mocked(fetchGraphArtifact).mockReset().mockImplementation(async (id: string) => artifact(id) as never)
})

describe('knowledgeBuilder store', () => {
  it('starts on the graph tab with nothing loaded', () => {
    const kb = useKnowledgeBuilderStore()
    expect(kb.activeTab).toBe('graph')
    expect(kb.error).toBe('')
    expect(kb.graphBundle).toBeNull()
    expect(kb.selectedNode).toBeNull()
  })

  it('setError takes an Error or anything else', () => {
    const kb = useKnowledgeBuilderStore()
    kb.setError(new Error('boom'))
    expect(kb.error).toBe('boom')
    kb.setError('plain')
    expect(kb.error).toBe('plain')
  })

  it('loadSchemas seeds stats from ready/stale artifacts, selects the first schema and loads its graph', async () => {
    vi.mocked(fetchSchemas).mockResolvedValue([schema('a', 'ready'), schema('b', 'stale'), schema('c', 'missing'), schema('d')])
    const kb = useKnowledgeBuilderStore()

    await kb.loadSchemas()
    expect(kb.schemas.map(s => s._id)).toEqual(['a', 'b', 'c', 'd'])
    expect(Object.keys(kb.statsBySchema).sort()).toEqual(['a', 'b'])
    expect(kb.selectedSchema?._id).toBe('a')

    await settle()
    expect(fetchGraphArtifact).toHaveBeenCalledWith('a', 'b1')
    expect(kb.graphBundle?.schemaId).toBe('a')
    expect(kb.graphBundle?.nodeCount).toBe(3)
    expect(kb.selectedStats?.node_count).toBe(3)
    expect(kb.statsBySchema.a.node_count).toBe(3)
    expect(kb.graphLoading).toBe(false)
    expect(kb.graphLoad.active).toBe(false)
  })

  it('keeps the graph bundle shallow: the worker output is never wrapped in proxies', async () => {
    vi.mocked(fetchSchemas).mockResolvedValue([schema('a', 'ready')])
    const kb = useKnowledgeBuilderStore()
    await kb.loadSchemas()
    await settle()

    const { graphBundle } = storeToRefs(kb)
    const bundle = graphBundle.value!
    expect(bundle).not.toBeNull()
    expect(isProxy(bundle)).toBe(false)
    expect(isReactive(bundle.nodeSummaries)).toBe(false)
    expect(isProxy(bundle.nodeSummaries[0])).toBe(false)
  })

  it('a storeToRefs ref writes through (as the shell\'s Reset DB does)', async () => {
    vi.mocked(fetchSchemas).mockResolvedValue([schema('a', 'ready')])
    const kb = useKnowledgeBuilderStore()
    await kb.loadSchemas()
    await settle()

    const { graphBundle, selectedNode } = storeToRefs(kb)
    selectedNode.value = { _id: 'n1' } as never
    graphBundle.value = null
    selectedNode.value = null
    expect(kb.graphBundle).toBeNull()
    expect(kb.selectedNode).toBeNull()
  })

  it('switching schema clears the selected node and loads the new graph', async () => {
    vi.mocked(fetchSchemas).mockResolvedValue([schema('a', 'ready'), schema('b', 'ready')])
    const kb = useKnowledgeBuilderStore()
    await kb.loadSchemas()
    await settle()

    kb.selectedNode = { _id: 'n1' } as never
    kb.selectedSchema = kb.schemas[1]
    await settle()
    expect(kb.selectedNode).toBeNull()
    expect(kb.graphBundle?.schemaId).toBe('b')
  })

  it('reports a failed schema list on the error chip', async () => {
    vi.mocked(fetchSchemas).mockRejectedValue(new Error('offline'))
    const kb = useKnowledgeBuilderStore()
    await kb.loadSchemas()
    expect(kb.error).toBe('offline')
    expect(kb.selectedSchema).toBeNull()
  })

  it('reset() returns to a first visit and orphans an in-flight load', async () => {
    vi.mocked(fetchSchemas).mockResolvedValue([schema('a', 'ready')])
    let release!: () => void
    vi.mocked(fetchGraphArtifact).mockImplementation(
      (id: string) => new Promise(resolve => { release = () => resolve(artifact(id) as never) }),
    )
    const kb = useKnowledgeBuilderStore()
    kb.activeTab = 'kg'
    kb.error = 'old error'

    await kb.loadSchemas()
    await flushPromises()
    expect(kb.graphLoading).toBe(true)

    kb.reset()
    expect(kb.activeTab).toBe('graph')
    expect(kb.error).toBe('')
    expect(kb.schemas).toEqual([])
    expect(kb.selectedSchema).toBeNull()
    expect(kb.statsBySchema).toEqual({})
    expect(kb.graphLoading).toBe(false)

    // The load that was in flight finishes after the reset: it must not
    // repopulate the store.
    release()
    await settle()
    expect(kb.graphBundle).toBeNull()
    expect(kb.selectedStats).toBeNull()
    expect(kb.graphLoading).toBe(false)
    expect(kb.statsBySchema).toEqual({})
  })

  it('terminateWorker() stops a worker mid-build so its bundle is dropped', async () => {
    vi.mocked(fetchSchemas).mockResolvedValue([schema('a', 'ready')])
    const kb = useKnowledgeBuilderStore()
    await kb.loadSchemas()
    await flushPromises()
    await flushPromises()
    expect(workers).toHaveLength(1)

    kb.terminateWorker()
    expect(workers[0].terminated).toBe(true)
    await settle()
    expect(kb.graphBundle).toBeNull()
  })
})
