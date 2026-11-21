import assert from 'node:assert/strict'
import { test } from 'node:test'
import { sandboxRunnerLabel } from '../src/sandboxRunner.ts'

test('remote badge requires a matching result and a sandbox identity', () => {
  assert.equal(sandboxRunnerLabel({
    runner: 'daytona', runner_id: '12345678-abcd', remote_match: true,
  }), 'Daytona sandbox 12345678 · remote checks match')
})
test('fallback badge explains the recorded remote failure', () => {
  assert.equal(sandboxRunnerLabel({
    runner: 'local', remote_match: null, runner_note: 'Remote validation timed out after 8s',
  }), 'Local isolated copy (Daytona unavailable: Remote validation timed out after 8s)')
})
test('empty and legacy sandbox metadata remain explicit about local execution', () => {
  for (const value of [undefined, null, {}]) {
    assert.equal(sandboxRunnerLabel(value), 'Local isolated copy (Daytona unavailable: not configured)')
  }
})
test('a disagreement never claims remote success', () => {
  assert.equal(sandboxRunnerLabel({
    runner: 'daytona', runner_id: '12345678-abcd', remote_match: false,
  }), 'Local isolated copy (Daytona unavailable: remote checks differed; local validation retained)')
})
test('unconfirmed or anonymous remote metadata does not claim a match', () => {
  for (const value of [
    { runner: 'daytona', runner_id: '12345678-abcd', remote_match: null },
    { runner: 'daytona', runner_id: null, remote_match: true },
  ]) assert.match(sandboxRunnerLabel(value), /^Local isolated copy/)
})
