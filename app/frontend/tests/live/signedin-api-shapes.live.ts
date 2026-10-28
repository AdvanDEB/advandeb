// What the signed-in pages receive and send, by shape only: for each JSON
// response under /api, the field names (never values), flags for fields that
// look like secrets or credentials, and the query-parameter names of every
// request URL. Desktop only; pages are visited, nothing is clicked.
import { test, expect } from './guard'
import { record } from './collect'

const PAGES = ['/', '/chat', '/documents', '/facts', '/settings/llm-keys', '/settings/privacy', '/elicitation', '/admin/users', '/admin/experts', '/models']

const SECRETISH = /pass(word)?|hash|secret|token|api_?key|encrypted|refresh|ticket|salt|otp|totp/i

function shape(v: unknown, depth = 0): unknown {
  if (Array.isArray(v)) return v.length ? [shape(v[0], depth + 1)] : []
  if (v && typeof v === 'object' && depth < 3) {
    return Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, shape(x, depth + 1)]))
  }
  return typeof v
}

function secretFields(v: unknown, prefix = ''): { field: string; type: string; length?: number; masked?: boolean }[] {
  const out: { field: string; type: string; length?: number; masked?: boolean }[] = []
  if (Array.isArray(v)) { if (v.length) out.push(...secretFields(v[0], prefix + '[]')); return out }
  if (v && typeof v === 'object') {
    for (const [k, x] of Object.entries(v as Record<string, unknown>)) {
      if (SECRETISH.test(k) && x !== null && typeof x !== 'boolean') {
        out.push({ field: prefix + k, type: typeof x, length: typeof x === 'string' ? x.length : undefined, masked: typeof x === 'string' ? /[*•…]/.test(x) : undefined })
      }
      out.push(...secretFields(x, prefix + k + '.'))
    }
  }
  return out
}

test('api shapes on signed-in pages (names only)', async ({ page, evidence }, info) => {
  test.skip(info.project.name !== 'desktop', 'shapes do not depend on the viewport')
  test.setTimeout(150_000)
  const shapes: Record<string, unknown> = {}
  const secrets: Record<string, unknown> = {}
  const queryNames = new Set<string>()
  page.on('request', (r) => {
    const u = new URL(r.url())
    if (!u.hostname.endsWith('advandeb.com')) return
    for (const k of u.searchParams.keys()) queryNames.add(`${u.pathname.replace(/[0-9a-f]{24}|[0-9a-f-]{36}/g, ':id')}?${k}`)
  })
  page.on('response', async (r) => {
    const u = new URL(r.url())
    if (!u.pathname.startsWith('/api/') || !(r.headers()['content-type'] || '').includes('json')) return
    const key = `${r.request().method()} ${u.pathname.replace(/[0-9a-f]{24}|[0-9a-f-]{36}/g, ':id')}`
    try {
      const body = await r.json()
      shapes[key] = shape(body)
      const s = secretFields(body)
      if (s.length) secrets[key] = s
    } catch { /* not JSON or body gone */ }
  })

  for (const p of PAGES) {
    await page.goto(p, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
    await page.waitForTimeout(800)
  }
  const storage = await page.evaluate(() => Object.keys(localStorage).concat(Object.keys(sessionStorage).map((k) => 'session:' + k)))

  record(info, 'api-shapes', { shapes, secrets, queryNames: [...queryNames], storageKeys: storage, blocked: evidence.blocked, failed: evidence.failed })
  expect(evidence.blocked).toEqual([])
})
