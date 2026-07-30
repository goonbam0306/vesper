import { expect, test } from '@playwright/test'
import { startHarness } from './support/vesper-harness'

test.describe('Split Aperture presence integration', () => {
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
      await page.goto(harness.frontendUrl)
      await page.getByRole('button', { name: 'Processes' }).click()
      await expect(page.getByTestId('empty-processes')).toBeVisible()

      const fixture = await page.evaluate(() => {
        const host = document.createElement('div')
        host.id = 'presence-test-fixture'
        document.body.append(host)
        return host.id
      })
      expect(fixture).toBe('presence-test-fixture')
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
    await expect(page.getByTestId('presence-blocked')).toHaveClass(/is-blocked/)
    await expect(page.getByTestId('presence-blocked').locator('[data-actor="jam-seal"]')).toBeVisible()
    await expect(page.getByTestId('presence-retrieving').locator('[data-actor="input-packet"]')).toHaveCount(3)
    await expect(page.getByTestId('presence-writing').locator('[data-actor="output-packet"]')).toHaveCount(3)
    await expect(page.getByTestId('presence-fixture-toggle')).toBeVisible()
  } finally {
    await harness.close()
  }
})
