import { test, expect } from '@playwright/test'
import { startHarness } from './support/vesper-harness'

test('Lane dashboard registers and activates a Lane through the local contract', async ({ page }) => {
  const harness = await startHarness()
  try {
    await page.goto(`${harness.backendUrl}/dashboard/lanes`)
    await expect(page.getByRole('heading', { name: 'Lane Management' })).toBeVisible()
    await page.getByLabel('Lane ID').fill('browser-e2e-lane')
    await page.getByLabel('Purpose').fill('browser registration fixture')
    await page.getByRole('button', { name: 'Register Lane' }).click()
    await expect(page.locator('#lanes')).toContainText('browser-e2e-lane')
    await expect(page.locator('#lanes')).toContainText('"enabled":false')
    await page.getByRole('button', { name: 'Enable' }).click()
    await expect(page.locator('#lane-action-result')).toContainText('"enabled":true')
  } finally {
    await harness.close()
  }
})


test('Lane dashboard handles duplicate registration without corrupting the registry', async ({ page }) => {
  const harness = await startHarness()
  try {
    await page.goto(`${harness.backendUrl}/dashboard/lanes`)
    for (const purpose of ['first registration', 'duplicate registration']) {
      await page.getByLabel('Lane ID').fill('duplicate-e2e-lane')
      await page.getByLabel('Purpose').fill(purpose)
      await page.getByRole('button', { name: 'Register Lane' }).click()
    }
    await expect(page.locator('#registration-result')).toContainText('duplicate-e2e-lane')
    await expect(page.locator('#lanes')).toContainText('duplicate-e2e-lane')
  } finally {
    await harness.close()
  }
})

