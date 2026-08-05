import { expect, test } from '@playwright/test'
import { startHarness } from './support/vesper-harness'

test.describe('deterministic design review fixture', () => {
  test('renders the approved desktop shell, presentation-only Aurora, and responsive inspection surfaces', async ({ page }) => {
    const harness = await startHarness()
    try {
      await page.goto(`${harness.frontendUrl}/?designReviewFixture=1`)

      await expect(page.getByTestId('design-review-fixture')).toBeVisible()
      await expect(page.getByText('DEMO · DETERMINISTIC REVIEW DATA')).toBeVisible()
      await expect(page.getByTestId('desktop-shell')).toBeVisible()
      await expect(page.getByTestId('sidebar')).toBeVisible()
      await expect(page.getByTestId('workspace')).toBeVisible()
      await expect(page.getByTestId('inspector')).toBeVisible()
      await expect(page.getByTestId('aurora-layer')).toHaveAttribute('data-aurora-mode', 'presentation')
      await expect(page.getByTestId('aurora-layer')).toHaveAttribute('data-aurora-opacity', '50')
      await expect(page.getByTestId('aurora-layer')).not.toHaveAttribute('data-aurora-source', /ask|process|loading/i)
      await expect(page.getByTestId('fixture-process-running')).toHaveAttribute('data-presence-state', 'thinking')
      await expect(page.getByTestId('fixture-retrieve')).toHaveCount(0)
      await expect(page.getByTestId('fixture-writing')).toHaveCount(0)
      await page.screenshot({ path: 'test-results/design-review-desktop.png', fullPage: true })

      await page.setViewportSize({ width: 900, height: 900 })
      await expect(page.getByTestId('desktop-shell')).toHaveAttribute('data-layout', 'compact')
      await expect(page.getByTestId('sidebar')).toHaveAttribute('data-collapsed', 'true')
      await expect(page.getByTestId('inspector')).toHaveAttribute('data-drawer', 'true')
      await page.screenshot({ path: 'test-results/design-review-tablet.png', fullPage: true })

      await page.setViewportSize({ width: 390, height: 844 })
      await expect(page.getByTestId('desktop-shell')).toHaveAttribute('data-layout', 'compact')
      expect(await page.locator('body').evaluate(body => body.scrollWidth <= window.innerWidth)).toBe(true)
      await page.screenshot({ path: 'test-results/design-review-mobile.png', fullPage: true })

      await page.emulateMedia({ reducedMotion: 'reduce' })
      await expect(page.getByTestId('aurora-layer')).toHaveAttribute('data-aurora-active', 'true')
      await expect(page.getByTestId('aurora-layer')).toHaveCSS('animation-name', 'none')
      await page.screenshot({ path: 'test-results/design-review-reduced-motion.png', fullPage: true })
    } finally {
      await harness.close()
    }
  })
})

test('first boot uses the approved setup shell without network fixture content', async ({ page }) => {
  const harness = await startHarness({ firstBootCompleted: false })
  try {
    await page.goto(harness.frontendUrl)
    await expect(page.getByTestId('first-boot-shell')).toBeVisible()
    await expect(page.getByTestId('first-boot-orbit')).toBeVisible()
    await expect(page.getByTestId('first-boot-panel')).toBeVisible()
  } finally {
    await harness.close()
  }
})
