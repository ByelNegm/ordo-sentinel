export type StatusTone = 'success' | 'warning' | 'danger' | 'neutral'

const success = new Set(['healthy', 'verified', 'resolved', 'passed', 'pass', 'running', 'settled', 'approved', 'completed', 'released', 'remote_validated'])
const warning = new Set(['recovering', 'investigating', 'contained', 'validating', 'awaiting_approval', 'correcting', 'quarantined', 'held', 'pending', 'armed'])
const danger = new Set(['violated', 'blocked', 'rejected', 'failed', 'denied', '403', 'sandbox_rejected', 'discrepancy', 'missing', 'detected', 'fail', 'invalid', 'conflict'])

export function statusTone(value: string | null | undefined): StatusTone {
  const status = value?.trim().toLowerCase().replaceAll(' ', '_') || ''
  if (danger.has(status) || /^http_403\b/.test(status)) return 'danger'
  if (warning.has(status)) return 'warning'
  if (success.has(status)) return 'success'
  return 'neutral'
}

export function auditTone(action: string | null | undefined, detail = ''): StatusTone {
  const value = action?.trim().toLowerCase() || ''
  const tones = value.split('.').map(statusTone)
  if (tones.includes('danger') || (value === 'sandbox.completed' && /passed:\s*false/i.test(detail))) return 'danger'
  if (tones.includes('warning') || value.startsWith('investigation.') || ['sandbox.started', 'recovery.started'].includes(value)) return 'warning'
  return tones.includes('success') ? 'success' : 'neutral'
}

export function guideStepTone(index: number, current: number, status?: string): StatusTone {
  if (current < 0 || index > current) return 'neutral'
  if (index < current || index === 0 || index === 5) return 'success'
  if (index === 1) return 'warning'
  return statusTone(status)
}
