/**
 * Sign-in helpers: where to go after login, and the Google OAuth `state` and
 * PKCE values that bind an authorization response to the request that asked
 * for it.
 */

/**
 * The in-app path to return to after signing in, or `/`.
 *
 * Only a same-origin path is accepted: `//evil.example` and `/\evil.example`
 * are protocol-relative URLs to a browser, so taking `?redirect=` at face
 * value would make the login page an open redirect.
 */
export function safeRedirect(target: unknown): string {
  if (typeof target !== 'string' || !target.startsWith('/')) return '/'
  if (target.startsWith('//') || target.startsWith('/\\')) return '/'
  if (target === '/login' || target.startsWith('/login?') || target.startsWith('/login/')) return '/'
  return target
}

function base64url(bytes: Uint8Array): string {
  let binary = ''
  for (const b of bytes) binary += String.fromCharCode(b)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomToken(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength)
  crypto.getRandomValues(bytes)
  return base64url(bytes)
}

export interface GoogleFlow {
  /** Echoed back by Google; a callback whose state differs is not ours. */
  state: string
  /** PKCE secret, sent only with the code exchange. */
  codeVerifier: string
  /** Where to land after sign-in. */
  redirect: string
}

const FLOW_KEY = 'oauth_google_flow'

/** S256 PKCE challenge for a verifier (RFC 7636 §4.2). */
export async function pkceChallenge(codeVerifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(codeVerifier))
  return base64url(new Uint8Array(digest))
}

/**
 * Start a Google flow: fresh state and verifier, kept in sessionStorage — the
 * tab that started the flow is the one the callback lands in, and nothing
 * else should be able to read it.
 */
export function beginGoogleFlow(redirect: string): GoogleFlow {
  const flow: GoogleFlow = {
    state: randomToken(),
    codeVerifier: randomToken(48),
    redirect: safeRedirect(redirect),
  }
  sessionStorage.setItem(FLOW_KEY, JSON.stringify(flow))
  return flow
}

/**
 * Finish a Google flow: the stored flow if `state` matches it, else null.
 * Either way the stored flow is consumed — a state is good for one callback.
 */
export function takeGoogleFlow(state: string | null): GoogleFlow | null {
  const raw = sessionStorage.getItem(FLOW_KEY)
  sessionStorage.removeItem(FLOW_KEY)
  if (!raw || !state) return null
  try {
    const flow = JSON.parse(raw) as GoogleFlow
    return flow.state === state ? flow : null
  } catch {
    return null
  }
}
