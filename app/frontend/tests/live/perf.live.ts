// First visit to the landing page on a throttled phone (Lighthouse's "slow
// 4G" profile: 150 ms RTT, ~1.6 Mbps down, 4x CPU slowdown), cold cache.
// One page load per run, phone project only.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from './guard'

test.use({ signedIn: false })

const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'

test('perf: landing page, cold cache, slow 4G + 4x CPU', async ({ page, evidence }, info) => {
  test.skip(info.project.name !== 'phone', 'throttled run on the phone profile only')

  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Network.enable')
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8,
  })
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 })

  await page.addInitScript(() => {
    const w = window as unknown as { __firstH1?: number }
    const mo = new MutationObserver(() => {
      if (w.__firstH1 === undefined && document.querySelector('h1')) { w.__firstH1 = performance.now(); mo.disconnect() }
    })
    mo.observe(document, { childList: true, subtree: true })
  })

  await page.goto('/', { waitUntil: 'networkidle', timeout: 60_000 })
  await expect(page.locator('h1')).toBeVisible()
  const m = await page.evaluate(async () => {
    const lcp = await new Promise<number | null>((resolve) => {
      let v: number | null = null
      new PerformanceObserver((l) => { const e = l.getEntries(); v = e[e.length - 1].startTime })
        .observe({ type: 'largest-contentful-paint', buffered: true })
      setTimeout(() => resolve(v), 500)
    })
    const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming
    const res = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
    return {
      firstH1: Math.round((window as unknown as { __firstH1?: number }).__firstH1 ?? -1),
      fcp: Math.round(performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? -1),
      lcp: lcp && Math.round(lcp),
      domContentLoaded: Math.round(nav.domContentLoadedEventEnd),
      load: Math.round(nav.loadEventEnd),
      transfer: res.reduce((a, r) => a + r.transferSize, 0) + nav.transferSize,
      byChunk: res.map((r) => ({ path: new URL(r.name).pathname, transfer: r.transferSize, end: Math.round(r.responseEnd) })),
    }
  })
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 })

  const dir = path.join(OUT, 'data', info.project.name)
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, 'perf-home-slow4g.json'), JSON.stringify(m, null, 2))
  expect(evidence.blocked).toEqual([])
})
