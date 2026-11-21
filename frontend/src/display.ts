import type { Entry, Overview, Payment } from './types'

export function maskIban(iban?: string | null) {
  return iban ? `${iban.slice(0, 4)} ${iban.slice(4, 8)} •••• ${iban.slice(-4)}` : 'IBAN unavailable'
}

export function createDisplay(accounts: Overview['accounts'], payments: Payment[], entries: Entry[]) {
  const accountMap = new Map(accounts.map(account => [account.id, account]))
  const paymentMap = new Map(payments.map(payment => [payment.id, payment]))
  const entryMap = new Map(entries.map(entry => [entry.id, entry]))
  const accountName = (id: string) => accountMap.get(id)?.name ?? 'Account information unavailable'
  const reference = (id: string) => paymentMap.get(id)?.reference ?? 'Payment reference unavailable'
  const purpose = (id: string) => paymentMap.get(id)?.purpose_label ?? 'Payment'
  const journal = (id: string) => id.startsWith('entry-') ? 'JE' + id.slice(6) : 'Compensating journal'
  const humanize = (text: string) => text
    .replace(/correction-incident-\d+-(?:entry-\d+|intent-payment-\d+)/g, id => {
      const entry = entryMap.get(id)
      return entry ? 'Recovery journal for ' + reference(entry.instruction_id) : 'Recovery journal'
    })
    .replace(/idem-payment-\d+/g, id => 'settlement key for ' + reference(id.slice(5)))
    .replace(/payment-\d+/g, reference)
    .replace(/customer-\d+/g, accountName)
    .replace(/\b(clearing|treasury)\b(?!@)/g, accountName)
    .replace(/entry-\d+/g, journal)
    .replace(/event-(\d+)/g, (_, sequence) => 'settlement event #' + Number(sequence))
    .replace(/(?:proposal-)?incident-\d+/g, 'settlement incident')
  return {
    accountName, reference, purpose, journal, humanize,
    iban: (id: string) => maskIban(accountMap.get(id)?.iban),
  }
}

export type Display = ReturnType<typeof createDisplay>
