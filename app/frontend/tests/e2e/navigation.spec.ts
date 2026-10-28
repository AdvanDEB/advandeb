import { test, expect, type Page } from '@playwright/test'

// Every route used to share one document.title, and after a client-side
// navigation focus fell to <body>, so a keyboard or screen-reader user got no
// sign that the page had changed (F-006, WCAG 2.4.2 / 2.4.3).
async function signedOut(page: Page) {
  await page.route('**/api/auth/config', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"google_oauth_enabled":false}' }))
  await page.route('**/api/users/me', route =>
    route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Not authenticated"}' }))
}

const focused = (page: Page) => page.evaluate(() => {
  const el = document.activeElement
  return { tag: el?.tagName.toLowerCase(), text: el?.textContent?.trim() }
})

test.beforeEach(async ({ page }) => signedOut(page))

test('first load: home keeps its full title and focus is not moved', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible()
  await expect(page).toHaveTitle('AdvanDEB — Knowledge Graph for DEB Biology')
  expect((await focused(page)).tag).toBe('body')
})

test('keyboard: Sign in from home lands on the login heading with its own title', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: 'Sign in' }).focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page).toHaveTitle('Sign in · AdvanDEB')
  await expect.poll(() => focused(page)).toEqual({ tag: 'h1', text: 'Sign in to AdvanDEB' })
})

test('404 → Go to Home moves focus to the home heading', async ({ page }) => {
  await page.goto('/no/such/page')
  await expect(page).toHaveTitle('Page not found · AdvanDEB')
  await page.getByRole('link', { name: 'Go to Home' }).focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/$/)
  await expect(page).toHaveTitle('AdvanDEB — Knowledge Graph for DEB Biology')
  await expect.poll(async () => (await focused(page)).tag).toBe('h1')
})

test('signed in: the sidebar lands on the heading, or on <main> with an announcement', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('access_token', 'mock-token-for-e2e'))
  await page.route('**/api/users/me', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 'u1', email: 'test@example.com', full_name: 'Test User', roles: ['administrator'], capabilities: [] }),
    }))
  await page.route('**/api/chat/sessions', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(nav).toBeVisible()

  await nav.getByRole('link', { name: 'Docs' }).click()
  await expect(page).toHaveTitle('Documentation · AdvanDEB')
  await expect.poll(() => focused(page)).toEqual({ tag: 'h1', text: 'Documentation' })

  // The chat view's heading is visually hidden (F-030); it still takes focus.
  await nav.getByRole('link', { name: 'Chat' }).click()
  await expect(page).toHaveTitle('Chat · AdvanDEB')
  await expect.poll(() => focused(page)).toEqual({ tag: 'h1', text: 'Chat' })

  // (A view with no <h1> - focus on <main> plus an announcement - is covered in
  // src/tests/routeFocus.test.ts.)

  // Signed in, the 404 renders inside AppLayout's <main>: still one landmark.
  await page.goto('/no/such/page')
  await expect(page.locator('h1')).toHaveText('Page not found')
  await expect(page.getByRole('main')).toHaveCount(1)
})
