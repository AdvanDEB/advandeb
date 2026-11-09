/**
 * Who may open what — one definition for the router guard, the sidebar and
 * the Home cards.
 *
 * These checks were copied into router/index.ts, AppLayout.vue and
 * HomeView.vue, and the copies had already drifted: the sidebar hid
 * Elicitation from users without the capability while the route let them in,
 * and Home showed the Knowledge Graph card to everyone while the route bounced
 * non-curators back to Home without a word. The router enforces; the sidebar
 * and Home only present — but they have to agree, or a link leads nowhere.
 */

/** Anything with the role/capability shape of the auth store's user. */
export interface AccessSubject {
  roles?: string[] | null
  capabilities?: string[] | null
}

export const KB_ROLES = ['administrator', 'knowledge_curator'] as const

/**
 * Prefixes an external contributor may visit. They hold the elicitation
 * capability and nothing else (advandeb_methods/docs/10 §4.1).
 */
export const EXTERNAL_ALLOWED_PREFIXES = ['/elicitation', '/settings', '/login'] as const

/** The 2026Workshop wiki, and its first address (which redirects to it). */
export const WORKSHOP_PREFIXES = ['/2026Workshop', '/wiki'] as const
export const CAP_WORKSHOP = 'workshop_2026'

function roles(u: AccessSubject | null | undefined): string[] {
  return u?.roles ?? []
}

export function hasRole(u: AccessSubject | null | undefined, role: string): boolean {
  return roles(u).includes(role)
}

export function isAdmin(u: AccessSubject | null | undefined): boolean {
  return hasRole(u, 'administrator')
}

/** Administrators and knowledge curators — the backend's require_curator. */
export function isCurator(u: AccessSubject | null | undefined): boolean {
  return KB_ROLES.some(r => hasRole(u, r))
}

/** The Knowledge Builder (/kb) is curator-only. */
export function canUseKnowledgeBuilder(u: AccessSubject | null | undefined): boolean {
  return isCurator(u)
}

/**
 * Elicitation follows the capability, not a role: the DEB experts who give
 * the judgments hold knowledge_explorator only. Mirrors the backend's
 * require_capability('sf_elicitation') (app/core/dependencies.py): curators,
 * admins and external contributors always may. Leaving the external role out
 * would also send an external-only account round the guard forever — it is
 * confined to /elicitation, which would then bounce it home.
 */
export function canElicit(u: AccessSubject | null | undefined): boolean {
  return (u?.capabilities ?? []).includes('sf_elicitation')
    || canUseKnowledgeBuilder(u)
    || hasRole(u, 'external_contributor')
}

/** An account whose every role is external_contributor. */
export function isExternalOnly(u: AccessSubject | null | undefined): boolean {
  const r = roles(u)
  return r.length > 0 && r.every(x => x === 'external_contributor')
}

/**
 * The 2026Workshop wiki is for the experts who were at the workshop: an
 * administrator grants it per account (Admin › Experts), and new accounts start
 * without it. Mirrors the backend's require_workshop (app/core/dependencies.py).
 */
export function canSeeWorkshop(u: AccessSubject | null | undefined): boolean {
  return isAdmin(u) || (u?.capabilities ?? []).includes(CAP_WORKSHOP)
}

const under = (path: string, prefixes: readonly string[]) =>
  prefixes.some(p => path === p || path.startsWith(p + '/'))

/**
 * `path` is a route path (no query string). An external contributor granted the
 * workshop may open it too, as the backend lets them reach /api/wiki.
 */
export function isAllowedForExternal(path: string, u?: AccessSubject | null): boolean {
  return under(path, EXTERNAL_ALLOWED_PREFIXES) || (canSeeWorkshop(u) && under(path, WORKSHOP_PREFIXES))
}
