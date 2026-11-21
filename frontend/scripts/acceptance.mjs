import { chromium, expect } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const output = process.env.UI_EVIDENCE_DIR || '/home/ubuntu/blackbox-evidence/ui'
await mkdir(output, { recursive: true })
const browser = await chromium.connectOverCDP(process.env.CDP_URL || 'http://localhost:29229')
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce' })
const page = await context.newPage()
const errors = []
const requests = []
page.on('pageerror', error => errors.push(error.message))
page.on('response', response => {
  if (response.request().method() === 'POST' && response.url().includes('/api/')) {
    requests.push({ path: new URL(response.url()).pathname, status: response.status() })
  }
})
const nav = title => page.getByRole('navigation', { name: 'Sections' }).getByRole('button', { name: title, exact: false }).click()
const backend = endpoint => page.evaluate(async endpoint => {
  const response = await fetch('/api' + endpoint)
  if (!response.ok) throw new Error('GET failed: ' + response.status)
  return response.json()
}, endpoint)
const screenshot = name => page.screenshot({ path: path.join(output, name + '.png'), animations: 'disabled' })

try {
  await page.goto(process.env.UI_URL || 'http://localhost:5173')
  await expect(page.getByTestId('integrity-status')).toHaveText('HEALTHY')
  await nav('Attack Simulator')
  await page.getByRole('button', { name: 'Reset baseline', exact: true }).click()
  await expect(page.getByText('HTTP 200 · Baseline restored · 100 settled payments')).toBeVisible()
  await nav('Bank Operations')
  await expect(page.getByTestId('checks-passed')).toHaveText('7/7 checks')
  await expect(page.getByRole('heading', { name: 'Trust, independently verified.' })).toBeInViewport({ ratio: 1 })
  await screenshot('healthy')

  await nav('Attack Simulator')
  await page.getByRole('button', { name: 'Start traffic', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Stop traffic', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Inject Duplicate Settlement', exact: true }).click()
  await nav('Bank Operations')
  await expect(page.getByTestId('integrity-status')).toHaveText('VIOLATED', { timeout: 15000 })
  await expect(page.locator('.effect.duplicate').first()).toHaveText('×2')
  await expect(page.getByText('Balanced. But not correct.', { exact: true })).toBeInViewport({ ratio: 1 })
  await screenshot('violated')

  await nav('Recovery Sandbox')
  await expect(page.getByTestId('sandbox-result')).toHaveText('SANDBOX PASSED', { timeout: 15000 })
  await expect(page.getByTestId('incident-status')).toHaveText('awaiting approval')
  await page.getByRole('combobox', { name: 'Approver' }).selectOption('blackbox-agent')
  await page.getByRole('button', { name: 'Approve recovery', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('HTTP 403 · Actor is not an authorized approver')
  await expect(page.getByTestId('incident-status')).toHaveText('awaiting approval')
  await page.setViewportSize({ width: 1440, height: 2000 })
  await nav('Recovery Sandbox')
  await expect(page.getByTestId('sandbox-result')).toBeInViewport({ ratio: 1 })
  await expect(page.getByRole('alert')).toBeInViewport({ ratio: 1 })
  await screenshot('awaiting_approval')
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.getByRole('combobox', { name: 'Approver' }).selectOption('ops.lead@bank')
  await page.getByRole('button', { name: 'Approve recovery', exact: true }).click()
  await expect(page.getByTestId('incident-status')).toHaveText('resolved')
  await nav('Recovery Verification')
  await expect(page.getByRole('heading', { name: 'INTEGRITY RESTORED', exact: true })).toBeInViewport({ ratio: 1 })
  await expect(page.getByTestId('integrity-status')).toHaveText('HEALTHY')
  await expect(page.getByTestId('checks-passed')).toHaveText('7/7 checks')
  await expect(page.getByText('Original preserved:', { exact: false })).toBeVisible()
  await screenshot('resolved')

  await page.getByRole('button', { name: 'Release settlement-svc', exact: true }).click()
  await expect(page.getByText('HTTP 200 · settlement-svc · running', { exact: true })).toBeVisible()
  await expect.poll(async () => (await backend('/overview')).volume.held).toBe(0)
  await nav('Attack Simulator')
  await page.getByRole('button', { name: 'Stop traffic', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Start traffic', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Reset baseline', exact: true }).click()
  await expect(page.getByTestId('integrity-status')).toHaveText('HEALTHY')
  await expect(page.getByTestId('checks-passed')).toHaveText('7/7 checks')
  await expect.poll(async () => (await backend('/overview')).volume.instructions).toBe(100)
  console.log('PASS UI acceptance: reset -> traffic -> duplicate -> VIOLATED / ×2 -> sandbox PASSED -> agent 403 -> ops approval -> INTEGRITY RESTORED / 7/7 -> release -> reset')

  for (const [kind, title] of [['missing', 'Missing Settlement'], ['tamper', 'Tampered Settlement']]) {
    await page.getByRole('button', { name: 'Inject ' + title, exact: true }).click()
    await expect(page.getByText('HTTP 200 · ' + kind + ' fault armed', { exact: true })).toBeVisible()
    await expect.poll(async () => (await backend('/overview')).services[0].fault).toBe(kind)
    await page.getByRole('button', { name: 'Reset baseline', exact: true }).click()
    await expect.poll(async () => (await backend('/overview')).services[0].fault).toBe(null)
  }
  console.log('PASS UI P2 controls: missing and tamper each armed the real backend fault; reset cleared each')
  await nav('Bank Operations')
  expect(errors).toEqual([])
  expect(requests).toContainEqual({ path: '/api/incidents/incident-0001/approve', status: 403 })
  expect(requests).toContainEqual({ path: '/api/incidents/incident-0001/approve', status: 200 })
  await writeFile(path.join(output, 'acceptance.json'), JSON.stringify({ requests, errors, final: await backend('/overview') }, null, 2))
  console.log('PASS browser runtime: no uncaught page errors')
  console.log('Screenshots: ' + ['healthy', 'violated', 'awaiting_approval', 'resolved'].map(name => path.join(output, name + '.png')).join(', '))
  process.exit(0)
} catch (error) {
  await screenshot('failure')
  console.error(error)
  process.exit(1)
}
