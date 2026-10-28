// Deep links to protected routes while signed out: where the visitor lands,
// whether the intended destination survives (in the URL and across a reload),
// and that nothing protected is requested — no API call beyond the public
// ones, no protected view's code — before the redirect.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect, shot } from './guard'

test.use({ signedIn: false })

const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'

function record(project: string, name: string, data: unknown) {
  const dir = path.join(OUT, 'data', project)
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, `${name}.json`), JSON.stringify(data, null, 2))
}

const DEEP_LINKS = ['/chat', '/kb', '/admin/users', '/models/abc', '/settings/llm-keys', '/elicitation', '/documents?page=2']

/** Public endpoints an anonymous page may call. */
const PUBLIC_API = new Set(['/api/auth/config', '/api/enrolment/categories'])

/** View chunks that only a signed-in visitor should ever download. */
const PROTECTED_CHUNK = /\/assets\/(ChatView|KnowledgeBuilderView|AdminUsersView|AdminExpertsView|AdminUserChatsView|ModelsView|ModelsLibraryView|LLMKeysView|ElicitationView|DocumentsView|FactsView|DocumentationView|PrivacySettingsView|plotly-vendor)-/

test('signed out: protected deep links redirect to login', async ({ page, evidence }, info) => {
  const requests: string[] = []
  page.on('request', (r) => {
    const u = new URL(r.url())
    if (u.hostname.endsWith('advandeb.com')) requests.push(`${r.method()} ${u.pathname}`)
  })

  const results = []
  for (const link of DEEP_LINKS) {
    requests.length = 0
    await page.goto(link, { waitUntil: 'networkidle' })
    await page.locator('input[type="email"]').waitFor()
    const state = await page.evaluate(() => {
      const host = document.querySelector('#app') as unknown as { __vue_app__?: { config: { globalProperties: { $router: { currentRoute: { value: { fullPath: string; redirectedFrom?: { fullPath: string } } } } } } } }
      const route = host.__vue_app__?.config.globalProperties.$router.currentRoute.value
      return {
        url: location.pathname + location.search,
        title: document.title,
        redirectedFrom: route?.redirectedFrom?.fullPath ?? null,
        notice: document.querySelector('.login')?.textContent?.replace(/\s+/g, ' ').trim().slice(0, 160) ?? null,
      }
    })
    const api = requests.filter((r) => r.includes(' /api/') || r.includes(' /ws/'))
    results.push({
      link,
      ...state,
      apiCalls: api,
      unexpectedApi: api.filter((r) => !PUBLIC_API.has(r.split(' ')[1])),
      protectedChunks: requests.filter((r) => PROTECTED_CHUNK.test(r)),
    })
  }
  await shot(page, info, 'redirect-login-from-documents')

  // Does the destination survive a reload of the login page?
  await page.goto('/chat', { waitUntil: 'networkidle' })
  await page.locator('input[type="email"]').waitFor()
  await page.reload({ waitUntil: 'networkidle' })
  await page.locator('input[type="email"]').waitFor()
  const afterReload = await page.evaluate(() => {
    const host = document.querySelector('#app') as unknown as { __vue_app__?: { config: { globalProperties: { $router: { currentRoute: { value: { redirectedFrom?: { fullPath: string } } } } } } } }
    return {
      url: location.pathname + location.search,
      redirectedFrom: host.__vue_app__?.config.globalProperties.$router.currentRoute.value.redirectedFrom?.fullPath ?? null,
    }
  })

  // The explicit form the app itself uses after a 401 (utils/authRefresh.ts).
  await page.goto('/login?redirect=%2Fchat', { waitUntil: 'networkidle' })
  const explicit = await page.evaluate(() => location.pathname + location.search)

  record(info.project.name, 'protected-redirects', { results, afterReload, explicit })
  expect(evidence.blocked, 'the review must not send anything').toEqual([])
  for (const r of results) {
    expect.soft(r.url.startsWith('/login'), `${r.link} should land on /login`).toBe(true)
    expect.soft(r.unexpectedApi, `${r.link}: protected API calls before redirect`).toEqual([])
    expect.soft(r.protectedChunks, `${r.link}: protected view code fetched`).toEqual([])
  }
})
