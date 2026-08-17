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

test('January plus Global opens aggregate attention across every media scope', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.locator('input[type="date"]').nth(1).fill('2025-01-31')
  await expect(page.locator('.map-stat strong')).toHaveText('304')
  await expect(page.locator('.watchlist > button').first()).toContainText('Wildfire in United States')

  for (const scope of ['affected', 'eu27', 'international', 'global']) {
    await page.locator('.scope-section select').selectOption(scope)
    await page.locator('.watchlist > button').first().click()
    await expect(page.locator('.event-error')).toHaveCount(0)
    await expect(page.locator('.event-drawer')).toContainText('Wildfire in United States')
    await page.locator('.drawer-header .icon-button').click()
  }

  await page.locator('.scope-section select').selectOption('global')
  await page.locator('.watchlist > button').first().click()

  for (const scope of ['affected', 'eu27', 'international', 'global']) {
    await page.locator('.scope-select select').selectOption(scope)
    await expect(page.locator('.event-error')).toHaveCount(0)
  }

  await expect(page.getByRole('tab')).toHaveCount(2)
  await expect(page.getByRole('tab', { name: 'Attention' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: 'Coverage breakdown' })).toHaveCount(1)
  for (const removedTab of ['Articles', 'Briefing', 'Geography', 'Methods']) {
    await expect(page.getByRole('tab', { name: removedTab })).toHaveCount(0)
  }
  await expect(page.getByRole('heading', { name: /Topic coverage around the event/ })).toBeVisible()

  expect(errors).toEqual([])
})

test('attention toggle and before-after analysis share the selected measure', async ({ page }) => {
  const errors = collectClientErrors(page)
  await page.goto('/?event=gdacs%3AWF%3A1023505', { waitUntil: 'networkidle' })
  await expect(page.locator('.event-drawer')).toBeVisible()
  await page.locator('.scope-select select').selectOption('global')

  const cards = page.locator('.before-after-card')
  await expect(cards).toHaveCount(2)
  await expect(page.locator('.before-after-card[data-test-status="unavailable"]')).toHaveCount(0)
  await expect(cards.first()).toContainText('URLs/day')
  await expect(cards.first()).toContainText('One-sided p =')
  await expect(page.locator('.recharts-reference-line')).toHaveCount(2)
  await expect(page.locator('.chart-wrap')).toContainText('Starts ·')
  await expect(page.locator('.chart-wrap')).toContainText('Ends ·')
  await expect(page.locator('.chart-wrap')).toContainText('Event duration')
  const allArticleResult = await cards.first().textContent()

  await page.getByRole('button', { name: 'Political only' }).click()
  await expect(page.getByRole('button', { name: 'Political only' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('heading', { name: /Political topic coverage around the event/ })).toBeVisible()
  await expect.poll(async () => cards.first().textContent()).not.toBe(allArticleResult)

  await page.getByLabel('Comparison window').selectOption('28')
  await expect(page.locator('.before-after-card[data-test-status="unavailable"]')).toHaveCount(0)
  await expect(cards.first()).toContainText('URLs/day')
  expect(errors).toEqual([])
})

test('coverage breakdown replaces article links with aggregate timing, political and market views', async ({ page }) => {
  const errors = collectClientErrors(page)
  await page.goto('/?event=gdacs%3AWF%3A1023505', { waitUntil: 'networkidle' })
  await expect(page.locator('.event-drawer')).toBeVisible()
  await page.locator('.scope-select select').selectOption('global')
  await page.getByRole('tab', { name: 'Coverage breakdown' }).click()

  await expect(page.getByRole('heading', { name: 'What changed, and where?' })).toBeVisible()
  await expect(page.locator('.coverage-summary strong').first()).not.toHaveText('0')
  await expect(page.getByRole('table', { name: 'Average daily coverage before, during and after the event' })).toBeVisible()
  await expect(page.locator('.phase-table > div[data-topic]')).toHaveCount(2)
  await expect(page.locator('.political-signal-summary > div')).toHaveCount(4)
  await expect(page.locator('.market-ranking button').first()).toBeVisible()
  await expect(page.locator('.article-list')).toHaveCount(0)
  await expect(page.locator('.drawer-content a[href^="http"]')).toHaveCount(0)

  const market = page.locator('.market-ranking button').first()
  const marketName = (await market.locator('span').textContent()) || ''
  await market.click()
  await expect(page.locator('.coverage-toolbar select').nth(1)).not.toHaveValue('all')
  await expect(page.locator('.coverage-breakdown')).toContainText(marketName)
  expect(errors).toEqual([])
})

test('trackpad-style zoom stays inside the map and clusters reveal individual events', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  const map = page.locator('.atlas-svg-map')
  const svg = map.locator(':scope > svg')
  await expect(svg).toHaveAttribute('data-zoom', '1.000')

  const prevented = await map.evaluate((element) => !element.dispatchEvent(new WheelEvent('wheel', {
    bubbles: true,
    cancelable: true,
    clientX: element.getBoundingClientRect().left + element.clientWidth / 2,
    clientY: element.getBoundingClientRect().top + element.clientHeight / 2,
    deltaY: -160,
    ctrlKey: true,
  })))
  expect(prevented).toBe(true)
  await expect.poll(async () => Number(await svg.getAttribute('data-zoom'))).toBeGreaterThan(1)

  await page.getByRole('button', { name: 'Reset world view' }).click()
  // SVG paints later markers on top; target the topmost visible cluster just as a user would.
  const cluster = page.locator('.atlas-marker.cluster').last()
  const clusterCount = Number(await cluster.getAttribute('data-count'))
  expect(clusterCount).toBeGreaterThan(1)
  await cluster.click()
  await expect(map).toHaveAttribute('data-camera-animating', 'true')
  await expect(page.locator('.atlas-marker.event[data-expanded="true"]')).toHaveCount(0)
  await expect(map).toHaveAttribute('data-camera-animating', 'false')
  await expect.poll(async () => Number(await svg.getAttribute('data-zoom'))).toBeGreaterThanOrEqual(7)
  await expect(page.locator('.atlas-marker.event[data-expanded="true"]')).toHaveCount(clusterCount)
  expect(errors).toEqual([])
})

test('event drawer keeps the corrected map-point label without a geography tab', async ({ page }) => {
  const errors = collectClientErrors(page)
  await page.goto('/?event=gdacs%3AFL%3A1103661', { waitUntil: 'networkidle' })
  await expect(page.locator('.event-drawer')).toBeVisible()
  await expect(page.locator('.drawer-header h2')).toHaveText('Flood in United Kingdom')
  await expect(page.locator('.event-meta')).toContainText('Map point: Cornwall, United Kingdom')
  await expect(page.locator('.event-meta')).toContainText('50.42°N, 4.75°W')
  await expect(page.locator('.event-meta')).toContainText('Affected: Ireland, United Kingdom')
  await expect(page.getByRole('tab')).toHaveCount(2)
  await expect(page.getByRole('tab', { name: 'Geography' })).toHaveCount(0)
  expect(errors).toEqual([])
})

test('selected Cornwall event stays pinned to its source coordinate while zooming', async ({ page }) => {
  const errors = collectClientErrors(page)
  await page.goto('/?event=gdacs%3AFL%3A1103661', { waitUntil: 'networkidle' })
  await expect(page.locator('.event-drawer')).toBeVisible()

  const map = page.locator('.atlas-svg-map')
  const marker = page.locator('.atlas-marker.event[data-event-id="gdacs:FL:1103661"]')
  await expect(marker).toBeVisible()
  await expect(marker.locator('.selected-halo')).toBeVisible()
  const sourcePosition = await marker.getAttribute('transform')

  const zoomIn = map.getByRole('button', { name: 'Zoom in', exact: true })
  // The open analysis drawer intentionally covers the right-side controls at
  // desktop widths, so invoke the control as a keyboard activation would.
  await zoomIn.evaluate((button: HTMLButtonElement) => button.click())
  await zoomIn.evaluate((button: HTMLButtonElement) => button.click())
  await expect.poll(async () => Number(await map.locator(':scope > svg').getAttribute('data-zoom'))).toBeGreaterThan(1.5)
  await expect(marker).toHaveAttribute('transform', sourcePosition || '')
  await expect(marker).toHaveAttribute('data-count', '1')
  expect(errors).toEqual([])
})

test('data summary reports only MVP sources and their stored coverage dates', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.getByRole('button', { name: 'Data', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'What the Atlas currently covers.' })).toBeVisible()
  await expect(page.locator('.source-card')).toHaveCount(2)
  await expect(page.locator('.source-timeline-row')).toHaveCount(2)
  await expect(page.locator('.source-card[data-source="gdacs"]')).toContainText('1 Jan 2025 — 31 Dec 2025')
  await expect(page.locator('.source-card[data-source="gdelt_ngrams"]')).toContainText('31 Jul 2026')
  await expect(page.locator('.source-card[data-source="gdelt_ngrams"]')).toContainText('stored observation dates')
  await expect(page.locator('.source-card[data-source="gdelt_ngrams"] .source-coverage-ranges span')).toHaveCount(2)
  await expect(page.locator('.source-card[data-source="gdelt_articles"]')).toHaveCount(0)
  await expect(page.locator('.source-timeline-row[data-source="gdelt_ngrams"] .source-timeline-track span')).toHaveCount(2)
  await expect(page.getByText('Google Trends comparison series')).toHaveCount(0)
  await expect(page.getByText('NASA FIRMS wildfire detections')).toHaveCount(0)
  await expect(page.getByText('GDELT DOC 2.0 topic timelines')).toHaveCount(0)
  expect((await page.locator('.source-card dd').allTextContents()).some((value) => value.includes('Open'))).toBe(false)

  await page.getByRole('button', { name: 'Explore', exact: true }).click()
  await expect(page.locator('.atlas-svg-map')).toBeVisible()
  expect(errors).toEqual([])
})

test('methods page documents the current research protocol and definitions', async ({ page }) => {
  const errors = collectClientErrors(page)
  await openExplorer(page)
  await page.getByRole('button', { name: 'Methods', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'How the Atlas turns events into evidence.' })).toBeVisible()
  await expect(page.locator('.protocol-section')).toHaveCount(12)
  await expect(page.locator('.topic-method-card')).toHaveCount(2)
  await expect(page.locator('.topic-method-card[data-topic="climate_change"]')).toContainText('Climate change')
  await expect(page.locator('.candidate-topics')).toContainText('Clean energy')
  await expect(page.locator('.candidate-topics')).toContainText('Held back')

  const climateDictionary = page.locator('.topic-method-card[data-topic="climate_change"] details')
  await climateDictionary.locator('summary').click()
  await expect(climateDictionary).toHaveAttribute('open', '')
  await expect(climateDictionary).toContainText('cambio climático')
  await expect(climateDictionary).toContainText('Japanese · draft')

  await expect(page.locator('.method-equation')).toContainText('actor OR action OR party OR official source')
  await expect(page.locator('#collection')).toContainText('deterministic phrase matching, not an AI-model query')
  await expect(page.getByRole('table', { name: 'Media scope definitions' })).toContainText('Affected countries')
  await expect(page.getByRole('table', { name: 'Media scope definitions' })).toContainText('Global')
  await expect(page.locator('.window-diagram')).toContainText('Event duration')
  await expect(page.locator('.window-diagram')).toContainText('Excluded')
  await expect(page.locator('.decision-table .status-chip.planned')).toHaveText('Planned')
  await expect(page.locator('.reference-list > a')).toHaveCount(8)
  await expect(page.locator('.reference-list > a').first()).toHaveAttribute('href', /gdeltproject\.org/)
  await expect(page.locator('.reference-list > a').first()).toHaveAttribute('target', '_blank')

  await page.locator('.methods-toc a[href="#geography"]').click()
  await expect(page.locator('#geography')).toBeInViewport()
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
