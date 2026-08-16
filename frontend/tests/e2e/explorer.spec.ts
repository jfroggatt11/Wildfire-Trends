import { expect, test, type Page } from '@playwright/test'

function collectClientErrors(page: Page) {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.stack || error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  return errors
}

async function openExplorer(page: Page) {
  await page.goto('/', { waitUntil: 'networkidle' })
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  await expect(page.locator('.atlas-marker').first()).toBeVisible()
}

test('all media scopes preserve events and open their detail panel', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const visibleCount = page.locator('.map-stat strong')
  await expect(visibleCount).toHaveText('4,159')

  for (const scope of ['affected', 'eu27', 'international', 'global']) {
    await page.locator('.scope-section select').selectOption(scope)
    await expect(visibleCount).toHaveText('4,159')
    await page.locator('.watchlist > button').first().click()
    await expect(page.locator('.event-drawer')).toBeVisible()
    await expect(page.locator('.event-error')).toHaveCount(0)
    await page.locator('.drawer-header .icon-button').click()
  }

  expect(errors).toEqual([])
})

test('January plus Global opens articles with nullable publication timestamps', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.locator('input[type="date"]').nth(1).fill('2025-01-31')
  await expect(page.locator('.map-stat strong')).toHaveText('304')
  await expect(page.locator('.watchlist > button').first()).toContainText('Forest fires in United States')

  for (const scope of ['affected', 'eu27', 'international', 'global']) {
    await page.locator('.scope-section select').selectOption(scope)
    await page.locator('.watchlist > button').first().click()
    await expect(page.locator('.event-error')).toHaveCount(0)
    await expect(page.locator('.event-drawer')).toContainText('Forest fires in United States')
    await page.locator('.drawer-header .icon-button').click()
  }

  await page.locator('.scope-section select').selectOption('global')
  await page.locator('.watchlist > button').first().click()

  for (const scope of ['affected', 'eu27', 'international', 'global']) {
    await page.locator('.scope-select select').selectOption(scope)
    await expect(page.locator('.event-error')).toHaveCount(0)
  }

  for (const tab of ['Attention', 'Geography', 'Articles', 'Methods', 'Briefing']) {
    await page.getByRole('tab', { name: tab }).click()
    await expect(page.locator('.event-error')).toHaveCount(0)
  }

  expect(errors).toEqual([])
})

test('article links expose political totals, signals and filtering', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.locator('input[type="date"]').nth(1).fill('2025-01-31')
  await page.locator('.scope-section select').selectOption('global')
  await page.locator('.watchlist > button').first().click()
  await page.getByRole('tab', { name: 'Articles' }).click()

  const allTotal = Number((await page.locator('.article-totals > div').first().locator('strong').textContent())?.replaceAll(',', ''))
  const politicalTotal = Number((await page.locator('.article-totals .political strong').textContent())?.replaceAll(',', ''))
  expect(allTotal).toBeGreaterThan(0)
  expect(politicalTotal).toBeGreaterThan(0)
  expect(politicalTotal).toBeLessThanOrEqual(allTotal)

  await page.getByRole('button', { name: /^Political/ }).click()
  await expect(page.locator('.article-list > a').first()).toHaveAttribute('data-political', 'true')
  await expect(page.locator('.article-list .political-indicator').first()).toHaveText('Political')
  await expect(page.locator('.article-list > a[data-political="false"]')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('clearing and keyboard-editing date filters never unmounts the explorer', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const endDate = page.locator('input[type="date"]').nth(1)
  await endDate.click()
  await endDate.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A')
  await endDate.press('Backspace')
  if (await endDate.inputValue()) await endDate.fill('')

  await expect(endDate).toHaveValue('')
  await expect(page.locator('.app-shell')).toBeVisible()
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  await expect(page.locator('.map-stat small')).toContainText('Open')

  await endDate.fill('2025-01-31')
  await expect(page.locator('.map-stat strong')).toHaveText('304')

  const startDate = page.locator('input[type="date"]').first()
  await startDate.fill('2025-02-01')
  await expect(page.locator('.map-stat strong')).toHaveText('0')
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  await startDate.fill('2025-01-01')
  await expect(page.locator('.map-stat strong')).toHaveText('304')
  expect(errors).toEqual([])
})

test('hazard and alert filters update map and sidebar together', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const visibleCount = page.locator('.map-stat strong')
  await page.getByRole('button', { name: 'Fire', exact: true }).click()
  await expect(visibleCount).toHaveText('718')
  await expect(page.locator('.section-label small').first()).toHaveText('718 events')

  await page.getByRole('button', { name: 'Green', exact: true }).click()
  await expect(visibleCount).not.toHaveText('718')
  await expect(page.locator('.event-error')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('event selection survives an embedded preview that blocks URL history', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.evaluate(() => {
    window.history.replaceState = () => {
      throw new DOMException('History blocked by embedded preview', 'SecurityError')
    }
  })
  await page.locator('.atlas-marker.event').first().click()
  await expect(page.locator('.event-drawer')).toBeVisible()
  await expect(page.locator('.event-error')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('search supports empty results and recovers to the full event set', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const search = page.locator('.search-field input')
  await search.fill('no-such-climate-event-country')
  await expect(page.locator('.map-stat strong')).toHaveText('0')
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  await expect(page.locator('.atlas-marker')).toHaveCount(0)

  await search.fill('italy')
  await expect(page.locator('.map-stat strong')).not.toHaveText('0')
  await expect(page.locator('.atlas-marker').first()).toBeVisible()

  await page.locator('.search-field button').click()
  await expect(page.locator('.map-stat strong')).toHaveText('4,159')
  expect(errors).toEqual([])
})
