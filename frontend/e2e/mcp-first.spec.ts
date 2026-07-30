import { expect, test } from '@playwright/test'
import { bootstrap, command, startHarness } from './support/vesper-harness'

test('MCP-first external capability surface exposes only generic local sandbox evidence', async ({ page }) => {
  const h = await startHarness()
  try {
    const token = await bootstrap(h.backendUrl)
    const registered = await command(h.backendUrl, token, '/api/mcp/local-sandbox', { server_id: 'e2e-sandbox', display_name: 'E2E Local MCP Sandbox' })
    expect(registered.ok).toBeTruthy()
    const discovery = await command(h.backendUrl, token, '/api/mcp/e2e-sandbox/discover', {})
    expect(discovery.ok).toBeTruthy()
    await page.goto(h.frontendUrl)
    await page.getByRole('button', { name: 'Connections' }).click()
    await expect(page.getByRole('heading', { name: 'Connections · External Capabilities' })).toBeVisible()
    await expect(page.getByText('E2E Local MCP Sandbox')).toBeVisible()
    await expect(page.getByText('Approved local/custom sandbox')).toBeVisible()
    await expect(page.getByText('sandbox.read').first()).toBeVisible()
    await expect(page.getByText(/MCP is a transport only/)).toBeVisible()
    await expect(page.getByText('Credentials are never displayed here.')).toBeVisible()
  } finally { await h.close() }
})
