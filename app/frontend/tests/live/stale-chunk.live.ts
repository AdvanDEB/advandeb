// What a visitor with the app open sees after a deploy. A rebuild replaces
// every hashed chunk, and nginx answers the old names with 404 — so the next
// lazy route the open tab needs cannot load. Simulated in the browser only:
// the LoginView chunk request is answered locally with the same 404 nginx
// gives for a removed asset. Nothing reaches the server.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect, shot } from './guard'

test.use({ signedIn: false })

const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'

test('stale tab: a lazy route whose chunk is gone after a deploy', async ({ page, evidence }, info) => {
  test.skip(info.project.name !== 'desktop', 'behaviour is viewport-independent')

  await page.goto('/', { waitUntil: 'networkidle' })
  await expect(page.locator('h1')).toBeVisible()

  await page.route(/\/assets\/LoginView-[^/]+\.(js|css)$/, (route) =>
    route.fulfill({ status: 404, contentType: 'text/html', body: '<html><body>404 Not Found</body></html>' }))

  await page.getByRole('link', { name: 'Sign in' }).click()
  await page.waitForTimeout(2500)

  const state = await page.evaluate(() => ({
    url: location.pathname,
    h1: document.querySelector('h1')?.textContent?.trim() ?? null,
    loginFormShown: !!document.querySelector('input[type="email"]'),
  }))
  // A second click: does anything recover without a manual reload?
  await page.getByRole('link', { name: 'Sign in' }).click().catch(() => {})
  await page.waitForTimeout(1500)
  const second = await page.evaluate(() => ({ url: location.pathname, loginFormShown: !!document.querySelector('input[type="email"]') }))
  await shot(page, info, 'stale-chunk-after-click', false)

  const dir = path.join(OUT, 'data', info.project.name)
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, 'stale-chunk.json'), JSON.stringify({
    state, second, console: evidence.console, pageErrors: evidence.pageErrors,
  }, null, 2))
  expect(evidence.blocked).toEqual([])
})
