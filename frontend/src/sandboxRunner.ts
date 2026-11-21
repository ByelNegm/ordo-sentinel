import type { Incident } from './types'

export function sandboxRunnerLabel(sandbox: Incident['sandbox'] | undefined): string {
  if (sandbox?.runner === 'daytona' && sandbox.remote_match === true && sandbox.runner_id) {
    return `Daytona sandbox ${sandbox.runner_id.slice(0, 8)} · remote checks match`
  }
  const note = sandbox?.runner_note || (sandbox?.remote_match === false
    ? 'remote checks differed; local validation retained'
    : 'not configured')
  return `Local isolated copy (Daytona unavailable: ${note})`
}
