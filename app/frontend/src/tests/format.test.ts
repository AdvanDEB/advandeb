import { describe, it, expect } from 'vitest'
import { formatBytes, formatCount, formatDate, formatDateTime, formatRelativeTime } from '@/utils/format'

describe('format', () => {
  it('formatDate handles missing and unparseable values instead of printing "Invalid Date"', () => {
    expect(formatDate(undefined)).toBe('')
    expect(formatDate(null, '—')).toBe('—')
    expect(formatDate('not a date', '—')).toBe('—')
    expect(formatDate('2026-10-28T10:00:00Z')).toBe(new Date('2026-10-28T10:00:00Z').toLocaleDateString())
  })

  it('formatDateTime includes the time', () => {
    const iso = '2026-10-28T10:00:00Z'
    expect(formatDateTime(iso)).toBe(new Date(iso).toLocaleString())
    expect(formatDateTime('')).toBe('')
  })

  it('formatRelativeTime', () => {
    const now = Date.parse('2026-10-28T12:00:00Z')
    expect(formatRelativeTime('2026-10-28T11:59:40Z', now)).toBe('Just now')
    expect(formatRelativeTime('2026-10-28T11:15:00Z', now)).toBe('45m ago')
    expect(formatRelativeTime('2026-10-28T07:00:00Z', now)).toBe('5h ago')
    expect(formatRelativeTime('garbage', now)).toBe('')
  })

  it('formatBytes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
    expect(formatBytes(3 * 1024 ** 3)).toBe('3.0 GB')
    expect(formatBytes(undefined)).toBe('—')
  })

  it('formatCount', () => {
    expect(formatCount(950)).toBe('950')
    expect(formatCount(1234)).toBe('1.2k')
    expect(formatCount(3_400_000)).toBe('3.4M')
    expect(formatCount(undefined)).toBe('—')
  })
})
