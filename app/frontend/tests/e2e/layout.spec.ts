import { test, expect, type Page } from '@playwright/test'

// The signed-in shell's sidebar is sized with the --el-* tokens. While they
// never resolved (scoped :root, see enrolment.spec.ts) its controls collapsed
// to their content size; with the tokens live, the 44px expand toggle and log
// out button no longer fit the 60px rail side by side and were clipped.
async function signIn(page: Page) {
  await page.addInitScript(() => localStorage.setItem('access_token', 'mock-token-for-e2e'))
  await page.route('**/api/auth/config', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"google_oauth_enabled":false}' }))
  await page.route('**/api/users/me', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'u1', email: 'test@example.com', full_name: 'Test User',
        roles: ['administrator'], capabilities: [],
      }),
    }))
}

async function insideRail(page: Page, selector: string) {
  const rail = (await page.locator('.sidebar').boundingBox())!
  const box = (await page.locator(selector).boundingBox())!
  return box.x >= rail.x && box.x + box.width <= rail.x + rail.width + 0.5 && box.height >= 44
}

test.describe('Sidebar rail', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page)
    await page.goto('/documentation')
    await page.mouse.move(900, 400) // keep the pointer off the hover-to-expand rail
    await expect(page.locator('.sidebar')).toBeVisible()
  })

  test('collapsed: expand toggle and log out are whole 44px targets inside the rail', async ({ page }) => {
    await expect.poll(() => page.locator('.sidebar').evaluate(el => el.getBoundingClientRect().width)).toBe(60)
    expect(await insideRail(page, '.rail-toggle')).toBe(true)
    expect(await insideRail(page, '.logout-btn')).toBe(true)
  })

  test('expanded: the same controls still fit', async ({ page }) => {
    await page.locator('.rail-toggle').click()
    await page.mouse.move(900, 400)
    await expect.poll(() => page.locator('.sidebar').evaluate(el => el.getBoundingClientRect().width)).toBe(200)
    expect(await insideRail(page, '.rail-toggle')).toBe(true)
    expect(await insideRail(page, '.logout-btn')).toBe(true)
  })
})
