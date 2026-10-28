import { test, expect, type Page } from '@playwright/test'

// A tab opened before a deploy: the next lazy route's chunk is gone (404).
// Before the fix the click did nothing — URL unchanged, no message, and every
// later click failed the same way. On this dev server the route's module is
// /src/views/LoginView.vue; production asks for /assets/LoginView-<hash>.js,
// the same dynamic import through the same router.
const LOGIN_MODULE = /\/src\/views\/LoginView\.vue/

async function setUp(page: Page) {
  await page.route('**/api/auth/config', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"google_oauth_enabled":false}' }))
  await page.route('**/api/users/me', route =>
    route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Not authenticated"}' }))
  const documents: string[] = []
  page.on('request', r => { if (r.resourceType() === 'document') documents.push(new URL(r.url()).pathname) })
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible()
  return documents
}

const gone = { status: 404, contentType: 'text/html', body: '<html><body>404 Not Found</body></html>' }

test('a stale chunk reloads into the page the user asked for', async ({ page }) => {
  const documents = await setUp(page)
  // Only the old tab's request fails; after the reload the module is there.
  await page.route(LOGIN_MODULE, route => route.fulfill(gone), { times: 1 })

  await page.getByRole('link', { name: 'Sign in' }).click()

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.locator('input[type="email"]')).toBeVisible()
  expect(documents).toEqual(['/', '/login'])
})

test('a chunk that stays broken reloads once, then says so', async ({ page }) => {
  const documents = await setUp(page)
  await page.route(LOGIN_MODULE, route => route.fulfill(gone))

  await page.getByRole('link', { name: 'Sign in' }).click()

  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('This page could not be loaded')
  await expect(dialog.getByRole('button', { name: 'Reload' })).toBeVisible()
  // No reload loop: the guard allowed exactly one automatic reload.
  await page.waitForTimeout(1500)
  expect(documents).toEqual(['/', '/login'])
})
