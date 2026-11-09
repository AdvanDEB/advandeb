// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { DEFAULT_FORCES, ForceSim, type ForceParams } from '@/utils/wikiForce'

/**
 * The wiki graph's force engine (utils/wikiForce.ts). What the view relies on:
 * links pull related notes together, the section force gathers sections, the
 * 2D view stays flat, a dragged node stays where it is held, the layout
 * settles, and the same input gives the same picture.
 */

// Two groups of six notes, each a ring with chords; one link between the groups.
const nodes = Array.from({ length: 12 }, (_, i) => ({ id: `n${i}`, group: i < 6 ? 'a' : 'b', radius: 4 }))
const edges: [string, string][] = []
for (const off of [0, 6]) {
  for (let i = 0; i < 6; i++) {
    edges.push([`n${off + i}`, `n${off + ((i + 1) % 6)}`])
    edges.push([`n${off + i}`, `n${off + ((i + 2) % 6)}`])
  }
}
edges.push(['n0', 'n6'])

function settle(sim: ForceSim, max = 2000) {
  let ticks = 0
  while (sim.running && ticks < max) { sim.tick(); ticks++ }
  return ticks
}

const dist = (sim: ForceSim, a: string, b: string) => {
  const p = sim.byId.get(a)!
  const q = sim.byId.get(b)!
  return Math.hypot(p.x - q.x, p.y - q.y, p.z - q.z)
}

function meanDistance(sim: ForceSim, pairs: [string, string][]) {
  return pairs.reduce((s, [a, b]) => s + dist(sim, a, b), 0) / pairs.length
}

const allPairs: [string, string][] = []
for (let i = 0; i < 12; i++) for (let j = i + 1; j < 12; j++) allPairs.push([`n${i}`, `n${j}`])
const sameGroup = allPairs.filter(([a, b]) => (Number(a.slice(1)) < 6) === (Number(b.slice(1)) < 6))
const otherGroup = allPairs.filter(p => !sameGroup.includes(p))

describe('ForceSim', () => {
  it('settles, and linked notes end up closer than notes in general', () => {
    const sim = new ForceSim(nodes, edges, { ...DEFAULT_FORCES }, 2)
    const ticks = settle(sim)
    expect(sim.running).toBe(false)
    expect(ticks).toBeLessThan(1000)
    for (const n of sim.nodes) expect(Number.isFinite(n.x) && Number.isFinite(n.y)).toBe(true)
    expect(meanDistance(sim, edges)).toBeLessThan(0.75 * meanDistance(sim, allPairs))
  })

  it('keeps the 2D layout flat and spreads the 3D one in depth', () => {
    const flat = new ForceSim(nodes, edges, { ...DEFAULT_FORCES }, 2)
    settle(flat)
    expect(flat.nodes.every(n => n.z === 0)).toBe(true)

    const deep = new ForceSim(nodes, edges, { ...DEFAULT_FORCES }, 3)
    settle(deep)
    const zs = deep.nodes.map(n => n.z)
    expect(Math.max(...zs) - Math.min(...zs)).toBeGreaterThan(10)

    deep.setDims(2)
    expect(deep.nodes.every(n => n.z === 0)).toBe(true)
    expect(deep.running).toBe(true)
  })

  it('gathers sections when asked to', () => {
    const loose: ForceParams = { ...DEFAULT_FORCES, cluster: 0, linkStrength: 0 }
    const a = new ForceSim(nodes, edges, loose, 2)
    settle(a)
    const b = new ForceSim(nodes, edges, { ...loose, cluster: 0.3 }, 2)
    settle(b)
    const ratio = (s: ForceSim) => meanDistance(s, sameGroup) / meanDistance(s, otherGroup)
    expect(ratio(b)).toBeLessThan(ratio(a))
    expect(ratio(b)).toBeLessThan(0.7)
  })

  it('holds a dragged note where it is held', () => {
    const sim = new ForceSim(nodes, edges, { ...DEFAULT_FORCES }, 2)
    const n = sim.byId.get('n3')!
    n.fx = 500
    n.fy = -200
    for (let i = 0; i < 50; i++) sim.tick()
    expect([n.x, n.y]).toEqual([500, -200])
  })

  it('gives the same layout for the same input', () => {
    const one = new ForceSim(nodes, edges, { ...DEFAULT_FORCES }, 3)
    const two = new ForceSim(nodes, edges, { ...DEFAULT_FORCES }, 3)
    for (let i = 0; i < 100; i++) { one.tick(); two.tick() }
    expect([...one.positions()]).toEqual([...two.positions()])
  })

  it('starts from given positions, so a filter change does not scramble the picture', () => {
    const first = new ForceSim(nodes, edges, { ...DEFAULT_FORCES }, 2)
    settle(first)
    const start = first.positions()
    const subset = nodes.slice(0, 6)
    const next = new ForceSim(subset, edges, { ...DEFAULT_FORCES }, 2, start)
    expect(next.byId.get('n2')!.x).toBe(start.get('n2')![0])
    expect(next.nodes).toHaveLength(6)
  })

  it('ignores links to notes it does not have', () => {
    const sim = new ForceSim(nodes.slice(0, 3), [['n0', 'n1'], ['n1', 'n9'], ['n2', 'n2']], { ...DEFAULT_FORCES }, 2)
    expect(() => settle(sim)).not.toThrow()
  })
})
