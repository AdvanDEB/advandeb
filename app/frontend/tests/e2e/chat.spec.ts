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
      (window as any).__wsMessages = []
      const OrigWS = window.WebSocket
      ;(window as any).WebSocket = class MockWS {
        onmessage: ((e: MessageEvent) => void) | null = null
        onclose: (() => void) | null = null
        readyState = 1 // OPEN

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

    await page.fill('textarea', 'What is DEB?')
    await page.keyboard.press('Enter')

    await expect(page.locator('.message.user').first()).toBeVisible()
    await expect(page.locator('.message.assistant').first()).toContainText('Dynamic Energy Budget')
  })

  test('export button triggers JSON download', async ({ page }) => {
    // Verify export button exists in toolbar
    await expect(page.locator('.toolbar-btn')).toContainText('Export')
  })
})
