import { chromium, expect } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const output = process.env.UI_EVIDENCE_DIR || '/home/ubuntu/blackbox-evidence/ui'
await mkdir(output, { recursive: true })
const browser = await chromium.connectOverCDP(process.env.CDP_URL || 'http://localhost:29229')
const context = await browser.newContext({ viewport: { width: 1440, height: 1200 }, reducedMotion: 'reduce' })
const page = await context.newPage()
const errors = [], requests = [], results = []
page.on('pageerror', error => errors.push(error.message))
page.on('response', response => {
  if (response.request().method() === 'POST') requests.push({ path: new URL(response.url()).pathname, status: response.status() })
})
const nav = title => page.getByRole('navigation', { name: 'Sections' }).getByRole('button', { name: title }).click()
const backend = endpoint => page.evaluate(async endpoint => {
  const response = await fetch('/api' + endpoint)
  if (!response.ok) throw new Error('HTTP ' + response.status)
  return response.json()
}, endpoint)
const screenshot = name => page.screenshot({ path: path.join(output, name + '.png'), animations: 'disabled' })
const assertDisplay = async () => {
  const text = await page.locator('main').evaluate(main => {
    const clone = main.cloneNode(true)
    clone.querySelectorAll('.lineages, .timeline').forEach(element => element.remove())
    return clone.textContent
  })
  expect(text).not.toMatch(/customer-\d+|payment-\d+|entry-\d+|event-\d+|incident-\d+/)
  expect(text).not.toContain('information unavailable')
  expect(text).not.toContain('reference unavailable')
}
const reset = async () => {
  await nav('Attack Simulator')
  await page.getByRole('button', { name: 'Reset baseline', exact: true }).click()
  await expect(page.getByTestId('checks-passed')).toHaveText('7/7 checks')
  await expect(page.getByTestId('incident-status')).toHaveCount(0)
  await expect(page.getByTestId('workflow-next')).toHaveText('Start live traffic')
  await expect.poll(async () => (await backend('/overview')).volume.instructions).toBe(100)
}
const aligned = async section => {
  await expect.poll(async () => page.locator('#' + section + (section === 'bank' ? '' : ' .section-title')).evaluate(element =>
    Math.abs(element.getBoundingClientRect().top - parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--workspace-offset'))))).toBeLessThan(3)
}

try {
  await page.goto(process.env.UI_URL || 'http://localhost:5173')
  await expect(page.getByTestId('checks-passed')).toHaveText('7/7 checks')
  for (const kind of ['duplicate', 'tamper']) {
    await reset()
    await nav('Bank Operations')
    await aligned('bank')
    await assertDisplay()
    await expect(page.locator('.payment-scroll')).toContainText(/FT26325[A-Z0-9]{5}/)
    await expect(page.locator('.payment-scroll')).toContainText(/AE\d{2} 033\d •••• \d{4}/)
    if (kind === 'duplicate') await screenshot('v2_healthy')
    await page.getByTestId('workflow-next').click()
    await expect(page.locator('[data-action="traffic"]')).toHaveClass(/next-control-pulse/)
    await page.getByRole('button', { name: 'Start traffic', exact: true }).click()
    await expect(page.getByTestId('workflow-next')).toHaveText('Choose a fault to inject')
    await page.getByTestId('workflow-next').click()
    await expect(page.locator('[data-action="duplicate"]')).toHaveClass(/next-control-pulse/)
    const started = performance.now()
    await page.getByRole('button', { name: kind === 'duplicate' ? 'Inject Duplicate Settlement' : 'Inject Tampered Settlement', exact: true }).click()
    await expect(page.getByTestId('integrity-status')).toHaveText('VIOLATED', { timeout: 20000 })
    await expect(page.getByTestId('incident-summary')).toBeInViewport({ ratio: 1 })
    await expect(page.getByTestId('incident-summary')).toContainText(kind === 'duplicate' ? 'settled twice' : 'instead of')
    await aligned('investigation')
    await assertDisplay()
    await nav('Bank Operations')
    if (kind === 'duplicate') {
      await expect(page.locator('.effect.duplicate').first()).toHaveText('×2')
      await screenshot('v2_violated')
    }
    await expect(page.getByTestId('sandbox-result')).toHaveText('SANDBOX PASSED', { timeout: 20000 })
    await expect(page.getByTestId('workflow-caption')).toHaveText('Optionally test an unsafe correction, then approve')
    await expect(page.getByTestId('sandbox-result')).toBeInViewport({ ratio: 1 })
    await aligned('sandbox')
    const awaitingSeconds = +((performance.now() - started) / 1000).toFixed(3)
    await page.getByRole('button', { name: 'Wrong amount (+100 minor)', exact: true }).click()
    await expect(page.getByTestId('challenge-result')).toHaveText('SANDBOX REJECTED')
    await expect(page.getByTestId('challenge-applied')).toHaveText('Blocked before applying to the sandbox copy')
    await expect(page.locator('.rejection-reasons')).toContainText('ledger guard')
    await page.getByRole('button', { name: 'Reverse original', exact: true }).click()
    await expect(page.getByTestId('challenge-applied')).toHaveText('Integrity checks after applying: ' + (kind === 'duplicate' ? '7/7' : '5/7'))
    await expect(page.locator('.rejection-reasons')).toContainText(kind === 'duplicate' ? 'lineage guard' : 'intent guard')
    await expect(page.getByText(/Real ledger unchanged: \d+ entries before = \d+ after/)).toBeVisible()
    await nav('Recovery Sandbox')
    await assertDisplay()
    if (kind === 'duplicate') await screenshot('v2_sandbox')
    await page.getByRole('combobox', { name: 'Approver' }).selectOption('blackbox-agent')
    await page.getByRole('button', { name: 'Approve recovery', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('HTTP 403 · Actor is not an authorized approver')
    await expect(page.getByTestId('incident-status')).toHaveText('awaiting approval')
    await page.getByRole('combobox', { name: 'Approver' }).selectOption('ops.lead@bank')
    await page.getByRole('button', { name: 'Approve recovery', exact: true }).click()
    await expect(page.getByTestId('incident-status')).toHaveText('resolved')
    await expect(page.getByRole('heading', { name: 'INTEGRITY RESTORED', exact: true })).toBeInViewport({ ratio: 1 })
    await expect(page.getByTestId('checks-passed')).toHaveText('7/7 checks')
    await expect(page.getByTestId('workflow-next')).toHaveText('Release settlement-svc')
    await aligned('verification')
    await assertDisplay()
    await screenshot(kind === 'duplicate' ? 'v2_resolved' : 'v2_tamper_resolved')
    await page.getByTestId('workflow-next').click()
    await expect(page.locator('[data-action="release"]')).toHaveClass(/next-control-pulse/)
    await page.getByRole('button', { name: 'Release settlement-svc', exact: true }).click()
    await expect.poll(async () => (await backend('/overview')).volume.held).toBe(0)
    await expect(page.getByTestId('workflow-next')).toHaveText('Reset baseline')
    await reset()
    results.push({ kind, result: 'PASS', injectToAwaitingSeconds: awaitingSeconds })
    console.log('PASS v2 UI ' + kind + ': named payment / masked IBAN -> live guide / aligned auto-scroll -> truthful rejected challenges -> agent 403 -> approval / 7/7 -> release -> reset')
  }
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.getByTestId('workflow-next').click()
  await page.waitForFunction(() => {
    const target = document.querySelector('#simulator .section-title')
    const offset = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--workspace-offset'))
    return window.scrollY > 0 && target.getBoundingClientRect().top > offset + 10
  })
  await aligned('simulator')
  await page.waitForFunction(() => {
    const style = getComputedStyle(document.querySelector('[data-action="traffic"]'))
    return style.animationName === 'next-control-pulse' && parseFloat(style.outlineWidth) > 0
  })
  await screenshot('v2_guided_control')
  console.log('PASS normal-motion guide: smooth scroll observed; next control visibly pulses')
  expect(errors).toEqual([])
  const final = await backend('/overview')
  expect(final.traffic_running).toBe(false)
  expect(final.integrity.status).toBe('healthy')
  expect(final.services[0].status).toBe('running')
  await writeFile(path.join(output, 'acceptance_v2.json'), JSON.stringify({ results, requests, errors, final }, null, 2))
  console.log('PASS browser runtime: no uncaught errors; bank reset')
  process.exit(0)
} catch (error) {
  await screenshot('v2_failure')
  console.error(error)
  process.exit(1)
}
