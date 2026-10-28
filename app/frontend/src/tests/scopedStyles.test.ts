// @vitest-environment node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { parse } from '@vue/compiler-sfc'

/**
 * Global CSS cannot live in a <style scoped> block. Scoping rewrites every
 * selector, so `:root { --el-accent: … }` becomes `[data-v-…]:root`, which
 * matches no element, and the custom properties stay unset. That is how the
 * enrolment page shipped unstyled with an invisible submit button: six SFCs
 * @import-ed styles/elicitation-tokens.css from their scoped block, so no
 * --el-* token ever resolved (AppLayout's sidebar spacing and touch sizes
 * included). The token files are loaded once, globally, from main.ts.
 *
 * src/tests/buildChunks.test.ts checks the same thing on the built CSS.
 */

const src = fileURLToPath(new URL('..', import.meta.url))

function vueFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return vueFiles(p)
    return e.name.endsWith('.vue') ? [p] : []
  })
}

const scopedBlocks = vueFiles(src).flatMap(file => {
  const { descriptor } = parse(fs.readFileSync(file, 'utf8'), { filename: file })
  return descriptor.styles
    .filter(s => s.scoped)
    .map(s => ({ file: path.relative(src, file), css: s.content }))
})

describe('<style scoped> blocks', () => {
  it('finds the SFCs', () => {
    expect(scopedBlocks.length).toBeGreaterThan(20)
  })

  it('declare nothing on :root (it would compile to [data-v-…]:root)', () => {
    const offenders = scopedBlocks.filter(b => /:root\b/.test(b.css)).map(b => b.file)
    expect(offenders).toEqual([])
  })

  it('@import no stylesheet (it would be scoped too; load shared CSS from main.ts)', () => {
    const offenders = scopedBlocks.filter(b => /@import\b/.test(b.css)).map(b => b.file)
    expect(offenders).toEqual([])
  })
})

describe('main.ts', () => {
  it('loads the design-token files globally', () => {
    const main = fs.readFileSync(path.join(src, 'main.ts'), 'utf8')
    expect(main).toMatch(/^import '@\/styles\/tokens\.css'$/m)
    expect(main).toMatch(/^import '@\/styles\/elicitation-tokens\.css'$/m)
  })
})
