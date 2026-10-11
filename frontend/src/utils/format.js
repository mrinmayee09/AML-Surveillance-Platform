/**
 * Presentation helpers.
 *
 * Two rules enforced here:
 *  1. Risk styling is semantic AND always accompanied by a label/icon, so colour
 *     is never the only carrier of meaning.
 *  2. Money uses Indian numbering (lakh / crore) because that is how an analyst
 *     in this context reads amounts.
 */

import { format, formatDistanceToNowStrict, parseISO } from 'date-fns'

// ---------------------------------------------------------------------------
// Money & numbers
// ---------------------------------------------------------------------------

export function formatInr(value, { compact = true, decimals } = {}) {
  const amount = Number(value ?? 0)
  if (!Number.isFinite(amount)) return '—'
  const sign = amount < 0 ? '-' : ''
  const abs = Math.abs(amount)

  if (compact) {
    if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(decimals ?? 2)} Cr`
    if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(decimals ?? 2)} L`
    if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(decimals ?? 1)} K`
  }
  return `${sign}₹${abs.toLocaleString('en-IN', {
    minimumFractionDigits: decimals ?? 0,
    maximumFractionDigits: decimals ?? 2,
  })}`
}

/** Full precision, for anywhere an exact figure matters (integrity checks). */
export function formatInrExact(value) {
  return formatInr(value, { compact: false, decimals: 2 })
}

export function formatNumber(value, decimals = 0) {
  const n = Number(value ?? 0)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function formatPercent(value, decimals = 1) {
  const n = Number(value ?? 0)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(decimals)}%`
}

export function formatDelta(value) {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

export function formatMultiple(value, decimals = 1) {
  const n = Number(value ?? 0)
  return `${n.toFixed(decimals)}×`
}

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

// ISO date-time with no zone designator ("2026-10-04T04:40:00").
const ZONELESS_DATETIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

/**
 * Parse an API timestamp. The backend sends UTC with an explicit offset; a
 * zone-less string (older stored evidence, legacy rows) is also UTC, so it is
 * never read as the viewer's local time. Display is in the viewer's local zone.
 */
export function toDate(value) {
  if (!value) return null
  if (value instanceof Date) return value
  try {
    const text = typeof value === 'string' ? value.trim() : null
    const parsed =
      text !== null
        ? parseISO(ZONELESS_DATETIME.test(text) ? `${text.replace(' ', 'T')}Z` : text)
        : new Date(value)
    return Number.isNaN(parsed.getTime()) ? null : parsed
  } catch {
    return null
  }
}

export function formatDateTime(value) {
  const date = toDate(value)
  return date ? format(date, 'dd MMM yyyy, HH:mm') : '—'
}

export function formatDate(value) {
  const date = toDate(value)
  return date ? format(date, 'dd MMM yyyy') : '—'
}

export function formatTime(value) {
  const date = toDate(value)
  return date ? format(date, 'HH:mm:ss') : '—'
}

/** Short name of the viewer's time zone, e.g. "IST", for labelling displayed times. */
export function localZoneName(date = new Date()) {
  try {
    return (
      new Intl.DateTimeFormat('en-IN', { timeZoneName: 'short' })
        .formatToParts(date)
        .find((part) => part.type === 'timeZoneName')?.value ?? ''
    )
  } catch {
    return ''
  }
}

export function formatRelative(value) {
  const date = toDate(value)
  if (!date) return '—'
  return `${formatDistanceToNowStrict(date)} ago`
}

// ---------------------------------------------------------------------------
// Risk semantics
// ---------------------------------------------------------------------------

/**
 * Canonical style + copy for each risk band.
 * `action` states what the platform does at that band, so the meaning of the
 * colour is always spelled out in words next to it.
 */
export const RISK_META = {
  LOW: {
    label: 'Low',
    action: 'Allow',
    text: 'text-risk-low',
    bg: 'bg-risk-lowBg',
    border: 'border-risk-low/35',
    dot: 'bg-risk-low',
    chart: '#22a06b',
  },
  MEDIUM: {
    label: 'Medium',
    action: 'Monitor / verify',
    text: 'text-risk-medium',
    bg: 'bg-risk-mediumBg',
    border: 'border-risk-medium/35',
    dot: 'bg-risk-medium',
    chart: '#d99524',
  },
  HIGH: {
    label: 'High',
    action: 'Review / hold',
    text: 'text-risk-high',
    bg: 'bg-risk-highBg',
    border: 'border-risk-high/35',
    dot: 'bg-risk-high',
    chart: '#e0533d',
  },
  CRITICAL: {
    label: 'Critical',
    action: 'Block / escalate',
    text: 'text-risk-critical',
    bg: 'bg-risk-criticalBg',
    border: 'border-risk-critical/45',
    dot: 'bg-risk-critical',
    chart: '#c02a3f',
  },
}

export const NEUTRAL_META = {
  label: 'Unknown',
  action: '',
  text: 'text-slateish-300',
  bg: 'bg-ink-800',
  border: 'border-ink-600',
  dot: 'bg-slateish-400',
  chart: '#8b9ab5',
}

export function riskMeta(level) {
  return RISK_META[String(level || '').toUpperCase()] || NEUTRAL_META
}

export function riskColor(level) {
  return riskMeta(level).chart
}

/** Colour a 0-100 score using the same thresholds the backend applies. */
export function scoreMeta(score, thresholds = { medium: 35, high: 60, critical: 85 }) {
  const value = Number(score ?? 0)
  if (value >= thresholds.critical) return RISK_META.CRITICAL
  if (value >= thresholds.high) return RISK_META.HIGH
  if (value >= thresholds.medium) return RISK_META.MEDIUM
  return RISK_META.LOW
}

// ---------------------------------------------------------------------------
// Status semantics
// ---------------------------------------------------------------------------

export const STATUS_META = {
  // Alerts
  NEW: { label: 'New', text: 'text-info', bg: 'bg-info-soft', border: 'border-info/35' },
  UNDER_REVIEW: {
    label: 'Under review',
    text: 'text-risk-medium',
    bg: 'bg-risk-mediumBg',
    border: 'border-risk-medium/35',
  },
  ESCALATED: {
    label: 'Escalated',
    text: 'text-risk-high',
    bg: 'bg-risk-highBg',
    border: 'border-risk-high/35',
  },
  CLEARED: {
    label: 'Cleared',
    text: 'text-risk-low',
    bg: 'bg-risk-lowBg',
    border: 'border-risk-low/35',
  },
  CONFIRMED_SUSPICIOUS: {
    label: 'Confirmed suspicious',
    text: 'text-risk-critical',
    bg: 'bg-risk-criticalBg',
    border: 'border-risk-critical/45',
  },
  // Investigations
  OPEN: { label: 'Open', text: 'text-info', bg: 'bg-info-soft', border: 'border-info/35' },
  IN_PROGRESS: {
    label: 'In progress',
    text: 'text-risk-medium',
    bg: 'bg-risk-mediumBg',
    border: 'border-risk-medium/35',
  },
  PENDING_APPROVAL: {
    label: 'Pending approval',
    text: 'text-accent',
    bg: 'bg-accent-soft',
    border: 'border-accent/35',
  },
  CLOSED_CLEARED: {
    label: 'Closed - cleared',
    text: 'text-risk-low',
    bg: 'bg-risk-lowBg',
    border: 'border-risk-low/35',
  },
  CLOSED_REPORTED: {
    label: 'Closed - reported',
    text: 'text-risk-critical',
    bg: 'bg-risk-criticalBg',
    border: 'border-risk-critical/45',
  },
  // Transactions
  COMPLETED: {
    label: 'Completed',
    text: 'text-risk-low',
    bg: 'bg-risk-lowBg',
    border: 'border-risk-low/35',
  },
  PENDING: {
    label: 'Pending',
    text: 'text-slateish-300',
    bg: 'bg-ink-800',
    border: 'border-ink-600',
  },
  HELD: {
    label: 'Held',
    text: 'text-risk-medium',
    bg: 'bg-risk-mediumBg',
    border: 'border-risk-medium/35',
  },
  BLOCKED: {
    label: 'Blocked',
    text: 'text-risk-critical',
    bg: 'bg-risk-criticalBg',
    border: 'border-risk-critical/45',
  },
  REVERSED: {
    label: 'Reversed',
    text: 'text-slateish-300',
    bg: 'bg-ink-800',
    border: 'border-ink-600',
  },
  // Orders
  AWAITING_PAYMENT: {
    label: 'Awaiting payment',
    text: 'text-info',
    bg: 'bg-info-soft',
    border: 'border-info/35',
  },
  PAID: {
    label: 'Paid',
    text: 'text-risk-low',
    bg: 'bg-risk-lowBg',
    border: 'border-risk-low/35',
  },
  INTEGRITY_FAILED: {
    label: 'Integrity failed',
    text: 'text-risk-critical',
    bg: 'bg-risk-criticalBg',
    border: 'border-risk-critical/45',
  },
}

export function statusMeta(status) {
  return (
    STATUS_META[String(status || '').toUpperCase()] || {
      label: humanise(status),
      text: 'text-slateish-300',
      bg: 'bg-ink-800',
      border: 'border-ink-600',
    }
  )
}

export const DECISION_META = {
  ALLOW: { label: 'Allow', ...RISK_META.LOW },
  MONITOR: { label: 'Monitor', ...RISK_META.MEDIUM },
  REVIEW: { label: 'Review', ...RISK_META.HIGH },
  BLOCK: { label: 'Block', ...RISK_META.CRITICAL },
}

export function decisionMeta(decision) {
  return DECISION_META[String(decision || '').toUpperCase()] || NEUTRAL_META
}

export const PATTERN_LABELS = {
  CIRCULAR: 'Circular movement',
  LAYERED: 'Layered movement',
  FAN_OUT: 'Fan-out dispersion',
  FAN_IN: 'Fan-in convergence',
  SMURFING: 'Structuring / smurfing',
  PASS_THROUGH: 'Pass-through',
  NORMAL: 'No typology matched',
}

export function patternLabel(pattern) {
  return PATTERN_LABELS[String(pattern || '').toUpperCase()] || humanise(pattern)
}

export const ENTITY_LABELS = {
  CUSTOMER: 'Customer',
  ACCOUNT: 'Account',
  MERCHANT: 'Merchant',
  COMPANY: 'Company',
  WALLET: 'Wallet',
  BENEFICIARY: 'Beneficiary',
}

export function entityLabel(type) {
  return ENTITY_LABELS[String(type || '').toUpperCase()] || humanise(type)
}

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------

export function humanise(value) {
  if (!value) return '—'
  return String(value)
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/^\w/, (c) => c.toUpperCase())
}

export function truncate(value, length = 120) {
  const text = String(value ?? '')
  return text.length > length ? `${text.slice(0, length - 1)}…` : text
}

export function initials(name) {
  return String(name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}
