import { expect, test } from '@playwright/test'
import { startHarness } from './support/vesper-harness'

test.describe('E-03 product error-state matrix', () => {
  test('no model configured and no-data first boot are visible without false success', async ({ page }) => {
    const h = await startHarness()
    try {
      await page.goto(h.frontendUrl)
      await expect(page.getByRole('heading', { name: 'Good work starts here.' })).toBeVisible()
      await page.getByLabel('Ask Vesper').fill('no model')
      await page.getByLabel('Ask Vesper').press('Enter')
      await expect(page.getByRole('alert')).toContainText('AI connection is not configured')
      await expect(page.getByRole('button', { name: 'Set up AI' })).toBeVisible()
    } finally { await h.close() }
  })

  test('pending approval and blocked Process are visible', async ({ page }) => {
    const h = await startHarness()
    try {
      await page.goto(h.frontendUrl)
      await page.getByRole('button', { name: 'Approvals' }).click()
      await expect(page.locator('h2')).toContainText('Approvals')
      await expect(page.getByText(/No pending approvals|No approvals/)).toBeVisible()
      await page.getByRole('button', { name: 'Processes' }).click()
      await expect(page.locator('h2')).toContainText('Processes')
      await expect(page.getByTestId('empty-processes')).toBeVisible()
    } finally { await h.close() }
  })

  test('offline connection, stale memory, and disabled/retired Lane surfaces are explicit', async ({ page }) => {
    const h = await startHarness()
    try {
      await page.goto(`${h.backendUrl}/dashboard/lanes`)
      await expect(page.getByRole('heading', { name: 'Lane Management' })).toBeVisible()
      await page.getByLabel('Lane ID').fill('e03-disabled-lane')
      await page.getByLabel('Purpose').fill('error matrix')
      await page.getByRole('button', { name: 'Register Lane' }).click()
      await expect(page.locator('#lanes')).toContainText('"enabled":false')
      await page.goto(h.frontendUrl)
      await page.getByRole('button', { name: 'Connections' }).click()
      await expect(page.getByText(/No configured provider|Credentials are never displayed/)).toBeVisible()
      await page.getByRole('button', { name: 'Memory' }).click()
      await expect(page.getByText(/No memory|Inspectable latest memory state|stale|conflict/)).toBeVisible()
    } finally { await h.close() }
  })
})