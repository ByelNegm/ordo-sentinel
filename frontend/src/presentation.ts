export function balanceMessage(balanced: boolean, status: string | undefined) {
  if (!balanced) return {
    alert: true,
    heading: 'Debits ≠ credits.',
    detail: `Integrity is ${status?.toUpperCase() || 'UNKNOWN'}.`,
  }
  return {
    alert: status !== 'healthy',
    heading: 'Debits = credits.',
    detail: status === 'healthy'
      ? 'A balanced ledger alone does not prove correctness — balanced ≠ correct.'
      : 'The ledger still balances, but integrity is VIOLATED — balanced ≠ correct.',
  }
}

export function terminalStage(status: string | undefined) {
  return status === 'rejected' || status === 'failed' ? status : null
}

export function isForbiddenApproval(key: string, result?: { error: boolean; text: string }) {
  return key === 'approve' && result?.error === true && /^HTTP 403\b/.test(result.text)
}
