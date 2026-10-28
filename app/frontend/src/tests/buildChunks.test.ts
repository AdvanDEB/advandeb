// @vitest-environment node
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, beforeAll } from 'vitest'
import { build, type Rollup } from 'vite'
import { vendorChunk } from '../../vite.config'

/**
 * What every visitor downloads. The landing and login pages need the app shell
 * (entry + vue-vendor); the feature libraries belong to the routes that use
 * them: plotly/KaTeX/JSZip to /models, cosmos to the graph, markdown to chat.
 *
 * Before: luma.gl (inside @cosmos.gl/graph) has a dynamic import, so Rollup's
 * manualChunks swept Vite's preload helper into cosmos-vendor. The entry needs
 * that helper for every lazy route, so index.html modulepreloaded cosmos-vendor
 * and, through its imports, tdeb-vendor and markdown-vendor: 1.35 MB raw /
 * 368 kB gzip on every page instead of ~205 kB / 73 kB.
 *
 * This runs the real production build (unminified, nothing written), ~10 s.
 */

const FEATURE_VENDORS = ['tdeb-vendor', 'plotly-vendor', 'cosmos-vendor', 'markdown-vendor', 'd3-vendor']
const root = fileURLToPath(new URL('../..', import.meta.url))

let chunks: Rollup.OutputChunk[]
let indexHtml: string

beforeAll(async () => {
  const out = (await build({
    root,
    configFile: path.join(root, 'vite.config.ts'),
    logLevel: 'silent',
    build: {
      write: false,
      minify: false,
      outDir: path.join(os.tmpdir(), 'advandeb-build-chunks-test'),
    },
  })) as Rollup.RollupOutput
  chunks = out.output.filter((o): o is Rollup.OutputChunk => o.type === 'chunk')
  const html = out.output.find(o => o.fileName === 'index.html') as Rollup.OutputAsset
  indexHtml = String(html.source)
}, 120_000)

/** Chunk names of everything a chunk loads statically, itself included. */
function staticClosure(start: Rollup.OutputChunk): string[] {
  const byFile = new Map(chunks.map(c => [c.fileName, c]))
  const seen = new Set<Rollup.OutputChunk>()
  const todo = [start]
  while (todo.length) {
    const c = todo.pop()!
    if (seen.has(c)) continue
    seen.add(c)
    for (const f of c.imports) todo.push(byFile.get(f)!)
  }
  return [...seen].map(c => c.name)
}

function chunkFor(source: string): Rollup.OutputChunk {
  const c = chunks.find(c => (source === 'entry' ? c.isEntry : c.facadeModuleId?.endsWith(source)))
  if (!c) throw new Error(`no chunk for ${source}`)
  return c
}

describe('production build: what the landing page loads', () => {
  it('index.html preloads no feature vendor chunk', () => {
    const urls = [...indexHtml.matchAll(/<(?:script|link)\b[^>]*?(?:src|href)="([^"]+\.js)"/g)].map(m => m[1])
    expect(urls.length).toBeGreaterThan(0)
    for (const vendor of FEATURE_VENDORS) {
      expect(urls.filter(u => u.includes(`/${vendor}-`)), `index.html loads ${vendor}`).toEqual([])
    }
  })

  it.each(['entry', 'src/views/HomeView.vue', 'src/views/LoginView.vue'])(
    '%s loads no feature vendor chunk', source => {
      const loaded = staticClosure(chunkFor(source))
      expect(loaded.filter(name => FEATURE_VENDORS.includes(name))).toEqual([])
    })

  it('the graph view does not load the tDEB libraries', () => {
    const loaded = staticClosure(chunkFor('src/views/KnowledgeBuilderView.vue'))
    expect(loaded).toContain('cosmos-vendor')
    expect(loaded).not.toContain('tdeb-vendor')
    expect(loaded).not.toContain('plotly-vendor')
  })
})

describe('vendorChunk', () => {
  it('pins bundler helpers to the chunk every page loads', () => {
    expect(vendorChunk('\0vite/preload-helper.js')).toBe('vue-vendor')
    expect(vendorChunk('\0commonjsHelpers.js')).toBe('vue-vendor')
  })

  it('assigns a nested dependency to the package that owns it', () => {
    expect(vendorChunk('/x/node_modules/plotly.js/node_modules/d3-format/src/index.js')).toBe('plotly-vendor')
    expect(vendorChunk('/x/node_modules/d3-format/src/index.js')).toBe('d3-vendor')
    expect(vendorChunk('/x/node_modules/@cosmos.gl/graph/dist/index.js')).toBe('cosmos-vendor')
  })

  it('leaves stylesheets and app code to Rollup', () => {
    expect(vendorChunk('/x/node_modules/highlight.js/styles/github.css')).toBeUndefined()
    expect(vendorChunk('/x/src/main.ts')).toBeUndefined()
  })
})
