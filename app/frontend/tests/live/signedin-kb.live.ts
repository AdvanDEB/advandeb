// /kb, signed in as a curator/administrator: the graph the view loads by
// default (no other schema is selected, so no artifact build is triggered),
// then each tab in turn. Look only — Reset DB, rebuild, ingestion, linking,
// relation review and suggestion decisions are never touched, and relations
// are not loaded (loading them arms the y/n review hotkeys).
import { test, expect, shot, axe, overflow } from './guard'
import { record } from './collect'

test('kb: default graph and every tab (look only)', async ({ page, evidence }, info) => {
  test.setTimeout(150_000)
  await page.addInitScript(() => {
    const w = window as unknown as { __canvasAt?: number; __longTasks: number; __longMax: number }
    w.__longTasks = 0
    w.__longMax = 0
    try {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) { w.__longTasks += e.duration; w.__longMax = Math.max(w.__longMax, e.duration) }
      }).observe({ type: 'longtask', buffered: true })
    } catch { /* unsupported */ }
    const mo = new MutationObserver(() => {
      if (w.__canvasAt === undefined && document.querySelector('.graph-stage canvas')) { w.__canvasAt = performance.now(); mo.disconnect() }
    })
    mo.observe(document, { childList: true, subtree: true })
  })

  await page.goto('/kb', { waitUntil: 'domcontentloaded' })
  await page.locator('.kb-header').waitFor()
  // The default schema's graph: canvas, or an empty/error message.
  await page.locator('.graph-stage canvas, .graph-empty, .error-alert').first().waitFor({ timeout: 90_000 }).catch(() => {})
  await page.locator('.graph-loading-overlay').waitFor({ state: 'hidden', timeout: 90_000 }).catch(() => {})
  await page.waitForTimeout(3000)

  const graph = await page.evaluate(() => {
    const w = window as unknown as { __canvasAt?: number; __longTasks: number; __longMax: number }
    const res = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
    const mem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory
    return {
      schema: document.querySelector('.schema-tag')?.textContent?.trim() ?? null,
      canvasAt: Math.round(w.__canvasAt ?? -1),
      longTasksMs: Math.round(w.__longTasks),
      longestTaskMs: Math.round(w.__longMax),
      heapMB: mem ? Math.round(mem.usedJSHeapSize / 1e6) : null,
      empty: document.querySelector('.graph-empty')?.textContent?.trim() ?? null,
      error: document.querySelector('.error-alert')?.textContent?.trim() ?? null,
      transferKB: Math.round(res.reduce((a, r) => a + r.transferSize, 0) / 1024),
      api: res.filter((r) => new URL(r.name).pathname.startsWith('/api/')).map((r) => ({
        path: new URL(r.name).pathname.replace(/[0-9a-f]{24}/g, ':id'),
        kb: Math.round(r.transferSize / 1024), decodedKB: Math.round(r.decodedBodySize / 1024), ms: Math.round(r.duration),
      })),
      js: res.filter((r) => r.name.endsWith('.js')).map((r) => new URL(r.name).pathname.replace(/^\/assets\//, '').replace(/-[\w-]{8}\.js$/, '')),
    }
  })
  await shot(page, info, 'kb-graph', false)
  const graphAxe = await axe(page, info, 'axe-kb-graph', ['canvas'])

  // Tablist keyboard contract: focus the active tab, press ArrowRight.
  await page.locator('[role="tab"][aria-selected="true"]').focus()
  await page.keyboard.press('ArrowRight')
  const arrow = await page.evaluate(() => ({
    focused: document.activeElement?.textContent?.trim(),
    selected: document.querySelector('[role="tab"][aria-selected="true"]')?.textContent?.trim(),
    tabindexes: Array.from(document.querySelectorAll('[role="tab"]')).map((t) => (t as HTMLElement).tabIndex),
    controls: Array.from(document.querySelectorAll('[role="tab"]')).map((t) => t.getAttribute('aria-controls')),
  }))

  const tabs: Record<string, unknown> = {}
  for (const label of ['Ingestion', 'Database', 'KG Builder', 'Suggestions']) {
    await page.getByRole('tab', { name: label }).click()
    await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
    await page.waitForTimeout(1200)
    const id = label.toLowerCase().replace(/\s+/g, '-')
    await shot(page, info, `kb-${id}`, false)
    tabs[label] = {
      axe: await axe(page, info, `axe-kb-${id}`, ['canvas']),
      overflow: (await overflow(page)).scrollWidth,
      errors: await page.locator('.error-alert').allTextContents(),
    }
  }

  record(info, 'kb', { graph, graphAxe, arrow, tabs, evidence })
  expect(evidence.blocked).toEqual([])
})
