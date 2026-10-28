/**
 * Display formatting shared across views.
 *
 * There used to be nine private `formatDate` copies, three `fmtSize` and two
 * `fmtNum`. Most wrapped `new Date(x).toLocaleDateString()` in a try/catch that
 * could never fire — an unparseable string yields "Invalid Date", it does not
 * throw — so a bad timestamp rendered as the words "Invalid Date". These check
 * validity instead.
 */

function parse(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

/** Locale date, e.g. "28/10/2026". `fallback` for a missing or unparseable value. */
export function formatDate(value: string | number | Date | null | undefined, fallback = ''): string {
  const d = parse(value)
  return d ? d.toLocaleDateString() : fallback
}

/** Locale date and time. */
export function formatDateTime(value: string | number | Date | null | undefined, fallback = ''): string {
  const d = parse(value)
  return d ? d.toLocaleString() : fallback
}

/** "Just now", "5m ago", "3h ago", then a locale date. */
export function formatRelativeTime(
  value: string | number | Date | null | undefined,
  now: number = Date.now(),
): string {
  const d = parse(value)
  if (!d) return ''
  const diffMin = Math.floor((now - d.getTime()) / 60000)
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  return d.toLocaleDateString()
}

/** 512 B, 1.5 KB, 3.2 MB, 1.1 GB. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

/** Compact count: 950, 1.2k, 3.4M. */
export function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k'
  return String(n)
}
