// Public surface, signed out: home, login, enrolment (inspected, never sent),
// and an unknown route. Per page and viewport: screenshot, axe-core, overflow,
// document metadata, duplicate ids, landmarks, touch-target sizes and what the
// page downloaded. Read-only: no form is submitted here.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect, shot, axe, overflow } from './guard'

test.use({ signedIn: false })

const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'

function record(project: string, name: string, data: unknown) {
  const dir = path.join(OUT, 'data', project)
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, `${name}.json`), JSON.stringify(data, null, 2))
}

const PAGES = [
  { name: 'home', path: '/', ready: 'h1' },
  { name: 'login', path: '/login', ready: 'input[type="email"]' },
  { name: 'join', path: '/elicitation/join', ready: 'h1' },
  { name: 'notfound', path: '/no-such-page-live-review', ready: 'h1' },
]

for (const p of PAGES) {
  test(`public page: ${p.name}`, async ({ page, evidence }, info) => {
    // When the first rendered heading shows up, relative to navigation start.
    await page.addInitScript(() => {
      const w = window as unknown as { __firstH1?: number }
      const mo = new MutationObserver(() => {
        if (w.__firstH1 === undefined && document.querySelector('h1')) {
          w.__firstH1 = performance.now()
          mo.disconnect()
        }
      })
      mo.observe(document, { childList: true, subtree: true })
    })

    await page.goto(p.path, { waitUntil: 'networkidle' })
    await expect(page.locator(p.ready).first()).toBeVisible()
    if (p.name === 'join') {
      // Categories come from the API; wait for them or the error state.
      await page.locator('.chip, .cat-error').first().waitFor({ timeout: 15_000 }).catch(() => {})
    }

    const data = await page.evaluate(async () => {
      const meta = (sel: string) => document.querySelector(sel)?.getAttribute('content') ?? null
      const ids = new Map<string, number>()
      for (const el of Array.from(document.querySelectorAll('[id]'))) ids.set(el.id, (ids.get(el.id) || 0) + 1)
      const dupIds = [...ids].filter(([, n]) => n > 1).map(([id, n]) => ({ id, n }))

      const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
      const res = (performance.getEntriesByType('resource') as PerformanceResourceTiming[]).map((r) => ({
        path: new URL(r.name).pathname,
        type: r.initiatorType,
        transfer: r.transferSize,
        encoded: r.encodedBodySize,
        decoded: r.decodedBodySize,
        end: Math.round(r.responseEnd),
      }))
      const lcp = await new Promise<number | null>((resolve) => {
        let v: number | null = null
        try {
          new PerformanceObserver((l) => {
            const e = l.getEntries()
            v = e[e.length - 1].startTime
          }).observe({ type: 'largest-contentful-paint', buffered: true })
        } catch { /* unsupported */ }
        setTimeout(() => resolve(v), 500)
      })
      const fcp = performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? null

      const interactive = Array.from(document.querySelectorAll<HTMLElement>(
        'a[href], button, input, select, textarea, [role="button"], [role="radio"], [tabindex]:not([tabindex="-1"])',
      )).filter((el) => el.offsetParent !== null || el.getClientRects().length > 0).map((el) => {
        const r = el.getBoundingClientRect()
        const inline = el.tagName === 'A' && getComputedStyle(el).display === 'inline'
        return {
          tag: el.tagName.toLowerCase(),
          text: (el.innerText || el.getAttribute('aria-label') || (el as HTMLInputElement).name || el.id || '').trim().slice(0, 50),
          w: Math.round(r.width),
          h: Math.round(r.height),
          inline,
        }
      })

      return {
        url: location.pathname + location.search + location.hash,
        title: document.title,
        lang: document.documentElement.lang,
        description: meta('meta[name="description"]'),
        canonical: document.querySelector('link[rel="canonical"]')?.getAttribute('href') ?? null,
        og: {
          title: meta('meta[property="og:title"]'),
          url: meta('meta[property="og:url"]'),
          image: meta('meta[property="og:image"]'),
          twitterImage: meta('meta[name="twitter:image"]'),
        },
        appIds: document.querySelectorAll('#app').length,
        dupIds,
        headings: Array.from(document.querySelectorAll('h1, h2, h3')).map((h) => `${h.tagName}: ${(h as HTMLElement).innerText.trim().slice(0, 60)}`),
        landmarks: {
          main: document.querySelectorAll('main, [role="main"]').length,
          nav: document.querySelectorAll('nav, [role="navigation"]').length,
          header: document.querySelectorAll('header, [role="banner"]').length,
          footer: document.querySelectorAll('footer, [role="contentinfo"]').length,
        },
        skipLink: !!document.querySelector('a.skip-link, a[href="#main"], a[href="#main-content"]'),
        links: Array.from(document.querySelectorAll<HTMLAnchorElement>('a[href]')).map((a) => ({
          text: a.innerText.trim().slice(0, 40),
          href: a.getAttribute('href'),
          targetExists: a.getAttribute('href')?.startsWith('#') ? !!document.querySelector(a.getAttribute('href')!) : null,
        })),
        imagesWithoutAlt: document.querySelectorAll('img:not([alt])').length,
        timing: {
          ttfb: nav ? Math.round(nav.responseStart) : null,
          domContentLoaded: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
          load: nav ? Math.round(nav.loadEventEnd) : null,
          fcp: fcp && Math.round(fcp),
          lcp: lcp && Math.round(lcp),
          firstH1: Math.round((window as unknown as { __firstH1?: number }).__firstH1 ?? -1),
        },
        resources: res,
        interactive,
      }
    })

    const totals = { requests: data.resources.length + 1, transfer: 0, decoded: 0, js: 0, jsDecoded: 0, css: 0, img: 0, font: 0 }
    for (const r of data.resources) {
      totals.transfer += r.transfer
      totals.decoded += r.decoded
      if (r.path.endsWith('.js')) { totals.js += r.transfer; totals.jsDecoded += r.decoded }
      else if (r.path.endsWith('.css')) totals.css += r.transfer
      else if (/\.(png|svg|ico|jpg|webp)$/.test(r.path)) totals.img += r.transfer
      else if (/\.(woff2?|ttf)$/.test(r.path)) totals.font += r.transfer
    }

    const small = info.project.name === 'phone'
      ? data.interactive.filter((i) => !i.inline && (i.w < 44 || i.h < 44))
      : []

    const ov = await overflow(page)
    const violations = await axe(page, info, `axe-${p.name}`)
    const screenshot = await shot(page, info, p.name)
    // Above-the-fold view as well, for the phone layout.
    await shot(page, info, `${p.name}-fold`, false)

    record(info.project.name, p.name, {
      ...data,
      totals,
      smallTouchTargets: small,
      overflow: ov,
      axe: violations,
      screenshot,
      evidence: { console: evidence.console, pageErrors: evidence.pageErrors, failed: evidence.failed, blocked: evidence.blocked },
    })

    expect(evidence.blocked, 'the review must not send anything').toEqual([])
  })
}
