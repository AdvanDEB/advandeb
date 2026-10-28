import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

// F-008: on the public pages the primary buttons and links were white on
// #4285f4 (3.56:1), the login hint #888 on white (3.5:1), and the footer link
// differed from its text by colour alone. WCAG 1.4.3 AA wants 4.5:1.
test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/config', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '{"google_oauth_enabled":false}' }))
  await page.route('**/api/users/me', r =>
    r.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Not authenticated"}' }))
})

for (const path of ['/', '/login', '/no/such/page']) {
  test(`${path}: no colour-contrast or link-in-text-block violations`, async ({ page }) => {
    await page.goto(path)
    await expect(page.locator('h1')).toBeVisible()
    const { violations } = await new AxeBuilder({ page })
      .withRules(['color-contrast', 'link-in-text-block'])
      .analyze()
    expect(violations.map(v => `${v.id}: ${v.nodes.map(n => n.target.join(' ')).join(', ')}`)).toEqual([])
  })
}
