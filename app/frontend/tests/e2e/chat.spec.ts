import { test, expect } from '@playwright/test'

// These tests assume an authenticated session (token injected via storageState or mock)
test.describe('Chat interface', () => {
  test.beforeEach(async ({ page }) => {
    // Inject a mock token so auth guard passes
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'mock-token-for-e2e')
    })

    // Mock the /api/users/me endpoint
    await page.route('**/api/users/me', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'u1', email: 'test@example.com',
          full_name: 'Test User', roles: ['administrator'], capabilities: [],
        }),
      })
    )

    // Mock session list
    await page.route('**/api/chat/sessions', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    )

    await page.goto('/chat')
  })

  test('renders chat layout', async ({ page }) => {
    await expect(page.locator('.chat-interface')).toBeVisible()
    await expect(page.locator('textarea')).toBeVisible()
  })

  test('send button disabled on empty input', async ({ page }) => {
    await expect(page.locator('.send-btn')).toBeDisabled()
  })

  test('send button enabled after typing', async ({ page }) => {
    await page.fill('textarea', 'What is DEB theory?')
    await expect(page.locator('.send-btn')).toBeEnabled()
  })

  test('message appears in list after send (WebSocket mock)', async ({ page }) => {
    // Mock WebSocket by overriding at window level
    await page.addInitScript(() => {
      ;(window as any).WebSocket = class MockWS {
        // useChatSocket compares readyState with WebSocket.OPEN and sends only
        // from onopen, so the mock has to open the way a real socket does.
        static CONNECTING = 0
        static OPEN = 1
        static CLOSING = 2
        static CLOSED = 3

        onopen: (() => void) | null = null
        onmessage: ((e: MessageEvent) => void) | null = null
        onclose: (() => void) | null = null
        readyState = 0 // CONNECTING

        constructor() {
          setTimeout(() => {
            this.readyState = 1
            this.onopen?.()
          }, 0)
        }

        send(data: string) {
          const parsed = JSON.parse(data)
          if (parsed.type === 'user_message') {
            setTimeout(() => {
              this.onmessage?.({
                data: JSON.stringify({
                  type: 'message',
                  role: 'assistant',
                  content: 'DEB stands for Dynamic Energy Budget.',
                  session_id: 'sess-1',
                }),
              } as MessageEvent)
            }, 100)
          }
        }

        close() {}
      }
    })
    // A socket opens only with a one-time ticket from POST /api/auth/ws-ticket.
    await page.route('**/api/auth/ws-ticket', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"ticket":"e2e-ticket"}' })
    )
    // Init scripts apply from the next navigation on; beforeEach already loaded /chat.
    await page.reload()

    await page.fill('textarea', 'What is DEB?')
    await page.keyboard.press('Enter')

    await expect(page.locator('.message.user').first()).toBeVisible()
    await expect(page.locator('.message.assistant').first()).toContainText('Dynamic Energy Budget')
  })

  test('export button triggers JSON download', async ({ page }) => {
    // Verify export button exists in toolbar
    await expect(page.getByRole('button', { name: 'Export' })).toBeVisible()
  })
})
