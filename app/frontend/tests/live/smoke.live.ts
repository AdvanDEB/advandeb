// Harness smoke check: public pages load, the guard and evidence capture work.
import { test, expect, shot } from './guard'

test.use({ signedIn: false })

test('public: home and login render', async ({ page, evidence }, info) => {
  await page.goto('/')
  await expect(page.locator('#app[data-v-app]')).not.toBeEmpty()
  await shot(page, info, 'smoke-home')
  await page.goto('/login')
  await expect(page.locator('input[type="email"]')).toBeVisible()
  await shot(page, info, 'smoke-login')
  expect(evidence.blocked).toEqual([])
})
