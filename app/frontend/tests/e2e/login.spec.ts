import { test, expect } from '@playwright/test'

test.describe('Login page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login')
  })

  test('displays login form', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Sign in')
    await expect(page.locator('input[type="email"]')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toBeVisible()
    await expect(page.locator('button[type="submit"]')).toBeVisible()
  })

  test('shows error on invalid credentials', async ({ page }) => {
    await page.fill('input[type="email"]', 'bad@example.com')
    await page.fill('input[type="password"]', 'wrongpass')
    await page.click('button[type="submit"]')
    await expect(page.locator('.error')).toBeVisible()
  })

  test('submit button disabled while loading', async ({ page }) => {
    await page.fill('input[type="email"]', 'user@example.com')
    await page.fill('input[type="password"]', 'password')

    // Intercept the API to stall
    await page.route('**/api/auth/login', (route) =>
      new Promise((resolve) => setTimeout(() => resolve(route.abort()), 500))
    )

    await page.click('button[type="submit"]')
    await expect(page.locator('button[type="submit"]')).toBeDisabled()
  })
})

// Public pages, signed out: F-009, F-013, F-014, F-020, F-021, F-022, F-023.
test.describe('Public pages (signed out)', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/auth/config', r =>
      r.fulfill({ status: 200, contentType: 'application/json', body: '{"google_oauth_enabled":false}' }))
    await page.route('**/api/users/me', r =>
      r.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Not authenticated"}' }))
  })

  test('a failed sign-in is announced and tied to the fields', async ({ page }) => {
    await page.route('**/api/auth/login', r =>
      r.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Invalid email or password"}' }))
    await page.goto('/login')
    await page.fill('input[type="email"]', 'bad@example.com')
    await page.fill('input[type="password"]', 'wrong')
    await page.click('button[type="submit"]')
    const alert = page.getByRole('alert')
    await expect(alert).toHaveText('Invalid email or password.')
    for (const field of ['#email', '#password']) {
      await expect(page.locator(field)).toHaveAttribute('aria-invalid', 'true')
      await expect(page.locator(field)).toHaveAttribute('aria-describedby', 'login-error')
    }
  })

  test('a protected link keeps its destination in the URL, across a reload', async ({ page }) => {
    await page.goto('/documents')
    await expect(page).toHaveURL(/\/login\?redirect=(%2F|\/)documents$/)
    await page.reload()
    await expect(page.getByText('Sign in to continue to that page.')).toBeVisible()

    await page.route('**/api/auth/login', r => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' }),
    }))
    await page.unroute('**/api/users/me')
    await page.route('**/api/users/me', r => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ id: 'u1', email: 'u@example.org', full_name: 'U', roles: ['knowledge_explorator'], capabilities: [] }),
    }))
    await page.route('**/api/documents/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
    await page.fill('input[type="email"]', 'u@example.org')
    await page.fill('input[type="password"]', 'pw')
    await page.click('button[type="submit"]')
    await expect(page).toHaveURL(/\/documents$/)
  })

  test('inputs show a focus ring and use the page font; there is a way home', async ({ page }) => {
    await page.goto('/login')
    await page.locator('#email').focus()
    const style = await page.locator('#email').evaluate(el => {
      const cs = getComputedStyle(el)
      return { outline: cs.outlineStyle, width: cs.outlineWidth, font: cs.fontFamily, body: getComputedStyle(document.body).fontFamily }
    })
    expect(style.outline).toBe('solid')
    expect(style.width).toBe('2px')
    expect(style.font).toBe(style.body)
    expect(style.body).toContain('Segoe UI')     // dialogs teleported to <body> get it too
    await expect(page.getByRole('link', { name: '← AdvanDEB home' })).toHaveAttribute('href', '/')
  })

  for (const path of ['/', '/login', '/no/such/page']) {
    test(`${path} has exactly one <main> landmark`, async ({ page }) => {
      await page.goto(path)
      await expect(page.locator('h1')).toBeVisible()
      await expect(page.getByRole('main')).toHaveCount(1)
    })
  }

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })
    test('sign-in controls are at least 44px tall', async ({ page }) => {
      await page.goto('/login')
      for (const sel of ['#email', '#password', 'button[type="submit"]']) {
        const box = (await page.locator(sel).boundingBox())!
        expect(box.height, sel).toBeGreaterThanOrEqual(44)
      }
    })
  })
})
