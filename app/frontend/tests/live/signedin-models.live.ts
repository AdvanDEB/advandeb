// tDEB models, signed in: the library, then one of the reviewer's own models
// opened through its "Open" button (navigation only). On desktop, one batch
// simulation with the panel's defaults — read-only on the server, nothing is
// saved — to see the Plotly results. Nothing is edited, dragged, duplicated,
// published or deleted.
import { test, expect, shot, axe, overflow } from './guard'
import { pageData, record } from './collect'

test.use({ allowMutations: [/^\/api\/tdeb\/models\/[^/]+\/simulate$/] })

test('models: library and one own model (one simulation on desktop)', async ({ page, evidence }, info) => {
  test.setTimeout(150_000)
  await page.goto('/models', { waitUntil: 'domcontentloaded' })
  await page.locator('main h1').waitFor()
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})

  const library = await page.evaluate(() => ({
    ownCards: document.querySelectorAll('.card-actions .card-action').length,
    sections: Array.from(document.querySelectorAll('.section-title')).map((h) => h.textContent?.trim().replace(/\s+/g, ' ')),
    cardRoles: Array.from(document.querySelectorAll('[role="button"]')).slice(0, 3).map((c) => ({ tabindex: c.getAttribute('tabindex'), label: c.getAttribute('aria-label') })),
  }))

  const openBtn = page.getByRole('button', { name: 'Open', exact: true }).first()
  if (!(await openBtn.count())) {
    record(info, 'models', { library, skipped: 'no own model to open' })
    test.skip(true, 'the account has no own model')
    return
  }
  const t0 = Date.now()
  await openBtn.click()
  await page.waitForURL(/\/models\/[^/]+$/)
  await page.locator('.tab-bar, .canvas, svg').first().waitFor({ timeout: 30_000 }).catch(() => {})
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})
  const editorMs = Date.now() - t0
  await page.waitForTimeout(1000)
  const editor = await pageData(page, { phone: info.project.name === 'phone' })
  await shot(page, info, 'models-editor', false)
  const editorAxe = await axe(page, info, 'axe-models-editor', ['svg'])
  const editorOverflow = await overflow(page)
  const saveIndicator = await page.locator('[class*="save"], [class*="Save"]').allTextContents()

  let simulation: unknown = null
  if (info.project.name === 'desktop') {
    const run = page.getByRole('button', { name: /Run simulation/ })
    if (await run.isEnabled().catch(() => false)) {
      const s0 = Date.now()
      const resP = page.waitForResponse((r) => /\/simulate$/.test(new URL(r.url()).pathname), { timeout: 90_000 })
      await run.click()
      const res = await resP.catch(() => null)
      await page.locator('.js-plotly-plot, .plot-container, .results-empty, .sim-error').first().waitFor({ timeout: 60_000 }).catch(() => {})
      await page.waitForTimeout(1500)
      simulation = {
        status: res?.status() ?? null,
        ms: Date.now() - s0,
        responseKB: res ? Math.round(((await res.body().catch(() => Buffer.alloc(0))).length) / 1024) : null,
        plots: await page.locator('.js-plotly-plot').count(),
        error: await page.locator('.sim-error, .error').allTextContents(),
      }
      await shot(page, info, 'models-results', false)
      await axe(page, info, 'axe-models-results', ['svg', '.js-plotly-plot'])
    } else {
      simulation = 'run button disabled'
    }
  }

  record(info, 'models', {
    library, editorMs, editor: { ...editor, smallTargets: editor.smallTargets.slice(0, 15) },
    editorAxe, editorOverflow: { w: editorOverflow.scrollWidth, vp: editorOverflow.viewport, offenders: editorOverflow.offenders.slice(0, 6) },
    saveIndicator, simulation, evidence,
  })
  expect(evidence.blocked).toEqual([])
})
