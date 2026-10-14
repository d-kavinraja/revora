/**
 * Accept only same-origin, internal redirect targets (e.g. `/profile`).
 *
 * Used to sanitize a user-controllable `?redirect=` value before it is
 * stored or navigated to, so an attacker-supplied link can never bounce a
 * signed-in user to an external site (open redirect). Rejects absolute URLs,
 * protocol-relative (`//evil.example`), and backslash-smuggled (`/\evil`)
 * prefixes — only a rooted, single-slash path is allowed.
 *
 * Dependency-free on purpose: imported by edge middleware (proxy.ts) as well
 * as client components.
 */
export function isSafeInternalPath(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.startsWith('/') &&
    !value.startsWith('//') &&
    !value.startsWith('/\\')
  );
}
