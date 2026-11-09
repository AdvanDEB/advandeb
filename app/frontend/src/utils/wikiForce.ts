/**
 * A force simulation for the wiki's knowledge graph, in two or three dimensions.
 *
 * d3-force does this in 2D. The 3D view needs one engine whose settings mean
 * the same in both views, though. The graph is small (a few hundred notes), so
 * exact pairwise forces cost less than a Barnes–Hut tree and need no new
 * dependency. The integration follows d3-force: forces add to velocities, the
 * velocities decay, a cooling `alpha` scales everything, and link forces are
 * biased by node degree so that hubs do not get dragged around by their leaves.
 */

export interface ForceParams {
  /** Many-body strength: how hard every pair of notes pushes apart. */
  repulsion: number
  /** Rest length of a link. */
  linkDistance: number
  /** Multiplier on d3's default link strength, 1 / min(degree of the two ends). */
  linkStrength: number
  /** Pull towards the centre. */
  gravity: number
  /** Pull towards an anchor shared by every note of the same section. */
  cluster: number
  /** Extra space kept between node discs; 0 turns collision off. */
  spacing: number
}

export const DEFAULT_FORCES: Readonly<ForceParams> = Object.freeze({
  repulsion: 220,
  linkDistance: 55,
  linkStrength: 1,
  gravity: 0.06,
  cluster: 0,
  spacing: 3,
})

/** Slider ranges for the settings panel. */
export const FORCE_RANGES: Record<keyof ForceParams, { min: number; max: number; step: number }> = {
  repulsion: { min: 0, max: 1000, step: 10 },
  linkDistance: { min: 10, max: 250, step: 5 },
  linkStrength: { min: 0, max: 3, step: 0.05 },
  gravity: { min: 0, max: 0.4, step: 0.01 },
  cluster: { min: 0, max: 0.5, step: 0.01 },
  spacing: { min: 0, max: 30, step: 1 },
}

export type Dims = 2 | 3
type Vec3 = [number, number, number]

export interface SimNode {
  id: string
  group: string
  radius: number
  x: number
  y: number
  z: number
  vx: number
  vy: number
  vz: number
  /** A fixed position (while dragged); null when free. */
  fx: number | null
  fy: number | null
  fz: number | null
}

interface SimLink {
  s: SimNode
  t: SimNode
  bias: number
  strength: number
}

export interface NodeInput {
  id: string
  group: string
  radius: number
}

/** Deterministic pseudo-random numbers (mulberry32), so a layout is repeatable. */
function rng(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const GOLDEN = Math.PI * (3 - Math.sqrt(5))

export class ForceSim {
  readonly nodes: SimNode[]
  readonly byId: Map<string, SimNode>
  private links: SimLink[]
  private anchors = new Map<string, Vec3>()
  private random: () => number
  dims: Dims
  params: ForceParams
  alpha = 1
  alphaMin = 0.002
  alphaTarget = 0
  readonly alphaDecay = 1 - Math.pow(0.001, 1 / 300)
  readonly velocityDecay = 0.6 // what d3 keeps per tick (it calls it 1 - 0.4)

  constructor(
    nodes: NodeInput[],
    edges: [string, string][],
    params: ForceParams,
    dims: Dims,
    /** Positions to start from (by id), e.g. the layout before a filter changed. */
    start: Map<string, Vec3> = new Map(),
    seed = 1,
  ) {
    this.random = rng(seed)
    this.dims = dims
    this.params = { ...params }
    this.nodes = nodes.map((n, i) => {
      const p = start.get(n.id)
      // d3's phyllotaxis start, plus a random depth in 3D.
      const r = 10 * Math.sqrt(0.5 + i)
      const a = i * GOLDEN
      return {
        id: n.id, group: n.group, radius: n.radius,
        x: p ? p[0] : r * Math.cos(a),
        y: p ? p[1] : r * Math.sin(a),
        z: dims === 3 ? (p && p[2] !== 0 ? p[2] : (this.random() - 0.5) * r) : 0,
        vx: 0, vy: 0, vz: 0, fx: null, fy: null, fz: null,
      }
    })
    this.byId = new Map(this.nodes.map(n => [n.id, n]))
    const degree = new Map<string, number>()
    const pairs = edges.filter(([a, b]) => a !== b && this.byId.has(a) && this.byId.has(b))
    for (const [a, b] of pairs) {
      degree.set(a, (degree.get(a) ?? 0) + 1)
      degree.set(b, (degree.get(b) ?? 0) + 1)
    }
    this.links = pairs.map(([a, b]) => {
      const da = degree.get(a)!
      const db = degree.get(b)!
      return { s: this.byId.get(a)!, t: this.byId.get(b)!, bias: da / (da + db), strength: 1 / Math.min(da, db) }
    })
    this.placeAnchors()
  }

  /** Each section gets a point on a circle (2D) or a sphere (3D) to gather around. */
  private placeAnchors() {
    const groups = [...new Set(this.nodes.map(n => n.group))].sort()
    const R = this.params.linkDistance * (2 + Math.sqrt(this.nodes.length) / 2)
    this.anchors.clear()
    groups.forEach((g, i) => {
      if (this.dims === 2) {
        const a = (i / groups.length) * Math.PI * 2
        this.anchors.set(g, [R * Math.cos(a), R * Math.sin(a), 0])
      } else {
        // Fibonacci sphere: evenly spread directions.
        const y = groups.length === 1 ? 0 : 1 - (2 * i) / (groups.length - 1)
        const r = Math.sqrt(1 - y * y)
        const a = i * GOLDEN
        this.anchors.set(g, [R * r * Math.cos(a), R * y, R * r * Math.sin(a)])
      }
    })
  }

  setParams(p: Partial<ForceParams>) {
    const spread = p.linkDistance !== undefined && p.linkDistance !== this.params.linkDistance
    Object.assign(this.params, p)
    if (spread) this.placeAnchors()
    this.reheat(0.5)
  }

  setDims(d: Dims) {
    if (d === this.dims) return
    this.dims = d
    for (const n of this.nodes) {
      if (d === 3) n.z = (this.random() - 0.5) * 2 * Math.max(40, Math.hypot(n.x, n.y) * 0.6)
      else { n.z = 0; n.vz = 0 }
    }
    this.placeAnchors()
    this.reheat(1)
  }

  reheat(alpha = 1) {
    this.alpha = Math.max(this.alpha, alpha)
  }

  get running(): boolean {
    return this.alpha >= this.alphaMin || this.alphaTarget > 0
  }

  tick() {
    const { repulsion, linkDistance, linkStrength, gravity, cluster, spacing } = this.params
    const a = this.alpha
    const ns = this.nodes
    const N = ns.length
    const flat = this.dims === 2

    // Many-body repulsion (and collision, in the same pass over the pairs).
    for (let i = 0; i < N; i++) {
      const p = ns[i]
      for (let j = i + 1; j < N; j++) {
        const q = ns[j]
        let dx = q.x - p.x
        let dy = q.y - p.y
        let dz = flat ? 0 : q.z - p.z
        let l2 = dx * dx + dy * dy + dz * dz
        if (l2 === 0) { // coincident: nudge apart, as d3's jiggle does
          dx = (this.random() - 0.5) * 1e-3
          dy = (this.random() - 0.5) * 1e-3
          dz = flat ? 0 : (this.random() - 0.5) * 1e-3
          l2 = dx * dx + dy * dy + dz * dz
        }
        if (repulsion > 0) {
          const w = (repulsion * a) / Math.max(l2, 1)
          p.vx -= dx * w; p.vy -= dy * w; p.vz -= dz * w
          q.vx += dx * w; q.vy += dy * w; q.vz += dz * w
        }
        if (spacing > 0) {
          const r = p.radius + q.radius + spacing
          if (l2 < r * r) {
            const l = Math.sqrt(l2)
            const k = ((r - l) / l) * 0.35
            p.vx -= dx * k; p.vy -= dy * k; p.vz -= dz * k
            q.vx += dx * k; q.vy += dy * k; q.vz += dz * k
          }
        }
      }
    }

    // Links pull towards their rest length.
    if (linkStrength > 0) {
      for (const { s, t, bias, strength } of this.links) {
        let dx = t.x + t.vx - s.x - s.vx
        let dy = t.y + t.vy - s.y - s.vy
        let dz = flat ? 0 : t.z + t.vz - s.z - s.vz
        const l = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1e-6
        const k = ((l - linkDistance) / l) * a * strength * linkStrength
        dx *= k; dy *= k; dz *= k
        t.vx -= dx * bias; t.vy -= dy * bias; t.vz -= dz * bias
        s.vx += dx * (1 - bias); s.vy += dy * (1 - bias); s.vz += dz * (1 - bias)
      }
    }

    // Centre and section anchors.
    for (const n of ns) {
      if (gravity > 0) {
        n.vx -= n.x * gravity * a; n.vy -= n.y * gravity * a; n.vz -= n.z * gravity * a
      }
      if (cluster > 0) {
        const c = this.anchors.get(n.group)
        if (c) {
          n.vx += (c[0] - n.x) * cluster * a
          n.vy += (c[1] - n.y) * cluster * a
          n.vz += (c[2] - n.z) * cluster * a
        }
      }
    }

    for (const n of ns) {
      if (n.fx !== null) { n.x = n.fx; n.vx = 0 } else { n.vx *= this.velocityDecay; n.x += n.vx }
      if (n.fy !== null) { n.y = n.fy; n.vy = 0 } else { n.vy *= this.velocityDecay; n.y += n.vy }
      if (flat) { n.z = 0; n.vz = 0 } else if (n.fz !== null) { n.z = n.fz; n.vz = 0 } else { n.vz *= this.velocityDecay; n.z += n.vz }
    }

    this.alpha += (this.alphaTarget - this.alpha) * this.alphaDecay
  }

  /** Positions by id, to carry a layout over into a rebuilt simulation. */
  positions(): Map<string, Vec3> {
    return new Map(this.nodes.map(n => [n.id, [n.x, n.y, n.z] as Vec3]))
  }

  /** Radius of the smallest origin-centred sphere holding every node. */
  extent(): number {
    let r = 0
    for (const n of this.nodes) r = Math.max(r, Math.hypot(n.x, n.y, n.z) + n.radius)
    return r || 1
  }
}
