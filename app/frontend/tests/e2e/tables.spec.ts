import { test, expect } from '@playwright/test'

// F-034: on a phone a wide table scrolls inside its card. The scroll region
// is a Tab stop with an edge fade; its focus ring was drawn outside the box
// and the fade's mask clipped it away entirely.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

const user = (i: number, roles: string[]) => ({
  id: `u${i}`, email: `person${i}@example.org`, full_name: `Test Person ${i}`, avatar_url: null, roles,
  capabilities: [], status: 'active', chat_history_visible_to_admin: true,
  created_at: '2026-09-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z',
})

test('the users table: named scroll region with a visible focus ring', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('access_token', 'mock-token-for-e2e'))
  await page.route('**/api/auth/config', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '{"google_oauth_enabled":false}' }))
  await page.route('**/api/users/me', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(user(0, ['administrator'])) }))
  await page.route('**/api/users/?*', r => r.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ items: [user(1, ['administrator']), user(2, ['knowledge_curator'])], total: 2, skip: 0, limit: 50 }),
  }))
  await page.goto('/admin/users')

  const region = page.getByRole('region', { name: 'Users table, scrolls sideways' })
  await expect(region).toBeVisible()
  await expect(region).toHaveClass(/scroll-more-right/)

  await page.keyboard.press('Tab')                      // reach it from the keyboard
  for (let i = 0; i < 20 && !(await region.evaluate(el => el === document.activeElement)); i++) {
    await page.keyboard.press('Tab')
  }
  await expect(region).toBeFocused()

  // The ring is painted: the region's top edge, away from the faded right
  // edge, is the focus blue (#2563eb), not the table's background.
  const box = (await region.boundingBox())!
  const shot = await page.screenshot({ clip: { x: box.x + 8, y: box.y, width: box.width / 2, height: 2 } })
  const blue = await page.evaluate(async (b64) => {
    const img = new Image()
    await new Promise(r => { img.onload = r; img.src = `data:image/png;base64,${b64}` })
    const c = document.createElement('canvas'); c.width = img.width; c.height = img.height
    const g = c.getContext('2d')!; g.drawImage(img, 0, 0)
    const d = g.getImageData(0, 0, img.width, img.height).data
    let n = 0
    for (let i = 0; i < d.length; i += 4) if (d[i + 2] > 180 && d[i] < 90 && d[i + 1] < 140) n++
    return n / (d.length / 4)
  }, shot.toString('base64'))
  expect(blue).toBeGreaterThan(0.4)
})
