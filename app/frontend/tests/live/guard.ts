/**
 * Fixtures for reviewing the deployed site without changing anything on it.
 *
 * - Any /api or /ws request whose method is not GET/HEAD/OPTIONS is aborted,
 *   unless it is in ALWAYS_ALLOWED (signing in and out, socket tickets) or the
 *   spec opts in with `test.use({ allowMutations: [/…/] })`. Aborted requests
 *   are recorded as `blocked` in the evidence, so an error the app shows
 *   because of the guard is not mistaken for a bug.
 * - Chat messages over the socket are counted against LIVE_CHAT_BUDGET
 *   (default 0: none). The chat backend shares one rate-limited key.
 * - Signing in happens once per run, through the API, with LIVE_EMAIL and
 *   LIVE_PASSWORD. The token pair lives in memory, is handed to each page via
 *   localStorage before the app boots, is read back after each test (the app
 *   may have rotated it), and is revoked at the end.
 * - Console errors, page errors, failed and slow requests are written per test
 *   to $LIVE_OUT/evidence/<project>/<test>.json; `shot` and `axe` write
 *   screenshots and axe-core results under $LIVE_OUT as well.
 *
 * Nothing here records a request body, an Authorization header or a password;
 * query parameters that carry credentials are redacted from recorded URLs.
 */
import { test as base, expect, type Page, type TestInfo } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import fs from 'node:fs'
import path from 'node:path'

const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'
const SLOW_MS = Number(process.env.LIVE_SLOW_MS || 2000)

/** Mutating requests the review itself needs. Matched against the URL path. */
const ALWAYS_ALLOWED: RegExp[] = [
  /^\/api\/auth\/login$/,
  /^\/api\/auth\/refresh$/,
  /^\/api\/auth\/logout$/,
  /^\/api\/auth\/ws-ticket$/,
]

const SECRET_PARAMS = ['ticket', 'token', 'access_token', 'refresh_token', 'code', 'state', 'password']

export function redact(raw: string): string {
  try {
    const u = new URL(raw)
    for (const k of SECRET_PARAMS) if (u.searchParams.has(k)) u.searchParams.set(k, 'REDACTED')
    return u.toString()
  } catch {
    return raw
  }
}

let chatBudget = Number(process.env.LIVE_CHAT_BUDGET || 0)

interface Session {
  access: string
  refresh: string
  user: { id: string; email: string; roles: string[]; capabilities: string[] }
}

export interface Evidence {
  console: { type: string; text: string; url?: string }[]
  pageErrors: string[]
  failed: { method: string; url: string; status?: number; error?: string }[]
  slow: { method: string; url: string; ms: number }[]
  blocked: { method: string; url: string }[]
  chatFramesBlocked: number
}

type TestFixtures = {
  /** Extra mutating paths this spec may send (regexes on the URL path). */
  allowMutations: RegExp[]
  /** Start the page signed in (needs LIVE_EMAIL/LIVE_PASSWORD). */
  signedIn: boolean
  evidence: Evidence
}

type WorkerFixtures = {
  liveSession: Session | null
}

function slug(s: string): string {
  return s.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase().slice(0, 80)
}

function outFile(kind: string, info: TestInfo, name: string, ext: string): string {
  const dir = path.join(OUT, kind, info.project.name)
  fs.mkdirSync(dir, { recursive: true })
  return path.join(dir, `${slug(name)}.${ext}`)
}

export const test = base.extend<TestFixtures, WorkerFixtures>({
  allowMutations: [[], { option: true }],
  signedIn: [true, { option: true }],

  liveSession: [async ({ playwright }, use, workerInfo) => {
    const email = process.env.LIVE_EMAIL
    const password = process.env.LIVE_PASSWORD
    if (!email || !password) {
      await use(null)
      return
    }
    const baseURL = (workerInfo.project.use.baseURL as string) || 'https://advandeb.com'
    const api = await playwright.request.newContext({ baseURL })
    const res = await api.post('/api/auth/login', { data: { email, password } })
    if (!res.ok()) {
      await api.dispose()
      throw new Error(`live login failed: HTTP ${res.status()}`)
    }
    const body = await res.json()
    const session: Session = { access: body.access_token, refresh: body.refresh_token, user: body.user }
    await use(session)
    // Revoke whatever refresh token the last test left us with.
    await api.post('/api/auth/logout', { data: { refresh_token: session.refresh } }).catch(() => {})
    await api.dispose()
  }, { scope: 'worker' }],

  // eslint-disable-next-line no-empty-pattern -- Playwright fixtures must destructure
  evidence: async ({}, use) => {
    await use({ console: [], pageErrors: [], failed: [], slow: [], blocked: [], chatFramesBlocked: 0 })
  },

  page: async ({ page, liveSession, signedIn, allowMutations, evidence }, use, testInfo) => {
    if (signedIn) {
      if (!liveSession) throw new Error('signed-in spec without LIVE_EMAIL/LIVE_PASSWORD')
      await page.addInitScript(([a, r]) => {
        // Only on the first document of the test: a later sign-out must stick.
        if (!sessionStorage.getItem('__live_seeded')) {
          localStorage.setItem('access_token', a)
          localStorage.setItem('refresh_token', r)
          sessionStorage.setItem('__live_seeded', '1')
        }
      }, [liveSession.access, liveSession.refresh])
    }

    const allowed = [...ALWAYS_ALLOWED, ...allowMutations]
    await page.route(/\/(api|ws)\//, async (route) => {
      const req = route.request()
      const method = req.method()
      const p = new URL(req.url()).pathname
      if (['GET', 'HEAD', 'OPTIONS'].includes(method) || allowed.some((re) => re.test(p))) {
        await route.fallback()
        return
      }
      evidence.blocked.push({ method, url: redact(req.url()) })
      await route.abort('blockedbyclient')
    })

    // Chat frames: let at most LIVE_CHAT_BUDGET user messages through per run.
    await page.routeWebSocket(/\/ws\/chat\//, (ws) => {
      const server = ws.connectToServer()
      ws.onMessage((msg) => {
        let isUserMessage = false
        try { isUserMessage = JSON.parse(String(msg)).type === 'user_message' } catch { /* not JSON */ }
        if (isUserMessage) {
          if (chatBudget <= 0) { evidence.chatFramesBlocked++; return }
          chatBudget--
        }
        server.send(msg)
      })
    })

    const started = new Map<object, number>()
    page.on('console', (m) => {
      if (m.type() === 'error' || m.type() === 'warning') {
        evidence.console.push({ type: m.type(), text: m.text().slice(0, 2000), url: m.location()?.url ? redact(m.location().url) : undefined })
      }
    })
    page.on('pageerror', (e) => evidence.pageErrors.push(String(e.stack || e).slice(0, 2000)))
    page.on('request', (r) => started.set(r, Date.now()))
    page.on('requestfailed', (r) => {
      const err = r.failure()?.errorText
      if (err === 'net::ERR_BLOCKED_BY_CLIENT') return // recorded as blocked
      evidence.failed.push({ method: r.method(), url: redact(r.url()), error: err })
    })
    page.on('response', (r) => {
      const req = r.request()
      const t0 = started.get(req)
      const ms = t0 ? Date.now() - t0 : 0
      if (r.status() >= 400) evidence.failed.push({ method: req.method(), url: redact(r.url()), status: r.status() })
      if (ms > SLOW_MS) evidence.slow.push({ method: req.method(), url: redact(r.url()), ms })
    })

    await use(page)

    // The app may have refreshed (rotated) the pair; carry the newest forward.
    if (signedIn && liveSession && !page.isClosed()) {
      try {
        const pair = await page.evaluate(() => [localStorage.getItem('access_token'), localStorage.getItem('refresh_token')])
        if (pair[0] && pair[1]) { liveSession.access = pair[0]; liveSession.refresh = pair[1] }
      } catch { /* page navigated away or closed */ }
    }
    const file = outFile('evidence', testInfo, testInfo.titlePath.slice(1).join(' '), 'json')
    fs.writeFileSync(file, JSON.stringify(evidence, null, 2))
    await testInfo.attach('evidence', { path: file, contentType: 'application/json' })
  },
})

export { expect }

/** Full-page screenshot under $LIVE_OUT/screens/<project>/; returns its path. */
export async function shot(page: Page, info: TestInfo, name: string, fullPage = true): Promise<string> {
  const file = outFile('screens', info, name, 'png')
  await page.screenshot({ path: file, fullPage })
  return file
}

/** axe-core (WCAG 2.0/2.1 A+AA) on the current page; full result written to disk. */
export async function axe(page: Page, info: TestInfo, name: string, exclude: string[] = []) {
  let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
  for (const sel of exclude) builder = builder.exclude(sel)
  const result = await builder.analyze()
  const file = outFile('axe', info, name, 'json')
  fs.writeFileSync(file, JSON.stringify(result.violations, null, 2))
  return result.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help }))
}

/** Horizontal overflow: elements wider than the viewport, by selector. */
export async function overflow(page: Page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth
    const out: { sel: string; right: number }[] = []
    for (const el of Array.from(document.querySelectorAll('body *'))) {
      const r = el.getBoundingClientRect()
      if (r.width > 0 && r.right > vw + 1) {
        const cls = typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).join('.') : ''
        out.push({ sel: el.tagName.toLowerCase() + cls, right: Math.round(r.right) })
      }
      if (out.length >= 25) break
    }
    return { scrollWidth: document.documentElement.scrollWidth, viewport: vw, offenders: out }
  })
}
