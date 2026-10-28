import { describe, it, expect, beforeEach } from 'vitest'
import { beginGoogleFlow, pkceChallenge, safeRedirect, takeGoogleFlow } from '@/utils/oauth'

describe('safeRedirect', () => {
  it.each([
    ['/kb', '/kb'],
    ['/models/abc?tab=run#x', '/models/abc?tab=run#x'],
    [undefined, '/'],
    [['/kb'], '/'],
    ['https://evil.example/', '/'],
    ['//evil.example/path', '/'],
    ['/\\evil.example', '/'],
    ['javascript:alert(1)', '/'],
    ['/login', '/'],
    ['/login?redirect=/kb', '/'],
  ])('%j → %j', (input, expected) => {
    expect(safeRedirect(input)).toBe(expected)
  })
})

describe('Google flow state', () => {
  beforeEach(() => sessionStorage.clear())

  it('accepts the callback that carries its own state, once', () => {
    const flow = beginGoogleFlow('/kb')
    expect(flow.redirect).toBe('/kb')
    expect(flow.codeVerifier.length).toBeGreaterThanOrEqual(43)

    expect(takeGoogleFlow(flow.state)).toEqual(flow)
    // A state is good for one callback.
    expect(takeGoogleFlow(flow.state)).toBeNull()
  })

  it('refuses a callback with another state (login CSRF), and forgets the flow', () => {
    const flow = beginGoogleFlow('/')
    expect(takeGoogleFlow('attacker-state')).toBeNull()
    expect(takeGoogleFlow(flow.state)).toBeNull()
  })

  it('refuses a callback nobody started', () => {
    expect(takeGoogleFlow('anything')).toBeNull()
  })

  it('never stores an off-site redirect', () => {
    expect(beginGoogleFlow('//evil.example').redirect).toBe('/')
  })
})

describe('pkceChallenge', () => {
  it('matches the S256 example in RFC 7636 appendix B', async () => {
    await expect(pkceChallenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'))
      .resolves.toBe('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
  })
})
