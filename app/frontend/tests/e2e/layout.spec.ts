import { test, expect, type Page } from '@playwright/test'

// The signed-in shell's sidebar is sized with the --el-* tokens. While they
// never resolved (scoped :root, F-001) the rail was cramped: icons of uneven
// size with no row padding, the » toggle jammed into a corner, log out on top
// of the avatar (F-025). Resolving the tokens alone then clipped the 44px
// toggle and log out out of the 60px rail, and a tap on the toggle could miss
// because focusing it widened the rail under the finger.
async function signIn(page: Page) {
  await page.addInitScript(() => localStorage.setItem('access_token', 'mock-token-for-e2e'))
  await page.route('**/api/auth/config', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"google_oauth_enabled":false}' }))
  await page.route('**/api/users/me', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      // An administrator sees all twelve links.
      body: JSON.stringify({
        id: 'u1', email: 'test@example.com', full_name: 'Test User',
        roles: ['administrator'], capabilities: ['sf_elicitation'],
      }),
    }))
}

type Box = { x: number, y: number, width: number, height: number }
const overlaps = (a: Box, b: Box) =>
  !(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y)

async function insideRail(page: Page, selector: string) {
  const rail = (await page.locator('.sidebar').boundingBox())!
  const box = (await page.locator(selector).boundingBox())!
  return box.x >= rail.x && box.x + box.width <= rail.x + rail.width + 0.5 && box.height >= 44
}

const railWidth = (page: Page) => page.locator('.sidebar').evaluate(el => el.getBoundingClientRect().width)

async function open(page: Page) {
  await signIn(page)
  await page.goto('/documentation')
  // Keep the pointer off the hover-to-expand rail, inside the viewport.
  const { width, height } = page.viewportSize()!
  await page.mouse.move(width - 5, height - 5)
  await expect(page.locator('.sidebar')).toBeVisible()
}

test.describe('Sidebar rail (desktop)', () => {
  test.beforeEach(async ({ page }) => open(page))

  test('collapsed: tokens resolve, rows and icons are uniform', async ({ page }) => {
    await expect.poll(() => railWidth(page)).toBe(60)
    const m = await page.evaluate(() => {
      const rail = document.querySelector('.sidebar')!
      const boxes = (s: string) => [...document.querySelectorAll(s)].map(e => e.getBoundingClientRect())
      return {
        s2: getComputedStyle(rail).getPropertyValue('--el-s2').trim(),
        rows: boxes('.nav-link').map(r => Math.round(r.height)),
        icons: boxes('.nav-icon').map(r => `${Math.round(r.width)}x${Math.round(r.height)}@${Math.round(r.x + r.width / 2)}`),
      }
    })
    expect(m.s2).toMatch(/^0?\.5rem$/) // minified in a build
    expect(m.rows).toHaveLength(12)
    expect(new Set(m.rows)).toEqual(new Set([44]))
    expect(new Set(m.icons).size).toBe(1) // same box, same centre line
    expect(m.icons[0]).toMatch(/^22x22@/)
  })

  test('collapsed: toggle and log out are whole 44px targets that overlap nothing', async ({ page }) => {
    await expect.poll(() => railWidth(page)).toBe(60)
    expect(await insideRail(page, '.rail-toggle')).toBe(true)
    expect(await insideRail(page, '.logout-btn')).toBe(true)
    const [toggle, brand, logout, avatar] = await Promise.all(
      ['.rail-toggle', '.brand-icon', '.logout-btn', '.user-avatar-placeholder']
        .map(async s => (await page.locator(s).boundingBox())!))
    expect(toggle.width).toBe(44)
    expect(toggle.height).toBe(44)
    expect(overlaps(toggle, brand)).toBe(false)
    expect(overlaps(logout, avatar)).toBe(false)
  })

  test('expanded: the same controls still fit', async ({ page }) => {
    await page.locator('.rail-toggle').click()
    await page.mouse.move(1000, 600)
    await expect.poll(() => railWidth(page)).toBe(200)
    expect(await insideRail(page, '.rail-toggle')).toBe(true)
    expect(await insideRail(page, '.logout-btn')).toBe(true)
  })

  test('keyboard focus in the rail shows the labels', async ({ page }) => {
    await page.keyboard.press('Tab') // skip link
    await page.keyboard.press('Tab') // first control in the rail
    await expect.poll(() => railWidth(page)).toBe(200)
  })
})

test.describe('Sidebar rail without hover (tablet, reduced motion)', () => {
  test.use({ viewport: { width: 768, height: 1024 }, hasTouch: true, contextOptions: { reducedMotion: 'reduce' } })

  for (const how of ['tap', 'click'] as const) {
    // A click focuses the toggle on mouse-down. With :focus-within that
    // widened the rail at once, the toggle moved from under the pointer before
    // mouse-up, and the click never happened.
    test(`a ${how} on the toggle expands the rail`, async ({ page }) => {
      await open(page)
      await expect.poll(() => railWidth(page)).toBe(60)
      await page.locator('.rail-toggle')[how]()
      await expect(page.locator('.rail-toggle')).toHaveAttribute('aria-expanded', 'true')
      await expect.poll(() => railWidth(page)).toBe(200)
    })
  }
})
