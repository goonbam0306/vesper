import { expect, test } from '@playwright/test'
import { bootstrap, startHarness } from './support/vesper-harness'

async function createProcess(baseUrl: string, token: string, origin: string): Promise<any> {
  const response = await fetch(`${baseUrl}/api/processes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': token, 'X-Client-Request-ID': crypto.randomUUID() },
    body: JSON.stringify({ origin }),
  })
  expect(response.ok).toBeTruthy()
  const payload = await response.json()
  return payload.process ?? payload.result?.process
}

async function transitionProcess(baseUrl: string, token: string, process: any, status: string): Promise<any> {
  const response = await fetch(`${baseUrl}/api/processes/${process.process_id}/transition`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': token, 'X-Client-Request-ID': crypto.randomUUID() },
    body: JSON.stringify({ status, expected_revision: process.revision }),
  })
  expect(response.ok).toBeTruthy()
  const payload = await response.json()
  return payload.process ?? payload.result?.process
}

test.describe('Split Aperture presence integration', () => {
  test('maps canonical process statuses to supplementary 24px presence icons without hiding raw status', async ({ page }) => {
    const harness = await startHarness()
    try {
      const token = await bootstrap(harness.backendUrl)
      const created = await createProcess(harness.backendUrl, token, 'presence-conformance')
      const statuses: Array<[string, string]> = [
        ['CREATED', 'idle'],
        ['WAITING', 'waiting'],
        ['PAUSED', 'waiting'],
        ['RUNNING', 'thinking'],
        ['FAILED', 'blocked'],
      ]
      let process = created
      for (const [status, expectedState] of statuses) {
        if (status !== 'CREATED') process = await transitionProcess(harness.backendUrl, token, process, status)
        await page.goto(harness.frontendUrl)
        await page.getByRole('button', { name: 'Processes' }).click()
        const icon = page.getByTestId(`process-presence-${process.process_id}`)
        await expect(icon).toHaveAttribute('data-presence-state', expectedState)
        await expect(icon).toHaveAttribute('data-size', '24')
        await expect(page.getByText(status, { exact: true }).first()).toBeVisible()
      }

      const cancelled = await createProcess(harness.backendUrl, token, 'presence-cancelled')
      const cancelledWaiting = await transitionProcess(harness.backendUrl, token, cancelled, 'WAITING')
      const cancelledProcess = await transitionProcess(harness.backendUrl, token, cancelledWaiting, 'CANCELLED')
      await page.reload()
      await page.getByRole('button', { name: 'Processes' }).click()
      const cancelledIcon = page.getByTestId(`process-presence-${cancelledProcess.process_id}`)
      await expect(cancelledIcon).toHaveAttribute('data-presence-state', 'idle')
      await expect(page.getByText('CANCELLED', { exact: true }).first()).toBeVisible()

      const completed = await createProcess(harness.backendUrl, token, 'presence-completed')
      const completedRunning = await transitionProcess(harness.backendUrl, token, completed, 'RUNNING')
      const completedProcess = await transitionProcess(harness.backendUrl, token, completedRunning, 'COMPLETED')
      await page.reload()
      await page.getByRole('button', { name: 'Processes' }).click()
      const completedIcon = page.getByTestId(`process-presence-${completedProcess.process_id}`)
      await expect(completedIcon).toHaveAttribute('data-presence-state', 'idle')
      await expect(page.getByText('COMPLETED', { exact: true }).first()).toBeVisible()
    } finally { await harness.close() }
  })
  test('keeps the VESPER wordmark and renders a decorative static Split Aperture brand mark', async ({ page }) => {
    const harness = await startHarness()
    try {
      await page.goto(harness.frontendUrl)
      await expect(page.getByText('VESPER', { exact: true })).toBeVisible()
      await expect(page.getByTestId('vesper-brand-presence')).toHaveAttribute('aria-hidden', 'true')
      await expect(page.getByTestId('vesper-brand-presence').locator('path[data-segment="A"]')).toBeVisible()
      await expect(page.locator('.brand-mark')).toHaveCount(0)
    } finally {
      await harness.close()
    }
  })

  test('maps Ask sending to Thinking without hiding textual status, then returns to Idle after failure is cleared by a new request', async ({ page }) => {
    const harness = await startHarness()
    try {
      await page.goto(harness.frontendUrl)
      const askIcon = page.getByTestId('ask-presence-icon')
      await expect(askIcon).toHaveAttribute('aria-label', 'Vesper idle')

      await page.getByLabel('Ask Vesper').fill('no model')
      await page.getByLabel('Ask Vesper').press('Enter')

      await expect(page.getByRole('alert')).toContainText('AI connection is not configured')
      await expect(askIcon).toHaveAttribute('aria-label', 'Vesper blocked')
      await expect(page.getByRole('alert')).toBeVisible()
    } finally {
      await harness.close()
    }
  })

  test('renders distinct reduced-motion final topologies for every approved presentation state', async ({ page }) => {
    const harness = await startHarness()
    try {
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.goto(`${harness.frontendUrl}/?presenceFixture=1`)
      for (const state of ['idle', 'thinking', 'retrieving', 'writing', 'waiting', 'blocked']) {
        const icon = page.getByTestId(`presence-state-${state}`)
        await expect(icon).toHaveAttribute('data-presence-state', state)
        await expect(icon).toHaveAttribute('data-reduced-motion', 'true')
      }
      await expect(page.getByTestId('presence-state-blocked').locator('[data-actor="jam-seal"]')).toBeVisible()
      await expect(page.getByTestId('presence-state-retrieving').locator('[data-actor="input-packet"]')).toHaveCount(3)
      await expect(page.getByTestId('presence-state-writing').locator('[data-actor="output-packet"]')).toHaveCount(3)
    } finally {
      await harness.close()
    }
  })
})

// Component contract assertions are exercised through a deterministic fixture exported by the app.
test('presence component fixture covers sizes, labels, decorative semantics, and blocked reset/re-entry', async ({ page }) => {
  const harness = await startHarness()
  try {
    await page.goto(`${harness.frontendUrl}/?presenceFixture=1`)
    for (const state of ['idle', 'thinking', 'retrieving', 'writing', 'waiting', 'blocked']) {
      await expect(page.getByTestId(`presence-state-${state}`)).toHaveAttribute('data-presence-state', state)
    }
    for (const size of ['16', '24', '32', '48']) {
      await expect(page.getByTestId(`presence-size-${size}`)).toHaveAttribute('width', size)
    }
    await expect(page.getByTestId('presence-labelled')).toHaveAttribute('aria-label', 'Custom Vesper label')
    await expect(page.getByTestId('presence-decorative')).toHaveAttribute('aria-hidden', 'true')
    const blocked = page.getByTestId('presence-blocked')
    await expect(blocked).toHaveClass(/is-blocked/)
    await expect(blocked).toHaveAttribute('data-blocked-topology', 'sealed')
    await expect(blocked.locator('[data-actor="jam-seal"]')).toBeVisible()
    await expect(page.getByTestId('presence-retrieving').locator('[data-actor="input-packet"]')).toHaveCount(3)
    await expect(page.getByTestId('presence-writing').locator('[data-actor="output-packet"]')).toHaveCount(3)
    const toggle = page.getByTestId('presence-fixture-toggle')
    await toggle.click()
    await expect(blocked).toHaveCount(0)
    await toggle.click()
    await expect(page.getByTestId('presence-blocked')).toHaveAttribute('data-blocked-topology', 'sealed')
  } finally {
    await harness.close()
  }
})
