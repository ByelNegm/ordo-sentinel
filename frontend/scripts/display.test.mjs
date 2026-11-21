import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createDisplay, maskIban } from '../src/display.ts'
import { deriveWorkflow } from '../src/workflow.ts'

const accounts = [{ id: 'customer-01', name: 'Al Noor Trading LLC', iban: 'AE070331234567890124567' }]
const payments = [{ id: 'payment-000102', reference: 'FT26325K8QZ2', purpose_label: 'Supplier payment' }]
const display = createDisplay(accounts, payments, [])
const overview = {
  accounts, services: [{ status: 'running', fault: null }], traffic_running: false,
  integrity: { status: 'healthy' },
}
const seven = Array.from({ length: 7 }, (_, index) => ({ name: 'check' + index, pass: true }))

test('bank display uses names, references, purpose and masked IBAN', () => {
  assert.equal(display.accountName('customer-01'), 'Al Noor Trading LLC')
  assert.equal(display.reference('payment-000102'), 'FT26325K8QZ2')
  assert.equal(display.purpose('payment-000102'), 'Supplier payment')
  assert.equal(display.iban('customer-01'), 'AE07 0331 •••• 4567')
})
test('empty and legacy metadata never exposes internal IDs', () => {
  const empty = createDisplay([], [], [])
  assert.equal(maskIban(null), 'IBAN unavailable')
  assert.equal(empty.reference('payment-000102'), 'Payment reference unavailable')
  assert.equal(empty.accountName('customer-01'), 'Account information unavailable')
})
test('diagnostics and audit text are sanitized, including compound correction IDs', () => {
  const text = display.humanize('customer-01 payment-000102 idem-payment-000102 correction-incident-0001-entry-000103 event-000103 entry-000102 incident-0001')
  assert.doesNotMatch(text, /customer-|payment-|incident-|entry-|event-/)
  assert.match(text, /Al Noor Trading LLC/)
  assert.match(text, /FT26325K8QZ2/)
  assert.match(text, /JE000102/)
  assert.equal(display.humanize('treasury@bank'), 'treasury@bank')
})
for (const [name, bank, incident, index, action] of [
  ['connecting', null, undefined, -1, 'Connecting to backend'],
  ['healthy', overview, undefined, 0, 'Start live traffic'],
  ['traffic', { ...overview, traffic_running: true }, undefined, 1, 'Choose a fault to inject'],
  ['armed fault', { ...overview, traffic_running: true, services: [{ status: 'running', fault: 'duplicate' }] }, undefined, 1, 'Watch live payments'],
  ['detected', overview, { status: 'detected' }, 2, 'Review the evidence'],
  ['contained', { ...overview, services: [{ status: 'quarantined' }] }, { status: 'contained' }, 2, 'Review the evidence'],
  ['validated', overview, { status: 'awaiting_approval', sandbox: { passed: true } }, 3, 'Review & approve recovery'],
  ['correcting', overview, { status: 'correcting' }, 4, 'View correction progress'],
  ['verified', { ...overview, services: [{ status: 'quarantined' }] }, { status: 'resolved', verification: { checks: seven } }, 5, 'Release settlement-svc'],
  ['released', overview, { status: 'resolved', verification: { checks: seven } }, 5, 'Reset baseline'],
  ['rejected', { ...overview, integrity: { status: 'violated' } }, { status: 'rejected' }, 6, 'Reset baseline'],
  ['evidence pending', { ...overview, integrity: { status: 'violated' } }, undefined, 2, 'Review the evidence'],
]) {
  test('workflow derives ' + name + ' from backend state', () => {
    const result = deriveWorkflow(bank, incident)
    assert.equal(result.index, index)
    assert.equal(result.action, action)
  })
}
test('failed sandbox cannot enable the approval workflow stage', () => {
  assert.equal(deriveWorkflow(overview, { status: 'awaiting_approval', sandbox: { passed: false } }).index, 2)
})
for (const status of ['rejected', 'failed']) {
  test(`terminal ${status} guide has a reset target regardless of integrity status`, () => {
    for (const integrityStatus of ['healthy', 'violated', 'recovering']) {
      const result = deriveWorkflow({ ...overview, integrity: { status: integrityStatus } }, { status })
      assert.equal(result.index, 6)
      assert.equal(result.terminal, status)
      assert.equal(result.caption, 'Reset the bank to start again')
      assert.equal(result.action, 'Reset baseline')
      assert.equal(result.section, 'simulator')
      assert.equal(result.target, '[data-action="reset"]')
    }
  })
}
test('terminal guide clears with reset and waits for real overview data', () => {
  assert.equal(deriveWorkflow(overview).terminal, undefined)
  assert.equal(deriveWorkflow(overview, { status: 'awaiting_approval', sandbox: { passed: true } }).terminal, undefined)
  assert.equal(deriveWorkflow(null, { status: 'failed' }).index, -1)
  assert.equal(deriveWorkflow(null, { status: 'failed' }).terminal, undefined)
})
