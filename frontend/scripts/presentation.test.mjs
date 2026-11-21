import assert from 'node:assert/strict'
import { test } from 'node:test'
import { balanceMessage, isForbiddenApproval, terminalStage } from '../src/presentation.ts'

test('healthy balanced banner is neutral and explains the independent check', () => {
  assert.deepEqual(balanceMessage(true, 'healthy'), {
    alert: false, heading: 'Debits = credits.',
    detail: 'A balanced ledger alone does not prove correctness — balanced ≠ correct.',
  })
})
for (const status of ['violated', 'recovering']) {
  test(`balanced ${status} banner keeps the financial violation explicit`, () => {
    assert.deepEqual(balanceMessage(true, status), {
      alert: true, heading: 'Debits = credits.',
      detail: 'The ledger still balances, but integrity is VIOLATED — balanced ≠ correct.',
    })
  })
}
test('an unbalanced ledger is an alert even with a stale healthy status', () => {
  for (const status of ['healthy', 'violated', 'recovering']) {
    assert.deepEqual(balanceMessage(false, status), {
      alert: true, heading: 'Debits ≠ credits.', detail: `Integrity is ${status.toUpperCase()}.`,
    })
  }
})
test('missing integrity metadata never claims health', () => {
  assert.equal(balanceMessage(true, undefined).alert, true)
  assert.equal(balanceMessage(false, undefined).detail, 'Integrity is UNKNOWN.')
})
test('only rejected and failed incidents acquire terminal steps', () => {
  for (const status of ['rejected', 'failed']) assert.equal(terminalStage(status), status)
  for (const status of [undefined, '', 'detected', 'awaiting_approval', 'correcting', 'resolved']) {
    assert.equal(terminalStage(status), null)
  }
})
test('approval 403 has a dedicated presentation', () => {
  assert.equal(isForbiddenApproval('approve', { error: true, text: 'HTTP 403 · Agent cannot approve' }), true)
})
test('empty, successful and other error results retain normal presentation', () => {
  assert.equal(isForbiddenApproval('approve'), false)
  for (const result of [
    { error: true, text: '' },
    { error: false, text: 'HTTP 403' },
    { error: true, text: 'HTTP 4030' },
    { error: true, text: 'HTTP 500 · unavailable' },
    { error: true, text: 'Backend unreachable' },
  ]) assert.equal(isForbiddenApproval('approve', result), false)
  assert.equal(isForbiddenApproval('challenge', { error: true, text: 'HTTP 403' }), false)
})
