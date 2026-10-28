// Harness check for the signed-in path: the seeded session is accepted and the
// app does not bounce to /login. Prints roles (not secret) for the reviewer.
import { test, expect } from './guard'

test('signed in: protected route renders', async ({ page, liveSession, evidence }) => {
  await page.goto('/documentation')
  await expect(page).not.toHaveURL(/\/login/)
  console.log('roles:', liveSession?.user.roles.join(','), 'capabilities:', liveSession?.user.capabilities.join(','))
  expect(evidence.blocked).toEqual([])
})
