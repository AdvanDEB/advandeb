import { test, expect } from '@playwright/test'

test.describe('Login page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login')
  })

  test('displays login form', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Login')
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
