import assert from 'node:assert/strict'
import { test } from 'node:test'
import { auditTone, guideStepTone, statusTone } from '../src/status.ts'

for (const [tone, values] of Object.entries({
  success: ['healthy', 'verified', 'resolved', 'passed', 'running', 'settled'],
  warning: ['recovering', 'investigating', 'contained', 'validating', 'awaiting_approval', 'correcting', 'quarantined', 'held', 'pending'],
  danger: ['violated', 'blocked', 'rejected', 'failed', 'denied', '403', 'sandbox rejected', 'discrepancy', 'missing'],
  neutral: [undefined, null, '', 'unknown', 'info'],
})) {
  test(`semantic status palette: ${tone}`, () => {
    for (const value of values) assert.equal(statusTone(value), tone, String(value))
  })
}
test('status normalization handles display labels without matching unrelated HTTP codes', () => {
  assert.equal(statusTone(' RECOVERING '), 'warning')
  assert.equal(statusTone('awaiting approval'), 'warning')
  assert.equal(statusTone('HTTP 403'), 'danger')
  assert.equal(statusTone('HTTP 4030'), 'neutral')
})
test('audit outcomes distinguish transport completion from sandbox rejection', () => {
  for (const action of ['approval.denied', 'sandbox.challenge.rejected', 'recovery.failed', 'integrity.violated']) assert.equal(auditTone(action), 'danger')
  for (const action of ['service.quarantined', 'investigation.completed', 'sandbox.started', 'recovery.started']) assert.equal(auditTone(action), 'warning')
  for (const action of ['sandbox.completed', 'sandbox.remote_validated', 'recovery.approved', 'recovery.verified', 'service.released']) assert.equal(auditTone(action), 'success')
  assert.equal(auditTone('sandbox.completed', 'Sandbox passed: False'), 'danger')
  assert.equal(auditTone('sandbox.completed', 'Sandbox passed: True'), 'success')
  assert.equal(auditTone('traffic.stopped'), 'neutral')
  assert.equal(auditTone(undefined), 'neutral')
})
test('guide progression separates completed, current recovery, terminal and future stages', () => {
  assert.equal(guideStepTone(0, -1), 'neutral')
  assert.equal(guideStepTone(0, 0), 'success')
  assert.equal(guideStepTone(1, 1), 'warning')
  assert.equal(guideStepTone(2, 2, 'detected'), 'danger')
  assert.equal(guideStepTone(2, 2, 'contained'), 'warning')
  assert.equal(guideStepTone(3, 3, 'awaiting_approval'), 'warning')
  assert.equal(guideStepTone(4, 4, 'correcting'), 'warning')
  assert.equal(guideStepTone(2, 2, 'rejected'), 'danger')
  assert.equal(guideStepTone(2, 2, 'failed'), 'danger')
  assert.equal(guideStepTone(1, 3, 'awaiting_approval'), 'success')
  assert.equal(guideStepTone(4, 3, 'awaiting_approval'), 'neutral')
  assert.equal(guideStepTone(5, 5, 'resolved'), 'success')
})
