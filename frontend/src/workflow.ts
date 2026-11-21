import type { Incident, Overview } from './types'

export const workflowSteps = [
  { title: 'Healthy bank', caption: 'Start live traffic' },
  { title: 'Inject fault', caption: 'Choose a fault to inject' },
  { title: 'Detected & contained', caption: 'Review the evidence' },
  { title: 'Sandbox validated', caption: 'Optionally test an unsafe correction, then approve' },
  { title: 'Approved & corrected', caption: 'Authorized correction and reconciliation' },
  { title: 'Verified', caption: 'Release settlement-svc' },
]

export function deriveWorkflow(overview: Overview | null, incident?: Incident) {
  if (!overview) return { index: -1, section: 'bank', target: '', action: 'Connecting to backend', caption: 'Waiting for live bank state' }
  if (incident && ['failed', 'rejected'].includes(incident.status)) {
    return { index: workflowSteps.length, terminal: incident.status, section: 'simulator', target: '[data-action="reset"]', action: 'Reset baseline', caption: 'Reset the bank to start again' }
  }
  if (incident?.status === 'resolved' && incident.verification?.checks.length === 7 && incident.verification.checks.every(check => check.pass)) {
    const quarantined = overview.services[0]?.status === 'quarantined'
    return { index: 5, section: quarantined ? 'verification' : 'simulator', target: quarantined ? '[data-action="release"]' : '[data-action="reset"]', action: quarantined ? 'Release settlement-svc' : 'Reset baseline', caption: quarantined ? '7/7 verified. Release the service to settle held payments.' : 'Service released. Reset baseline to repeat the demo.' }
  }
  if (incident?.status === 'correcting') return { index: 4, section: 'verification', target: '#verification .section-title', action: 'View correction progress', caption: 'Human approval accepted. Applying and verifying the correction.' }
  if (incident?.status === 'awaiting_approval' && incident.sandbox?.passed) {
    return { index: 3, section: 'sandbox', target: '[data-action="approve"]', action: 'Review & approve recovery', caption: workflowSteps[3].caption }
  }
  if (incident && !['resolved', 'rejected', 'failed'].includes(incident.status)) {
    return { index: 2, section: 'investigation', target: '.incident-summary', action: 'Review the evidence', caption: overview.services[0]?.status === 'quarantined' ? 'Fault contained. Follow the payment evidence below.' : 'Integrity violation detected. Investigation and containment are running.' }
  }
  if (!incident && overview.integrity.status !== 'healthy') return { index: 2, section: 'investigation', target: '#investigation .section-title', action: 'Review the evidence', caption: 'Integrity violation detected. Waiting for incident evidence.' }
  if (overview.traffic_running) {
    const armed = overview.services[0]?.fault
    return { index: 1, section: armed ? 'bank' : 'simulator', target: armed ? '#live-bank-metrics' : '[data-action="duplicate"]', action: armed ? 'Watch live payments' : 'Choose a fault to inject', caption: armed ? 'Fault armed. Waiting for the next live payment.' : workflowSteps[1].caption }
  }
  return { index: 0, section: 'simulator', target: '[data-action="traffic"]', action: 'Start live traffic', caption: 'The bank is healthy. Start traffic to begin the demonstration.' }
}
