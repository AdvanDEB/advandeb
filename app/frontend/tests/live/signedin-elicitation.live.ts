// /elicitation and /admin/experts, signed in: a quick load-and-blocker check
// only (both are being redesigned elsewhere). Loads the page, checks for page
// errors and 5xx responses, takes one screenshot. Clicks nothing, judges
// nothing. Admin pages list other people: no text is recorded.
import { test, expect, shot } from './guard'
import { record } from './collect'

for (const [name, path] of [['elicitation', '/elicitation'], ['admin-experts', '/admin/experts']] as const) {
  test(`${name}: loads without a blocker (look only)`, async ({ page, evidence }, info) => {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
    await page.locator('main h1').waitFor()
    await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
    const state = await page.evaluate(() => ({
      url: location.pathname,
      mainChildren: document.querySelector('main')?.children.length ?? 0,
    }))
    await shot(page, info, `${name}-load`, false)
    record(info, `${name}-load`, { state, evidence })
    expect(state.url).toBe(path)
    expect(evidence.pageErrors).toEqual([])
    expect(evidence.failed.filter((f) => (f.status ?? 0) >= 500)).toEqual([])
    expect(evidence.blocked).toEqual([])
  })
}
