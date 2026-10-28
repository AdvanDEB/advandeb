import { test, expect } from '@playwright/test'

// The enrolment page shipped unstyled: its --el-* design tokens were declared
// in a scoped style block, compiled to [data-v-…]:root, and never resolved.
// The submit button came out white text on a transparent background.
test.describe('Enrolment page styling', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/auth/config', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"google_oauth_enabled":false}' }))
    await page.route('**/api/users/me', route =>
      route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Not authenticated"}' }))
    await page.route('**/api/enrolment/categories', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          categories: [
            { key: 'growth', label: 'Growth', n_facts: 40, currently_assessed: true },
            { key: 'reproduction', label: 'Reproduction', n_facts: 25, currently_assessed: false },
          ],
        }),
      }))
    await page.goto('/elicitation/join')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Join')
  })

  test('design tokens resolve', async ({ page }) => {
    const tokens = await page.locator('.enrol-page').evaluate(el => {
      const cs = getComputedStyle(el)
      return { accent: cs.getPropertyValue('--el-accent').trim(), s4: cs.getPropertyValue('--el-s4').trim() }
    })
    expect(tokens).toEqual({ accent: '#111827', s4: '1rem' })
  })

  test('"Request access" is a visible, touch-sized button', async ({ page }) => {
    const submit = page.getByRole('button', { name: 'Request access' })
    const style = await submit.evaluate(el => {
      const cs = getComputedStyle(el)
      return { bg: cs.backgroundColor, color: cs.color, height: el.getBoundingClientRect().height }
    })
    expect(style.bg).toBe('rgb(17, 24, 39)')
    expect(style.color).toBe('rgb(255, 255, 255)')
    expect(style.height).toBeGreaterThanOrEqual(44)
  })
})
