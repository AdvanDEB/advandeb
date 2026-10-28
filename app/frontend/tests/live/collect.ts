/**
 * Measurements shared by the review specs: what a page rendered, downloaded
 * and exposes to assistive technology. Text that could carry personal data
 * (other users' names and emails on admin pages) is redacted or not recorded.
 */
import fs from 'node:fs'
import path from 'node:path'
import type { Page, TestInfo } from '@playwright/test'

const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'

export function record(info: TestInfo, name: string, data: unknown): string {
  const dir = path.join(OUT, 'data', info.project.name)
  fs.mkdirSync(dir, { recursive: true })
  const file = path.join(dir, `${name.replace(/[^a-z0-9-]+/gi, '-')}.json`)
  fs.writeFileSync(file, JSON.stringify(data, null, 2))
  return file
}

/** Element screenshot path under $LIVE_OUT/screens/<project>/. */
export function screenPath(info: TestInfo, name: string): string {
  const dir = path.join(OUT, 'screens', info.project.name)
  fs.mkdirSync(dir, { recursive: true })
  return path.join(dir, `${name.replace(/[^a-z0-9-]+/gi, '-')}.png`)
}

/** Records when the first heading appears (call before goto). */
export async function markFirstHeading(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __firstHeading?: number }
    const mo = new MutationObserver(() => {
      if (w.__firstHeading === undefined && document.querySelector('main h1, main h2, .kb-view h1, .kb-header')) {
        w.__firstHeading = performance.now()
        mo.disconnect()
      }
    })
    mo.observe(document, { childList: true, subtree: true })
  })
}

/** Navigate and wait for the view to settle without hanging on open streams. */
export async function open(page: Page, url: string, ready = 'main h1, main h2, .kb-header, .not-found h1') {
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await page.locator(ready).first().waitFor({ timeout: 20_000 }).catch(() => {})
  await page.waitForLoadState('networkidle', { timeout: 12_000 }).catch(() => {})
}

export interface PageData {
  url: string
  title: string
  h1: string[]
  appIds: number
  dupIds: { id: string; n: number }[]
  landmarks: Record<string, number>
  timing: Record<string, number | null>
  totals: { requests: number; transfer: number; decoded: number; js: number; css: number; api: number }
  apiCalls: { path: string; status?: number }[]
  slowest: { path: string; ms: number }[]
  smallTargets: { tag: string; text: string; w: number; h: number }[]
  unlabelled: { tag: string; type: string | null }[]
  tokens: { onRoot: string }
}

/** Snapshot of the current page. `personal` suppresses visible-text capture. */
export async function pageData(page: Page, opts: { personal?: boolean; phone?: boolean } = {}): Promise<PageData> {
  return page.evaluate(async ({ personal, phone }) => {
    const redact = (s: string) => s.replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '<email>')
    const ids = new Map<string, number>()
    for (const el of Array.from(document.querySelectorAll('[id]'))) ids.set(el.id, (ids.get(el.id) || 0) + 1)
    const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
    const res = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
    const lcp = await new Promise<number | null>((resolve) => {
      let v: number | null = null
      try {
        new PerformanceObserver((l) => { const e = l.getEntries(); v = e[e.length - 1].startTime })
          .observe({ type: 'largest-contentful-paint', buffered: true })
      } catch { /* unsupported */ }
      setTimeout(() => resolve(v), 300)
    })
    const totals = { requests: res.length + 1, transfer: 0, decoded: 0, js: 0, css: 0, api: 0 }
    for (const r of res) {
      totals.transfer += r.transferSize
      totals.decoded += r.decodedBodySize
      const p = new URL(r.name).pathname
      if (p.endsWith('.js')) totals.js += r.transferSize
      else if (p.endsWith('.css')) totals.css += r.transferSize
      else if (p.startsWith('/api/')) totals.api += r.transferSize
    }
    const visible = (el: Element) => (el as HTMLElement).offsetParent !== null || el.getClientRects().length > 0
    const interactive = Array.from(document.querySelectorAll<HTMLElement>(
      'a[href], button, input:not([type="hidden"]), select, textarea, [role="button"], [role="tab"], [role="radio"]',
    )).filter(visible)
    const smallTargets = phone
      ? interactive.filter((el) => {
        const r = el.getBoundingClientRect()
        const inline = el.tagName === 'A' && getComputedStyle(el).display === 'inline'
        return !inline && r.width > 0 && (r.width < 24 || r.height < 24)
      }).slice(0, 30).map((el) => {
        const r = el.getBoundingClientRect()
        return {
          tag: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : ''),
          text: personal ? '' : redact((el.getAttribute('aria-label') || el.innerText || '').trim().slice(0, 30)),
          w: Math.round(r.width), h: Math.round(r.height),
        }
      })
      : []
    const unlabelled = interactive.filter((el) => {
      if (!['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return false
      const i = el as HTMLInputElement
      return !(i.labels && i.labels.length) && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && !el.getAttribute('title')
    }).map((el) => ({ tag: el.tagName.toLowerCase(), type: el.getAttribute('type') }))
    return {
      url: location.pathname,
      title: document.title,
      h1: Array.from(document.querySelectorAll('h1')).map((h) => personal ? '(h1)' : redact((h as HTMLElement).innerText.trim().slice(0, 60))),
      appIds: document.querySelectorAll('#app').length,
      dupIds: [...ids].filter(([, n]) => n > 1).map(([id, n]) => ({ id, n })).slice(0, 10),
      landmarks: {
        main: document.querySelectorAll('main, [role="main"]').length,
        nav: document.querySelectorAll('nav, [role="navigation"]').length,
        skipLink: document.querySelectorAll('a.skip-link').length,
      },
      timing: {
        domContentLoaded: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
        load: nav ? Math.round(nav.loadEventEnd) : null,
        fcp: Math.round(performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? -1),
        lcp: lcp && Math.round(lcp),
        firstHeading: Math.round((window as unknown as { __firstHeading?: number }).__firstHeading ?? -1),
      },
      totals,
      apiCalls: res.filter((r) => new URL(r.name).pathname.startsWith('/api/'))
        .map((r) => ({ path: new URL(r.name).pathname.replace(/[0-9a-f]{24}|[0-9a-f-]{36}/g, ':id'), status: (r as PerformanceResourceTiming & { responseStatus?: number }).responseStatus })),
      slowest: res.map((r) => ({ path: new URL(r.name).pathname.replace(/[0-9a-f]{24}|[0-9a-f-]{36}/g, ':id'), ms: Math.round(r.duration) }))
        .sort((a, b) => b.ms - a.ms).slice(0, 5),
      smallTargets,
      unlabelled,
      tokens: { onRoot: getComputedStyle(document.documentElement).getPropertyValue('--el-touch') },
    }
  }, { personal: !!opts.personal, phone: !!opts.phone })
}

/** Press Tab up to `max` times; describe each stop and whether focus is visible. */
export async function tabWalk(page: Page, max: number, personal = false) {
  const stops: { tag: string; label: string; indicator: string; pos: string }[] = []
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab')
    const s = await page.evaluate((personal) => {
      const el = document.activeElement as HTMLElement | null
      if (!el || el === document.body) return null
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0
      const shadow = cs.boxShadow !== 'none'
      const raw = (el.getAttribute('aria-label') || el.innerText || (el as HTMLInputElement).placeholder || '').trim().replace(/\s+/g, ' ').slice(0, 40)
      return {
        tag: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : ''),
        label: personal ? '' : raw.replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '<email>'),
        indicator: outline ? `outline ${cs.outlineWidth} ${cs.outlineColor}` : shadow ? `shadow ${cs.boxShadow.slice(0, 40)}` : 'NONE',
        pos: `${Math.round(r.top + scrollY)},${Math.round(r.left)}`,
      }
    }, personal)
    if (!s) break
    if (stops.length && stops[0].pos === s.pos && stops[0].tag === s.tag) break
    stops.push(s)
  }
  return stops
}
