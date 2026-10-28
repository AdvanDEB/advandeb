// The one permitted form submission of the unauthenticated pass: a single
// sign-in with an address that cannot exist, to see the failure state. Runs
// on the desktop project only, and only with LIVE_FAKE_LOGIN=1, so a routine
// run sends none and an opted-in run exactly one login request.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect, shot } from './guard'

test.use({ signedIn: false })

const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'

test('login: failure state for an unknown account (one attempt)', async ({ page, evidence }, info) => {
  test.skip(info.project.name !== 'desktop', 'one attempt per run, on desktop only')
  test.skip(process.env.LIVE_FAKE_LOGIN !== '1', 'sends a real (failing) login request; opt in with LIVE_FAKE_LOGIN=1')

  await page.goto('/login', { waitUntil: 'networkidle' })
  await page.locator('#email').fill('reviewer-nonexistent@example.com')
  await page.locator('#password').fill('not-a-real-password-review')

  const responseP = page.waitForResponse((r) => r.url().endsWith('/api/auth/login'))
  await page.locator('#password').press('Enter')
  const res = await responseP
  const error = page.locator('.login .error')
  await expect(error).toBeVisible()

  const state = await page.evaluate(() => {
    const err = document.querySelector('.login .error')
    const active = document.activeElement as HTMLElement | null
    return {
      errorText: err?.textContent?.trim() ?? null,
      errorRole: err?.getAttribute('role') ?? null,
      errorLive: err?.closest('[aria-live]')?.getAttribute('aria-live') ?? null,
      emailInvalid: document.querySelector('#email')?.getAttribute('aria-invalid') ?? null,
      describedBy: document.querySelector('#email')?.getAttribute('aria-describedby') ?? null,
      active: active ? `${active.tagName.toLowerCase()}${active.id ? '#' + active.id : ''}` : null,
      passwordKept: (document.querySelector('#password') as HTMLInputElement | null)?.value.length ?? 0,
    }
  })
  await shot(page, info, 'login-error', false)

  const dir = path.join(OUT, 'data', info.project.name)
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, 'login-error.json'), JSON.stringify({
    status: res.status(),
    body: (await res.text()).slice(0, 200),
    ...state,
  }, null, 2))

  expect(evidence.blocked).toEqual([])
})
