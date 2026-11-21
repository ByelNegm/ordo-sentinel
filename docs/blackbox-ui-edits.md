# BLACKBOX console — UI edits on top of variant B

Applies to `frontend/` on branch `pivot/blackbox` (commit 6d20a10).
Two files change: `frontend/src/App.tsx` (3 places) and `frontend/src/styles.css` (7 lines appended).
Presentation only: no API, state or workflow logic changes.

Same changes as a git patch: `console-readability.patch`
Same changes as a pull request: https://github.com/ByelNegm/ordo-sentinel/pull/10

## 1. `frontend/src/App.tsx`

### 1.1 Larger 403 block

Replace

```tsx
<span>{display.humanize(results[key].text)}</span>
```

with

```tsx
<span className={results[key].text.startsWith('HTTP 403') ? 'forbidden' : ''}>{display.humanize(results[key].text)}</span>
```

### 1.2 "Balanced ≠ correct" banner

Insert this line directly before `<Panel title="Independent integrity checks" ...>`:

```tsx
{overview && <div className={`balance-banner ${status === 'healthy' ? '' : 'alert'}`}><strong>{balanced ? 'Debits = credits.' : 'Debits ≠ credits.'}</strong> {status === 'healthy' ? 'A balanced ledger alone does not prove correctness — balanced ≠ correct.' : balanced ? `The ledger still balances, but integrity is ${status?.toUpperCase()} — balanced ≠ correct.` : `Integrity is ${status?.toUpperCase()}.`}</div>}
```

### 1.3 Rejected / Failed step

Inside `<div className="stepper">`, replace the ending

```tsx
<b>{label(stage)}</b></div>)}</div>
```

with

```tsx
<b>{label(stage)}</b></div>)}{['rejected', 'failed'].includes(incident.status) && <div className="step terminal"><span>✕</span><b>{label(incident.status)}</b></div>}</div>
```

## 2. `frontend/src/styles.css`

Append to the end of the file:

```css
html{zoom:1.2}
.top-integrity .badge{font-size:15px;padding:7px 14px;letter-spacing:.06em}
.incident-header .badge{font-size:12px;padding:5px 10px}
.balance-banner{border:1px solid var(--line);background:#10161f;color:#9fb0c5;border-radius:7px;padding:13px 18px;font-size:13px;margin-bottom:18px}.balance-banner.alert{border-color:#8a3a48;background:#301c25;color:var(--red)}
.step.terminal{color:var(--red);border-top-color:var(--red)}.stepper:has(.terminal){grid-template-columns:repeat(8,1fr)}
.error-result:has(.forbidden){background:#3a1820;border:1px solid var(--red);border-radius:6px;padding:9px 14px;margin-top:12px;align-items:center;width:fit-content}.error-result:has(.forbidden) svg{width:16px;height:16px}.forbidden{font-size:13px;font-weight:600;color:var(--red)}
```

What each CSS line does:

| Line | Effect |
|---|---|
| 1 | Whole console at 120% |
| 2 | Larger integrity badge in the top bar |
| 3 | Larger incident status badge |
| 4 | "Balanced ≠ correct" banner (neutral when healthy, red otherwise) |
| 5 | Red terminal step for Rejected / Failed, stepper becomes 8 columns |
| 6 | 403 message as a bordered red block |

## Verification

- `tsc --noEmit`, `npm test` (31 passed), `npm run build` pass on `pivot/blackbox` @ 6d20a10.
- Duplicate flow driven in a browser up to the 403 and a rejection, on the previous `ui/blackbox-console` head.
- Not verified: full run through Release after the rebase, Missing/Tamper flows, the `failed` step.
- Known issue: at 120% zoom, rail navigation can stop 20–30px above the section heading.
