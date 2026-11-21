import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { PulseIcon as Activity, ArrowDownLeftIcon as ArrowDownLeft, ArrowRightIcon as ArrowRight,
  ArrowUpRightIcon as ArrowUpRight, CheckIcon as Check, CaretRightIcon as ChevronRight,
  CircleIcon as Circle, DatabaseIcon as Database, FingerprintIcon as Fingerprint,
  FlaskIcon as FlaskConical, StackIcon as Layers3, SpinnerGapIcon as LoaderCircle,
  LockKeyIcon as LockKeyhole, BroadcastIcon as Radio, ArrowCounterClockwiseIcon as RotateCcw,
  CubeFocusIcon as ScanLine, CheckCircleIcon as ShieldCheck, WarningCircleIcon as ShieldX,
  TerminalWindowIcon as Terminal, WarningIcon as TriangleAlert, LightningIcon as Zap, XIcon as X } from '@phosphor-icons/react'
import type { ChallengeVariant, Check as IntegrityCheck, Entry, SandboxChallenge } from './types'
import { api, useBank } from './useBank'
import { createDisplay } from './display'
import { deriveWorkflow, workflowSteps } from './workflow'
import { sandboxRunnerLabel } from './sandboxRunner'
import { balanceMessage, isForbiddenApproval, terminalStage } from './presentation'

const DisplayContext = createContext(createDisplay([], [], []))

const money = (value: number) => (value / 100).toLocaleString('en-AE', { style: 'currency', currency: 'AED' })
const label = (value: string) => value.replaceAll('_', ' ')
const clock = (value: string) => new Date(value).toLocaleTimeString('en-GB', { hour12: false })
const navigation = [
  { id: 'bank', title: 'Bank Operations', icon: Layers3 },
  { id: 'simulator', title: 'Attack Simulator', icon: Zap },
  { id: 'investigation', title: 'Incident Investigation', icon: Fingerprint },
  { id: 'sandbox', title: 'Recovery Sandbox', icon: FlaskConical },
  { id: 'verification', title: 'Recovery Verification', icon: ShieldCheck },
]
const stages = ['detected', 'investigating', 'contained', 'validating', 'awaiting_approval', 'correcting', 'resolved']
const positive = new Set(['healthy', 'running', 'settled', 'resolved', 'passed'])
const negative = new Set(['violated', 'quarantined', 'discrepancy', 'missing', 'failed', 'rejected'])

function Badge({ value, children }: { value: string; children?: ReactNode }) {
  return <span className={`badge ${positive.has(value) ? 'good' : negative.has(value) ? 'bad' : 'warn'}`}>
    {positive.has(value) ? <Check size={12} /> : negative.has(value) ? <ShieldX size={12} /> : <span className="dot" />}{children ?? label(value)}</span>
}
function Panel({ title, note, children, className = '' }: { title: string; note?: ReactNode; children: ReactNode; className?: string }) {
  return <div className={`panel ${className}`}><div className="panel-heading"><h3>{title}</h3>{note}</div>{children}</div>
}
function BalanceBanner({ balanced, status, context = false }: { balanced: boolean; status: string | undefined; context?: boolean }) {
  const message = balanceMessage(balanced, status)
  return <div className={`balance-banner ${message.alert ? 'alert' : ''}`} data-testid={context ? 'approval-balance-banner' : 'balance-banner'}>
    <strong>{message.heading}</strong> {message.detail}
  </div>
}
function SectionTitle({ number, title, subtitle }: { number: string; title: string; subtitle: string }) {
  return <div className="section-title"><span className="section-number">{number}</span><div><h2>{title}</h2><p>{subtitle}</p></div></div>
}
function Checks({ checks, compact = false }: { checks: IntegrityCheck[]; compact?: boolean }) {
  const display = useContext(DisplayContext)
  return <div className={compact ? 'check-list' : 'checks-grid'}>{checks.map(check =>
    <div className={`integrity-check ${check.pass ? 'pass' : 'fail'}`} key={check.name} title={display.humanize(check.detail)}>
      {check.pass ? <ShieldCheck size={17} /> : <ShieldX size={17} />}
      <div><strong>{label(check.name)}</strong><small>{compact ? display.humanize(check.detail) : check.pass ? 'PASS' : 'FAIL'}</small></div>
      {compact && <span className="check-result">{check.pass ? 'PASS' : 'FAIL'}</span>}
    </div>)}</div>
}
function Empty({ children }: { children: ReactNode }) {
  return <div className="empty"><ScanLine size={26} /><p>{children}</p></div>
}
function AccountView({ id }: { id: string }) {
  const display = useContext(DisplayContext)
  return <span className="account-label"><b>{display.accountName(id)}</b><small className="mono">{display.iban(id)}</small></span>
}
function EntryTable({ entries, originals = false }: { entries: Entry[]; originals?: boolean }) {
  const display = useContext(DisplayContext)
  return <div className="table-scroll"><table className="entries"><thead><tr><th>Journal entry / instruction</th><th>Posting lines</th><th>{originals ? 'Original preserved' : 'Corrects entry'}</th><th>Actor</th></tr></thead>
    <tbody>{entries.map(entry => <tr key={entry.id} id={'ledger-' + entry.id}>
      <td><span className="mono">{display.reference(entry.instruction_id)}</span><small>{display.purpose(entry.instruction_id)} · {entry.kind}</small><small>{display.journal(entry.id)}</small></td>
      <td>{entry.lines.map((line, i) => <div className="posting" key={i}><span>{line.side === 'debit' ? 'DR' : 'CR'} <AccountView id={line.account} /></span><span>{money(line.amount_minor)}</span></div>)}</td>
      <td>{entry.corrects_entry_id ? display.journal(entry.corrects_entry_id) : 'New intent effect'}</td><td>{entry.actor}</td>
    </tr>)}</tbody></table></div>
}

export default function App() {
  const { data, connected, error, refresh } = useBank()
  const [active, setActive] = useState('bank')
  const [actor, setActor] = useState('ops.lead@bank')
  const [pending, setPending] = useState('')
  const [results, setResults] = useState<Record<string, { error: boolean; text: string; raw?: string }>>({})
  const [ledgerOpen, setLedgerOpen] = useState(false)
  const [challenge, setChallenge] = useState<{ response: SandboxChallenge; before: number; after: number; unchanged: boolean } | null>(null)
  const { overview, integrity, payments, settlements, ledger, incidents, audit } = data
  const display = createDisplay(overview?.accounts ?? [], payments, ledger)
  const incident = incidents[0]
  const workflow = deriveWorkflow(overview, incident)
  const workflowRef = useRef<HTMLDivElement>(null)
  const lastStage = useRef(-1)
  useEffect(() => { setChallenge(null) }, [incident?.id])
  const service = overview?.services[0]
  const status = integrity?.status ?? overview?.integrity.status
  const passed = integrity?.checks.filter(check => check.pass).length
  const balanced = overview ? overview.totals.debits_minor === overview.totals.credits_minor : null
  const corrections = incident ? ledger.filter(entry => incident.corrections.includes(entry.id)) : []
  const navigate = (id: string) => {
    setActive(id)
    document.getElementById(id)?.scrollIntoView({ block: 'start' })
  }
  useLayoutEffect(() => {
    const element = workflowRef.current
    if (!element) return
    const update = () => document.documentElement.style.setProperty('--workspace-offset', Math.ceil(element.getBoundingClientRect().bottom + 16) + 'px')
    update()
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (workflow.index >= 0 && lastStage.current !== workflow.index) {
      lastStage.current = workflow.index
      navigate(workflow.index === 0 ? 'bank' : workflow.section)
    }
  }, [workflow.index])
  const guideNext = () => {
    navigate(workflow.section)
    requestAnimationFrame(() => {
      const element = document.querySelector<HTMLElement>(workflow.target)
      if (!element) return
      element.focus({ preventScroll: true })
      element.classList.add('next-control-pulse')
      element.addEventListener('animationend', () => element.classList.remove('next-control-pulse'), { once: true })
    })
  }
  async function act(key: string, path: string, body?: unknown) {
    setPending(key)
    try {
      const response = await api(path, body, 'POST')
      const text = 'HTTP 200 · ' + (response.fault ? `${response.fault} fault armed` :
        typeof response.running === 'boolean' ? `Traffic ${response.running ? 'started' : 'stopped'}` :
          response.integrity ? `Baseline restored · ${response.volume.settled} settled payments` :
            response.status ? `${response.id} · ${label(response.status)}` : 'Action accepted')
      setResults(old => ({ ...old, [key]: { error: false, text, raw: JSON.stringify(response, null, 2) } }))
      if (key === 'reset') {
        setResults({ reset: { error: false, text } })
        setActor('ops.lead@bank')
      }
    } catch (cause) {
      const text = cause instanceof Error ? cause.message : 'Request failed'
      setResults(old => ({ ...old, [key]: { error: true, text } }))
    } finally {
      await refresh()
      setPending('')
    }
  }
  async function attemptUnsafe(variant: ChallengeVariant) {
    if (!incident || incident.status !== 'awaiting_approval') return
    setPending('challenge')
    setChallenge(null)
    setResults(old => ({ ...old, challenge: { error: false, text: 'Checking isolated candidate…' } }))
    try {
      const [beforeRows, before] = await Promise.all([api('/ledger?limit=500'), api('/overview')])
      const response: SandboxChallenge = await api('/incidents/' + incident.id + '/sandbox/challenge', { variant }, 'POST')
      const [afterRows, after] = await Promise.all([api('/ledger?limit=500'), api('/overview')])
      setChallenge({
        response, before: before.totals.ledger_entries, after: after.totals.ledger_entries,
        unchanged: response.ledger_unchanged && before.totals.ledger_entries === after.totals.ledger_entries
          && JSON.stringify(beforeRows) === JSON.stringify(afterRows),
      })
      setResults(old => ({ ...old, challenge: { error: false, text: 'HTTP 200 · Isolated challenge completed' } }))
    } catch (cause) {
      setResults(old => ({ ...old, challenge: { error: true, text: cause instanceof Error ? cause.message : 'Backend unreachable' } }))
    } finally {
      await refresh()
      setPending('')
    }
  }
  const result = (key: string) => results[key] && <div className={`action-result ${results[key].error ? 'error-result' : ''} ${isForbiddenApproval(key, results[key]) ? 'approval-forbidden' : ''}`} role={results[key].error ? 'alert' : 'status'}>
    {results[key].error ? <TriangleAlert size={14} /> : <Check size={14} />}{isForbiddenApproval(key, results[key]) ? <div className="forbidden-copy">
      <strong>Agent approval blocked</strong><p>{display.humanize(results[key].text)}</p>
      {overview && <BalanceBanner balanced={balanced === true} status={status} context />}
    </div> : <span>{display.humanize(results[key].text)}</span>}
  </div>
  const actionButton = (key: string, title: string, path: string, style = '', disabled = false, body?: unknown) =>
    <button data-action={key} className={`button ${style}`} disabled={!!pending || disabled || !overview} onClick={() => { void act(key, path, body) }}>
      {pending === key ? <LoaderCircle className="spin" size={16} /> : key === 'reset' ? <RotateCcw size={15} /> : key === 'approve' ? <LockKeyhole size={15} /> : <ChevronRight size={15} />}{title}
    </button>

  return <DisplayContext.Provider value={display}><div className="app-shell">
    <aside className="rail">
      <a className="brand" href="#bank" onClick={() => navigate('bank')}><span className="brand-mark"><ScanLine size={25} /></span><span>BLACKBOX<small>Integrity infrastructure</small></span></a>
      <div className="rail-label">Operations console <span>v1.0</span></div>
      <nav aria-label="Sections">{navigation.map((item, index) => <button key={item.id} aria-label={item.title} onClick={() => navigate(item.id)} className={active === item.id ? 'active' : ''}>
        <item.icon size={18} /><span>{item.title}</span><small>0{index + 1}</small>
      </button>)}</nav>
      <div className="rail-bottom"><div className="rail-service"><span className={`dot ${connected ? 'live-dot' : 'offline-dot'}`} />{connected ? 'Live event stream' : 'Reconnecting stream'}</div>
        <p>Independent intent.<br />Immutable evidence.<br />Human control.</p><div className="rail-footer"><ShieldCheck size={14} /> Synthetic environment <ArrowUpRight size={13} /></div>
      </div>
    </aside>

    <header className="topbar">
      <span className="top-path">Workspace <ChevronRight size={13} /><b>Bank infrastructure</b></span>
      <div className="top-indicators"><span className="top-integrity" data-testid="integrity-status">{status ? <Badge value={status}>{status.toUpperCase()}</Badge> : 'CONNECTING'}</span>
        <span data-testid="checks-passed">{passed ?? '–'}/7 checks</span><span className="top-service">{service?.id ?? 'settlement-svc'} <b className={service?.status === 'quarantined' ? 'red-text' : 'accent-text'}>{service?.status ?? '–'}</b></span>
        <span>{overview?.open_incidents ?? '–'} open</span><span className="traffic-state"><Radio size={13} /> Traffic {overview ? overview.traffic_running ? 'ON' : 'OFF' : '–'}</span>
      </div>
    </header>

    <div className="workflow-strip" ref={workflowRef} role="region" aria-label="Guided workflow">
      <ol className="workflow-steps">{workflowSteps.map((step, index) => <li key={step.title} className={index === workflow.index ? 'current' : index < workflow.index ? 'complete' : ''} aria-current={index === workflow.index ? 'step' : undefined}><span>{index < workflow.index ? <Check size={12} /> : index + 1}</span><div><strong>{step.title}</strong><small>{step.caption}</small></div></li>)}</ol>
      <div className="workflow-next"><p data-testid="workflow-caption">{workflow.caption}</p><button className="button primary" data-testid="workflow-next" aria-label={'Go to control: ' + workflow.action} disabled={!overview || !connected} onClick={guideNext}>{workflow.action}<ArrowRight size={15} /></button></div>
    </div>
    <main>
      {(error || !connected) && <div className="connection-banner" role="status"><Radio size={16} />{error ? display.humanize(error) : 'Event stream reconnecting; displayed data may be stale.'}<button onClick={() => { void refresh() }}>Retry connection</button></div>}
      <section id="bank">
        <div className="eyebrow"><span className="live-dot dot" /> Independent payment monitoring</div>
        <div className="hero"><div><div className="overline">Bank operations</div>
          <h1>{!overview ? 'Connecting to the bank.' : status === 'violated' ? 'Balanced. But not correct.' : status === 'recovering' ? 'Recovery in progress.' : incident?.status === 'resolved' ? 'Integrity restored.' : 'Trust, independently verified.'}</h1>
          <p>Reconcile what happened against what should have happened.</p></div><div className="environment"><span className="dot live-dot" /> Synthetic bank<small>Real ledger. Real fault paths.</small></div></div>
        <div className="metric-grid" id="live-bank-metrics">
          <div className="metric"><span><Activity size={16} /> Payment volume</span><strong>{overview?.volume.instructions.toLocaleString() ?? '–'}<small>instructions</small></strong><div>{overview?.volume.settled ?? '–'} settled <i />{overview?.volume.held ?? '–'} held <i />{overview?.volume.pending ?? '–'} pending</div></div>
          <div className="metric"><span><ArrowUpRight size={16} /> Total debits</span><strong className="money">{overview ? money(overview.totals.debits_minor) : '–'}</strong><div>{overview?.totals.ledger_entries ?? '–'} append-only journal entries</div></div>
          <div className="metric"><span><ArrowDownLeft size={16} /> Total credits</span><strong className="money">{overview ? money(overview.totals.credits_minor) : '–'}</strong><div className={balanced === null ? '' : balanced ? 'accent-text' : 'red-text'}>{balanced === null ? 'Waiting for ledger' : balanced ? <><Check size={11} /> Debits equal credits</> : 'Debits and credits differ'}<b className="balanced-note">Balanced ≠ correct</b></div></div>
        </div>
        {overview && <BalanceBanner balanced={balanced === true} status={status} />}
        <Panel title="Independent integrity checks" note={<span className="subtle">{passed ?? '–'} of 7 passing · Reconciled against intent</span>}>
          {integrity ? <Checks checks={integrity.checks} /> : <Empty>Loading independent integrity checks…</Empty>}
        </Panel>
        <div className="bank-grid">
          <Panel title="Payment instructions" note={<span className="subtle">Latest {Math.min(payments.length, 50)} <span className="accent-text">/ Live</span></span>}>
            <div className="table-scroll payment-scroll"><table><thead><tr><th>Instruction</th><th>Debtor → Creditor</th><th className="right">Amount</th><th>Status</th><th>Effects</th></tr></thead><tbody>
              {payments.slice(0, 50).map(payment => <tr key={payment.id} className={payment.settlement_count > 1 || ['missing', 'discrepancy'].includes(payment.status) ? 'anomaly-row' : ''}>
                <td className="mono">{display.reference(payment.id)}<small>{payment.purpose} · {display.purpose(payment.id)}</small><small>{clock(payment.created_at)}</small></td><td><AccountView id={payment.debtor} /><span className="route-arrow">→</span><AccountView id={payment.creditor} /></td>
                <td className="right tabular">{money(payment.amount_minor)}</td><td><Badge value={payment.status} /></td>
                <td><span className={payment.settlement_count > 1 ? 'effect duplicate' : 'effect'}>{payment.settlement_count > 1 ? '×' : ''}{payment.settlement_count}</span></td></tr>)}
            </tbody></table>{!payments.length && <Empty>No payment instructions received.</Empty>}</div>
          </Panel>
          <Panel title="Settlement events" note={<Radio size={15} className="accent-text" />}>
            <div className="event-feed">{settlements.slice(0, 14).map(event => <div className="feed-event" key={event.id}><span className="event-icon"><ArrowRight size={14} /></span><div><strong className="mono">{display.reference(event.instruction_id)}</strong><small>{display.purpose(event.instruction_id)} · Settlement #{event.seq}</small><span>{money(event.amount_minor)}</span></div><time>{clock(event.ts)}</time></div>)}
              {!settlements.length && <Empty>No settlement events received.</Empty>}</div>
          </Panel>
        </div>
        <details className="disclosure"><summary><Database size={16} /> Account balances <span>{overview?.accounts.length ?? 0} accounts · Derived from postings</span></summary>
          <div className="table-scroll"><table><thead><tr><th>Account / masked IBAN</th><th>Type</th><th className="right">Balance</th></tr></thead><tbody>{overview?.accounts.map(account => <tr key={account.id}><td><AccountView id={account.id} /></td><td>{account.type}</td><td className="right tabular">{money(account.balance_minor)}</td></tr>)}</tbody></table></div>
        </details>
        <details className="disclosure" open={ledgerOpen} onToggle={event => setLedgerOpen(event.currentTarget.open)}><summary><Layers3 size={16} /> Append-only ledger <span>Latest {ledger.length} entries · Originals preserved</span></summary><EntryTable entries={ledger} /></details>
      </section>

      <section id="simulator">
        <SectionTitle number="02" title="Attack Simulator" subtitle="Controlled infrastructure faults. Real consequences. A repeatable recovery." />
        <div className="simulator-grid">
          <div className="panel control-card"><span className="control-icon accent"><Activity size={20} /></span><h3>Live payment traffic</h3><p>One deterministic payment approximately every 1.5 seconds.</p>
            {actionButton('traffic', overview?.traffic_running ? 'Stop traffic' : 'Start traffic', '/traffic/' + (overview?.traffic_running ? 'stop' : 'start'), 'primary')}
            {result('traffic')}</div>
          {([{ kind: 'duplicate', title: 'Duplicate Settlement', text: 'A retry bypasses deduplication. Two events. Two balanced postings.' },
            { kind: 'missing', title: 'Missing Settlement', text: 'Acknowledged before the write. The payment effect never arrives.' },
            { kind: 'tamper', title: 'Tampered Settlement', text: 'An altered event amount diverges from independent payment intent.' }]).map(fault =>
              <div className="panel control-card" key={fault.kind}><span className="control-icon neutral"><Zap size={20} /></span><h3>{fault.title}</h3><p>{fault.text}</p>
                {actionButton(fault.kind, 'Inject ' + fault.title, '/faults/' + fault.kind, 'danger-outline')}{result(fault.kind)}</div>)}
        </div>
        <div className="reset-strip"><div><RotateCcw size={18} /><span><strong>A clean slate. Not a hidden correction.</strong><small>Reset cancels tasks and re-seeds 100 settled payments. This discards the demo session.</small></span></div>{actionButton('reset', 'Reset baseline', '/reset')}{result('reset')}</div>
      </section>

      <section id="investigation">
        <SectionTitle number="03" title="Incident Investigation" subtitle="Follow the evidence. Reconstruct the failure. Isolate the source." />
        {!incident ? <Panel title="Investigation workspace"><Empty>No incidents. Monitoring independent payment intent for integrity violations.</Empty></Panel> : <>
          <p className="incident-summary" data-testid="incident-summary">{incident.summary_text ?? 'Reconstructing the payment from independent evidence…'}</p>
          <div className="incident-header"><span className="accent-text">Settlement recovery</span><span>{label(incident.type)}</span><Badge value={incident.status}><span data-testid="incident-status">{label(incident.status)}</span></Badge><span className="subtle">Newest incident · {incidents.length} total</span></div>
          <div className="stepper">{stages.map((stage, index) => <div key={stage} className={incident.status === stage ? 'step current' : stages.indexOf(incident.status) > index ? 'step done' : 'step'}><span>{stages.indexOf(incident.status) > index ? <Check size={13} /> : String(index + 1).padStart(2, '0')}</span><b>{label(stage)}</b></div>)}{terminalStage(incident.status) && <div className="step terminal" data-testid="terminal-step"><span><X size={14} /></span><b>{terminalStage(incident.status)}</b></div>}</div>
          <div className="investigation-grid">
            <Panel title="Root cause" note={<span className="method">{incident.root_cause.method === 'deterministic' ? 'Deterministic' : incident.root_cause.method}</span>}>
              <div className="root-cause"><div className="root-service"><Terminal size={18} /><strong>{incident.root_cause.service}</strong><span>{incident.root_cause.confidence} confidence</span></div><p>{display.humanize(incident.root_cause.summary)}</p><div className="impact"><span>Financial impact</span><strong>{money(incident.impact_minor)}</strong><small>{incident.affected_payments.length} affected payment{incident.affected_payments.length === 1 ? '' : 's'} · {incident.affected_accounts.map(display.accountName).join(', ')}</small></div></div>
            </Panel>
            <Panel title="Containment" note={<LockKeyhole size={16} />}>{incident.containment ? <div className="containment"><Badge value={service?.status ?? 'quarantined'} /><h3>{incident.containment.service}</h3><p>Quarantine applied at {clock(incident.containment.at)}. Held payments remain queued until service release.</p><strong>{overview?.volume.held ?? incident.containment.held_instructions}<small>instructions currently held</small></strong><span className="subtle">{incident.containment.held_instructions} held in latest incident evidence</span></div> : <Empty>Investigation is running. No containment action recorded yet.</Empty>}</Panel>
          </div>
          <Panel title="Evidence lineage" note={<span className="subtle">Independent intent → event → journal</span>}>
            <div className="lineages">{incident.lineage.length ? incident.lineage.map(line => <div className="lineage" key={line.instruction_id}><div><small>Payment instruction</small><strong className="mono">{display.reference(line.instruction_id)}</strong><small>{display.purpose(line.instruction_id)}</small><small className="evidence-id">{line.instruction_id}</small></div><ArrowRight size={18} /><div><small>Settlement events</small>{line.event_ids.length ? line.event_ids.map(id => <code className="evidence-id" key={id}>{id}</code>) : <em>No event recorded</em>}</div><ArrowRight size={18} /><div><small>Ledger entries</small>{line.entry_ids.length ? line.entry_ids.map(id => <code className="evidence-id" key={id}>{id}</code>) : <em>No posting recorded</em>}</div></div>) : <Empty>Reconstructing lineage from independent evidence…</Empty>}</div>
          </Panel>
          <Panel title="Evidence timeline" note={<span className="subtle">{incident.timeline.length} recorded events</span>}><div className="timeline">{incident.timeline.map((item, index) => <div className="timeline-item" key={index}><span className="timeline-node" /><time>{clock(item.ts)}</time><span className="timeline-kind">{label(item.kind)}</span><p>{display.humanize(item.detail)}<small className="mono evidence-id">{item.ref}</small></p></div>)}</div></Panel>
        </>}
      </section>

      <section id="sandbox">
        <SectionTitle number="04" title="Recovery Sandbox" subtitle="Prove the correction in isolation. A human decides whether it reaches the ledger." />
        {!incident?.proposal ? <Panel title="Isolated recovery environment"><Empty>No proposal yet. Recovery proposals appear here after investigation and containment.</Empty></Panel> : <>
          <div className="challenge-comparison">
            {incident.sandbox ? <div className={`sandbox-banner ${incident.sandbox.passed ? 'passed' : 'failed'}`}>{incident.sandbox.passed ? <ShieldCheck size={27} /> : <ShieldX size={27} />}<div><strong data-testid="sandbox-result">SANDBOX {incident.sandbox.passed ? 'PASSED' : 'FAILED'}</strong><p>{incident.sandbox.passed ? 'All seven checks pass on an isolated copy. The real ledger is untouched.' : 'Validation failed. Do not apply this proposal.'}</p>{incident.sandbox.passed && <span className="runner-badge" data-testid="sandbox-runner">{sandboxRunnerLabel(incident.sandbox)}</span>}</div><span className="method">Isolated copy</span></div> : <div className="sandbox-banner"><LoaderCircle className="spin" /><strong>Sandbox validation in progress</strong></div>}
            <div className="panel challenge-controls">
              <h3>Attempt unsafe correction</h3><p>Test a deliberately wrong candidate. Never apply it to the real ledger.</p>
              <div className="challenge-buttons">
                {([['wrong_amount', 'Wrong amount (+100 minor)'], ['reverse_original', 'Reverse original']] as const).map(([variant, title]) =>
                  <button className="button danger-outline" key={variant} disabled={!!pending || incident.status !== 'awaiting_approval'} onClick={() => { void attemptUnsafe(variant) }}>
                    {pending === 'challenge' ? <LoaderCircle className="spin" size={15} /> : <ShieldX size={15} />}{title}
                  </button>)}
              </div>
              {challenge && <div className={`challenge-result ${challenge.response.sandbox.passed ? 'passed' : 'failed'}`}>
                <strong data-testid="challenge-result">SANDBOX {challenge.response.sandbox.passed ? 'PASSED' : 'REJECTED'}</strong>
                <p>Variant: {label(challenge.response.variant)}</p>
                <ul className="rejection-reasons">{challenge.response.rejection_reasons.map((reason, index) => <li key={index}><strong>{label(reason.rule)}</strong><span>{display.humanize(reason.detail)}</span></li>)}</ul>
                <p data-testid="challenge-applied">{challenge.response.applied ? `Integrity checks after applying: ${challenge.response.sandbox.checks_after.filter(check => check.pass).length}/7` : 'Blocked before applying to the sandbox copy'}</p>
                <p className="ledger-proof">Real ledger {challenge.unchanged ? 'unchanged' : 'CHANGED'}: {challenge.before} entries before {challenge.before === challenge.after ? '=' : '≠'} {challenge.after} after</p>
              </div>}
              {result('challenge')}
            </div>
          </div>
          <Panel title="Proposed compensating entries" note={<span className="subtle">Human approval required</span>}><p className="panel-description">{incident.proposal.description}</p><EntryTable entries={incident.proposal.entries} /></Panel>
          {incident.sandbox && <>
            <Panel title="Balance simulation" note={<span className="subtle">Only changed accounts highlighted</span>}><div className="table-scroll"><table><thead><tr><th>Account</th><th className="right">Before</th><th className="right">After</th><th className="right">Difference</th></tr></thead><tbody>{Object.entries(incident.sandbox.balances_before).map(([account, before]) => {
              const after = incident.sandbox!.balances_after[account]
              return <tr className={before !== after ? 'changed-row' : 'unchanged-row'} key={account}><td><AccountView id={account} /></td><td className="right tabular">{money(before)}</td><td className="right tabular">{money(after)}</td><td className="right tabular">{before === after ? '–' : money(after - before)}</td></tr>
            })}</tbody></table></div></Panel>
            <div className="two-columns"><Panel title="Before correction"><Checks checks={incident.sandbox.checks_before} compact /></Panel><Panel title="After correction"><Checks checks={incident.sandbox.checks_after} compact /></Panel></div>
          </>}
          <div className="approval-card"><div><LockKeyhole size={21} /><span><strong>Human authorization required</strong><small>The agent proposes. It can never approve.</small></span></div><div className="approval-controls"><label>Approver<select aria-label="Approver" value={actor} onChange={event => setActor(event.target.value)}><option>ops.lead@bank</option><option>treasury@bank</option><option>blackbox-agent</option></select></label>
            {actionButton('reject', 'Reject proposal', '/incidents/' + incident.id + '/reject', '', incident.status !== 'awaiting_approval', { actor })}
            {actionButton('approve', 'Approve recovery', '/incidents/' + incident.id + '/approve', 'primary', incident.status !== 'awaiting_approval', { actor })}</div>
            <div className="approval-results">{result('approve')}{result('reject')}</div>
          </div>
        </>}
      </section>

      <section id="verification">
        <SectionTitle number="05" title="Recovery Verification" subtitle="Verify the real ledger. Preserve the original. Restore the service." />
        {incident?.verification ? <>
          <div className={`verification-hero ${incident.status === 'resolved' ? 'verified' : 'failed'}`}><span className="verification-icon">{incident.status === 'resolved' ? <ShieldCheck size={38} /> : <ShieldX size={38} />}</span><div><div className="overline">Real ledger verification</div><h2>{incident.status === 'resolved' ? 'INTEGRITY RESTORED' : 'VERIFICATION FAILED'}</h2><p>{incident.verification.checks.filter(check => check.pass).length}/7 checks passing · {incident.corrections.length} append-only correction{incident.corrections.length === 1 ? '' : 's'} · original history preserved</p></div><Badge value={incident.status} /></div>
          <Panel title="Verified integrity checks"><Checks checks={incident.verification.checks} /></Panel>
          <Panel title="Applied corrections" note={<span className="subtle">Original history preserved</span>}><EntryTable entries={corrections} originals /><div className="preserved">{corrections.map(entry => <p key={entry.id}><Check size={14} />{entry.corrects_entry_id ? <>Original preserved: <button className="text-link mono" onClick={() => { setLedgerOpen(true); setActive('bank'); requestAnimationFrame(() => document.getElementById('ledger-' + entry.corrects_entry_id)?.scrollIntoView({ block: 'start' })) }}>{display.journal(entry.corrects_entry_id)}</button></> : <>Missing/correct intent effect appended for <code>{display.reference(entry.instruction_id)}</code></>}</p>)}{incident.approval && <p><LockKeyhole size={14} />Approved by {incident.approval.actor} at {clock(incident.approval.at)}</p>}</div></Panel>
        </> : <Panel title="Post-recovery verification"><Empty>No corrections applied. Verification results appear after an authorized recovery.</Empty></Panel>}
        <div className="release-strip"><div><Radio size={20} /><span><strong>Release settlement-svc</strong><small>{overview?.volume.held ?? '–'} held instructions · service {service?.status ?? 'unavailable'}. Requires no open incidents.</small></span></div>{actionButton('release', 'Release settlement-svc', '/services/settlement-svc/release', 'primary', service?.status !== 'quarantined' || (overview?.open_incidents ?? 1) > 0)}{result('release')}</div>
        <Panel title="Audit trail" note={<span className="subtle">Latest {audit.length} records · All actions accountable</span>}><div className="table-scroll audit-scroll"><table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Reference / detail</th></tr></thead><tbody>{audit.map(record => <tr key={record.id}><td className="mono">{clock(record.ts)}</td><td>{record.actor}</td><td><span className="audit-action">{label(record.action)}</span></td><td><span>{display.humanize(record.ref ?? '–')}</span><small>{display.humanize(record.detail)}</small></td></tr>)}</tbody></table>{!audit.length && <Empty>No audit records received.</Empty>}</div></Panel>
      </section>
      <footer><span><Circle size={7} fill="currentColor" /> BLACKBOX / Independent by design</span><span>Synthetic data only · In-memory demo · No real payments</span></footer>
    </main>
  </div></DisplayContext.Provider>
}
