// Signed in (the reviewer's account): each main route rendered and looked at —
// screenshot, axe, overflow, metadata, what it downloaded and called, small
// touch targets, unlabelled fields, Tab order. Look only: nothing is clicked.
// Admin pages list other people; their text is not recorded (screenshots stay
// under $LIVE_OUT, outside the repository). /elicitation and /admin/experts
// are being redesigned elsewhere: signedin-elicitation.live.ts only checks
// them for blockers.
import { test, expect, shot, axe, overflow } from './guard'
import { markFirstHeading, open, pageData, record, tabWalk } from './collect'

const ROUTES: { name: string; path: (self: string) => string; personal?: boolean }[] = [
  { name: 'home', path: () => '/' },
  { name: 'documentation', path: () => '/documentation' },
  { name: 'chat', path: () => '/chat' },
  { name: 'facts', path: () => '/facts' },
  { name: 'documents', path: () => '/documents' },
  { name: 'models-library', path: () => '/models' },
  { name: 'llm-keys', path: () => '/settings/llm-keys' },
  { name: 'privacy', path: () => '/settings/privacy' },
  { name: 'admin-users', path: () => '/admin/users', personal: true },
  // Only the reviewer's own chats, never another user's.
  { name: 'admin-own-chats', path: (self) => `/admin/users/${self}/chats`, personal: true },
  { name: 'notfound-signed-in', path: () => '/no-such-page-signed-in' },
]

for (const r of ROUTES) {
  test(`signed in: ${r.name}`, async ({ page, evidence, liveSession }, info) => {
    const self = liveSession!.user.id
    await markFirstHeading(page)
    await open(page, r.path(self))
    // A little longer for views that fill in after their first request.
    await page.waitForTimeout(1500)

    const phone = info.project.name === 'phone'
    const data = await pageData(page, { personal: r.personal, phone })
    const ov = await overflow(page)
    const violations = await axe(page, info, `axe-${r.name}`)
    const screenshot = await shot(page, info, r.name)
    await shot(page, info, `${r.name}-fold`, false)
    const stops = phone ? [] : await tabWalk(page, 30, r.personal)

    record(info, r.name, {
      ...data,
      overflow: { scrollWidth: ov.scrollWidth, viewport: ov.viewport, offenders: ov.offenders.slice(0, 8) },
      axe: violations,
      tabStops: stops,
      screenshot,
      evidence: {
        console: evidence.console.map((c) => ({ ...c, text: c.text.replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '<email>') })),
        pageErrors: evidence.pageErrors,
        failed: evidence.failed,
        slow: evidence.slow,
        blocked: evidence.blocked,
      },
    })

    expect(page.url()).not.toMatch(/\/login/)
    // Look only: a blocked request here means the page itself sends one on
    // load, which the findings report as a harness artifact (or a bug).
    expect.soft(evidence.blocked).toEqual([])
  })
}
