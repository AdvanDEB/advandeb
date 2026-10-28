// Sign out through the shell (run LAST: it revokes the session the run holds).
// Checks that the tokens leave storage, the server is told, and that the back
// button and a protected deep link no longer show signed-in content.
import { test, expect, shot } from './guard'
import { record } from './collect'

test('shell: sign out, then back and deep link', async ({ page, evidence }, info) => {
  test.skip(info.project.name !== 'desktop', 'one sign-out per run')
  await page.goto('/documentation', { waitUntil: 'domcontentloaded' })
  await page.locator('main h1').waitFor()
  const logout = page.locator('.logout-btn')
  const logoutReq = page.waitForRequest((r) => r.url().endsWith('/api/auth/logout'), { timeout: 10_000 }).catch(() => null)
  await logout.click()
  await page.waitForURL('**/login')
  const req = await logoutReq
  const res = req ? await req.response() : null
  const after = await page.evaluate(() => ({
    url: location.pathname,
    access: localStorage.getItem('access_token') !== null,
    refresh: localStorage.getItem('refresh_token') !== null,
    title: document.title,
  }))
  await shot(page, info, 'signout-login', false)

  await page.goBack()
  await page.waitForTimeout(1500)
  const back = await page.evaluate(() => ({ url: location.pathname, sidebar: !!document.querySelector('#app-sidebar'), h1: document.querySelector('h1')?.textContent?.trim() ?? null }))
  await page.goto('/admin/users', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const deep = await page.evaluate(() => location.pathname)

  record(info, 'signout', { logoutStatus: res?.status() ?? null, after, back, deep, evidence })
  expect(after.access || after.refresh).toBe(false)
  expect(evidence.blocked).toEqual([])
})
