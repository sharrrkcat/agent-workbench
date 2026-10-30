import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { answerConfirmation, backToChat } from './controls';

async function submit(page: Page, text: string) {
  await expect(page.locator('.session-settings-trigger')).toBeEnabled();
  await page.locator('.composer textarea').fill(text);
  await expect(page.locator('.composer').getByRole('button', { name: /^(Send|发送)$/, exact: true })).toBeEnabled();
  await page.locator('.composer textarea').press('Enter');
}

for (const locale of ['en', 'zh-CN']) {
  const read = (namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
  const settings = read('settings'), runs = read('runs');
  for (const width of [1366, 390]) test.describe(`Web tools ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
    });

    test('persists citations, source links and specialized expanded traces', async ({ page, request }, info) => {
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session', { data: { web_tools: true, show_full_processing: true } });
      await page.goto('/');
      await submit(page, 'web-research');
      await expect(page.locator('.reply-answer')).toContainText('Evidence');
      await expect(page.locator('.status-done')).toBeVisible();
      const reply = page.locator('article[data-run-id]').last();
      const runId = await reply.getAttribute('data-run-id');
      const runData = await (await request.get(`/api/tools/runs/${runId}`)).json();
      const fetched = runData.messages.flatMap((message: { parts: Record<string, unknown>[] }) => message.parts)
        .find((part: { type: string; tool_name: string }) => part.type === 'tool_result' && part.tool_name === 'web_fetch').data;
      const fetchedTitle = fetched.title;
      await expect(reply.locator('[data-web-citation]')).toHaveCount(3);
      await expect(reply.locator('.reply-answer code')).toHaveText('[W1]');
      await expect(reply.locator('.approval-details')).toHaveCount(0);
      const sources = reply.locator('[data-web-sources]');
      const sourcesToggle = sources.locator('[data-slot=trace-collapsible-trigger]');
      await expect(sourcesToggle).toHaveAttribute('aria-expanded', 'false');
      await expect(sourcesToggle).toContainText('2');
      await sourcesToggle.focus();
      await sourcesToggle.press('Enter');
      await expect(sources.locator('a')).toHaveCount(2);
      await expect(sources.locator('a').first()).toContainText(fetchedTitle);
      await expect(sources.locator('a').last()).toContainText('Reference page');
      await expect(sources.locator('a').first()).toHaveAttribute('target', '_blank');

      const citation = reply.locator('[data-web-citation]').first();
      await citation.focus();
      const card = page.locator('[data-slot=hover-card-content]').filter({ hasText: fetchedTitle });
      await expect(card).toBeVisible();
      await expect(card.locator('a')).toHaveAttribute('href', /^https:\/\/example.com\/article\?query=/);
      await page.keyboard.press('Escape');
      await expect(card).toBeHidden();
      await sourcesToggle.focus();
      if (width === 390) await citation.tap();
      else {
        await page.mouse.move(0, 0);
        await citation.hover();
      }
      await expect(card).toBeVisible();
      await reply.locator('.processing-toggle').click();
      const search = reply.locator('[data-web-tool=web_search]');
      const fetch = reply.locator('[data-web-tool=web_fetch]');
      await expect(search.locator('[data-slot=trace-collapsible-trigger]')).toHaveAttribute('aria-expanded', 'true');
      await expect(fetch.locator('[data-slot=trace-collapsible-trigger]')).toHaveAttribute('aria-expanded', 'true');
      await expect(search).toContainText(locale === 'en' ? 'Searched the web for fixture query' : '已搜索网页：fixture query');
      await expect(search.locator('a')).toHaveCount(3);
      await expect(search.locator('a').last()).toHaveAttribute('href', 'https://unused.example.com/');
      await expect(search.locator('[data-slot=trace-collapsible-content-inner]')).toHaveText('Web article with a long query | example.comReference page | example.orgUnused result | unused.example.com');
      const content = fetch.locator('[data-slot=code-block-content]');
      await expect(content).toContainText('Extracted page content');
      await expect(content).not.toContainText('<script>');
      await expect(fetch.locator('[data-slot=trace-collapsible-content-inner]')).toHaveText(fetched.content);
      expect(await page.evaluate(() => (window as Window & { webPageExecuted?: boolean }).webPageExecuted)).toBeUndefined();
      expect((await content.boundingBox())!.height).toBeLessThanOrEqual(width < 768 ? 121 : 161);
      await page.screenshot({ path: info.outputPath('web-trace-expanded.png'), fullPage: true });
      await search.locator('[data-slot=trace-collapsible-trigger]').click();
      await reply.locator('.processing-toggle').click();
      await reply.locator('.processing-toggle').click();
      await expect(search.locator('[data-slot=trace-collapsible-trigger]')).toHaveAttribute('aria-expanded', 'false');
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath('web-trace.png'), fullPage: true });
      await page.reload();
      await expect(page.locator('[data-web-citation]')).toHaveCount(3);
      await expect(page.locator('[data-web-sources] [data-slot=trace-collapsible-trigger]')).toHaveAttribute('aria-expanded', 'false');
      await page.screenshot({ path: info.outputPath('web-citations.png'), fullPage: true });
      await submit(page, 'web-no-call');
      await expect(page.locator('.reply-answer').last()).toHaveText('Unknown [W1] in this reply.');
      await expect(page.locator('article[data-run-id]').last().locator('[data-web-sources]')).toHaveCount(0);
      expect(errors).toEqual([]);
    });

    test('shows a partial search batch as source links', async ({ page, request }) => {
      await request.post('/__test__/session', { data: { web_tools: true, show_full_processing: true } });
      await page.goto('/');
      await submit(page, 'web-partial');
      const reply = page.locator('article[data-run-id]').last();
      await expect(reply.locator('.status-done')).toBeVisible();
      await reply.locator('.processing-toggle').click();
      const search = reply.locator('[data-web-tool=web_search]');
      await expect(search.locator('a')).toHaveCount(2);
      await expect(search.locator('[data-slot=trace-collapsible-content-inner]')).toHaveText('Web article with a long query | example.comReference page | example.org');
    });

    test('shows empty, failed and cancelled web steps without approval', async ({ page, request }) => {
      await request.post('/__test__/session', { data: { web_tools: true, show_full_processing: true } });
      await page.goto('/');
      for (const [command, message] of [['web-empty', runs.web.noResults], ['web-failure', runs.web.errors.WEB_RATE_LIMITED]]) {
        await submit(page, command);
        const reply = page.locator('article[data-run-id]').last();
        await expect(reply.locator('.status-done')).toBeVisible();
        await reply.locator('.processing-toggle').click();
        await expect(reply.locator('[data-web-tool]')).toContainText(message);
        await expect(reply.locator('[data-web-sources]')).toHaveCount(0);
      }
      await submit(page, 'web-hold');
      const last = page.locator('article[data-run-id]').last();
      await expect(last.locator('[data-web-tool]')).toContainText(locale === 'en' ? 'Searching' : '正在搜索');
      await page.locator('.composer').getByRole('button', { name: runs.cancel, exact: true }).click();
      await expect(last.locator('.status-cancelled')).toBeVisible();
      await last.locator('.processing-toggle').click();
      await expect(last.locator('[data-web-tool]')).toContainText(locale === 'en' ? 'Cancelled' : '已取消');
      await expect(page.locator('.approval-details')).toHaveCount(0);
    });

    test('saves, replaces and clears the key while retaining failed edits', async ({ page, request }) => {
      const limits = { search_calls_per_run: 4, fetch_calls_per_run: 6, cache_ttl_hours: 24, cache_retention_days: 30 };
      await request.patch('/api/tools/web/settings', { data: { api_key: '', max_results: 10, zone: null, language: null, ...limits } });
      await page.goto('/settings?tab=tools&view=web');
      const form = page.getByRole('region', { name: 'AnySearch', exact: true });
      const input = form.getByLabel(settings.webTools.apiKey, { exact: true });
      const save = form.getByRole('button', { name: settings.save, exact: true });
      await input.fill('first-key');
      await save.click();
      await expect(input).toHaveValue('');
      await expect(input).toHaveAttribute('placeholder', settings.webTools.keySet);
      await page.reload();
      await expect(input).toHaveAttribute('placeholder', settings.webTools.keySet);
      expect(await (await request.get('/api/tools/web/settings')).json()).toEqual({ provider: 'anysearch', has_api_key: true, max_results: 10, zone: null, language: null, ...limits });
      const maxResults = form.getByLabel(settings.webTools.maxResults, { exact: true });
      const language = form.getByLabel(settings.webTools.language, { exact: true });
      await maxResults.fill('3');
      await language.fill('en');
      for (const [key, value] of Object.entries(limits)) {
        await form.getByLabel(settings.webTools[key], { exact: true }).fill(String(value + 1));
        limits[key as keyof typeof limits] = value + 1;
      }
      await form.getByRole('button', { name: settings.webTools.zones.intl, exact: true }).click();
      await save.click();
      await expect(save).toBeDisabled();
      expect(await (await request.get('/api/tools/web/settings')).json()).toEqual({ provider: 'anysearch', has_api_key: true, max_results: 3, zone: 'intl', language: 'en', ...limits });
      await page.reload();
      await expect(maxResults).toHaveValue('3');
      await expect(language).toHaveValue('en');
      for (const [key, value] of Object.entries(limits)) await expect(form.getByLabel(settings.webTools[key], { exact: true })).toHaveValue(String(value));
      await expect(form.getByRole('button', { name: settings.webTools.zones.intl, exact: true })).toHaveAttribute('aria-pressed', 'true');

      await page.route('**/api/tools/web/settings', (route) => route.request().method() === 'PATCH'
        ? route.fulfill({ status: 500, json: { error: { code: 'SAVE_FAILED', message: 'Fixture save failure' } } }) : route.continue());
      await input.fill('replacement-key');
      await maxResults.fill('5');
      await save.click();
      await expect(form).toContainText('SAVE_FAILED');
      await expect(input).toHaveValue('replacement-key');
      await expect(maxResults).toHaveValue('5');
      await backToChat(page);
      await answerConfirmation(page, false, locale);
      if (width === 390) await page.keyboard.press('Escape');
      await expect(input).toHaveValue('replacement-key');
      await page.unroute('**/api/tools/web/settings');
      await save.click();
      await expect(input).toHaveValue('');
      await form.getByRole('button', { name: settings.webTools.clearKey, exact: true }).click();
      await expect(input).toHaveAttribute('placeholder', settings.webTools.keyMissing);
      expect(await (await request.get('/api/tools/web/settings')).json()).toEqual({ provider: 'anysearch', has_api_key: false, max_results: 5, zone: 'intl', language: 'en', ...limits });
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });

    test('shows localized web instructions before Agent Persona', async ({ page, request }, info) => {
      const session = await (await request.post('/__test__/session', { data: { web_tools: true } })).json();
      await page.goto('/');
      await submit(page, 'web-no-call');
      const reply = page.locator('article[data-run-id]').last();
      await expect(reply.locator('.status-done')).toBeVisible();
      await reply.getByRole('button', { name: runs.context.details, exact: true }).click();
      const dialog = page.getByRole('dialog', { name: runs.context.details, exact: true });
      const instruction = dialog.locator('[data-context-source=instruction]');
      await expect(instruction).toContainText(runs.context.sources.instruction);
      const kinds = await dialog.locator('[data-context-source]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-context-source')));
      expect(kinds.indexOf('instruction')).toBe(kinds.indexOf('system') + 1);
      expect(kinds.indexOf('instruction')).toBeLessThan(kinds.indexOf('agent_persona'));
      await instruction.click();
      const text = dialog.locator('.context-source-detail .context-text');
      await expect(text).toHaveText(locale === 'en'
        ? /^Current date: \d{4}-\d{2}-\d{2} \((Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\)\.$/
        : /^当前日期：\d{4}年\d{1,2}月\d{1,2}日（星期[一二三四五六日]）。$/);
      const recordedDate = await text.innerText();
      await dialog.getByRole('tab', { name: runs.context.request, exact: true }).click();
      const recordedRequest = JSON.parse(await dialog.locator('.context-request').innerText());
      expect(recordedRequest.messages[0].content).toContain(recordedDate);
      const descriptions = recordedRequest.tools.map((tool: { function: { description: string } }) => tool.function.description).join('\n');
      expect(descriptions.match(/Cite web evidence/g)).toHaveLength(1);
      expect(descriptions.match(/untrusted evidence/g)).toHaveLength(1);
      await page.screenshot({ path: info.outputPath('date-instruction.png'), fullPage: true });
      await page.keyboard.press('Escape');
      await request.patch(`/api/sessions/${session.session_id}`, { data: { tools_allowed: [] } });
      await page.reload();
      await submit(page, 'web-no-call');
      await expect(page.locator('article[data-run-id]')).toHaveCount(2);
      await expect(reply.locator('.status-done')).toBeVisible();
      await reply.getByRole('button', { name: runs.context.details, exact: true }).click();
      await expect(dialog.locator('[data-context-source=system]')).toBeVisible();
      await expect(dialog.locator('[data-context-source=instruction]')).toHaveCount(0);
    });
  });
}
