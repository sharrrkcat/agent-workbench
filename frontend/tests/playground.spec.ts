import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { answerConfirmation, backToChat, navigateSettings, openSidebar } from './controls';
import { readMessages } from './history';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function openPlayground(page: Page) {
  await openSidebar(page);
  await page.locator('.session-sidebar').getByRole('button', { name: 'Playground', exact: true }).click();
  await expect(page).toHaveURL('/playground');
}

async function holdResponse(page: Page, pattern: string) {
  let release!: () => void, started!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const requested = new Promise<void>((resolve) => { started = resolve; });
  let completion: Promise<void> | undefined;
  await page.route(pattern, async (route) => {
    const response = await route.fetch();
    started();
    completion = held.then(() => route.fulfill({ response }));
    await completion;
  });
  return { requested, release: async () => { release(); await completion; await page.unroute(pattern); } };
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const labels = words(locale, 'personas'), common = words(locale, 'common'), settings = words(locale, 'settings');
  const knowledge = words(locale, 'knowledge'), chat = words(locale, 'chat');
  test.describe(`Playground ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    let session: { session_id: string; title: string };
    test.beforeEach(async ({ page, request }) => {
      session = await (await request.post('/__test__/session')).json();
      session.title = `Playground session ${session.session_id}`;
      await request.patch(`/api/sessions/${session.session_id}`, { data: { title: session.title } });
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
    });

    test('cards, keyboard access, direct routes, history and Settings return', async ({ page }, info) => {
      const errors: string[] = [], sessionReads: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('request', (request) => {
        if (/\/api\/sessions\/[^/]+(?:\/history)?$/.test(new URL(request.url()).pathname)) sessionReads.push(request.url());
      });
      await page.goto('/playground');
      await expect(page.getByRole('heading', { name: 'Playground', exact: true })).toBeVisible();
      await expect(page.locator('.composer, .chat-title')).toHaveCount(0);
      await openSidebar(page);
      const sidebar = page.locator('.session-sidebar');
      const entry = sidebar.getByRole('button', { name: 'Playground', exact: true });
      await expect(sidebar.locator('.sidebar-header [data-sidebar="menu-button"]')).toHaveText([
        labels.newSession, labels.newWorkspace, labels.newTimeline, labels.newQQBot, 'Playground',
      ]);
      await expect(entry).toHaveAttribute('aria-current', 'page');
      await expect(sidebar.locator('.session-select[aria-current="page"]')).toHaveCount(0);
      const historyLength = await page.evaluate(() => history.length);
      await entry.click();
      expect(await page.evaluate(() => history.length)).toBe(historyLength);
      if (width === 390) await expect(page.locator('[data-sidebar="trigger"]')).toHaveAttribute('aria-expanded', 'false');

      const cards = page.locator('.workspace [data-slot="card"]');
      const farkle = page.getByRole('button', { name: 'Farkle', exact: true });
      const whisper = page.getByRole('button', { name: 'Whisper', exact: true });
      await expect(cards).toHaveCount(2);
      await expect(cards.locator('[data-slot="card-title"]')).toHaveText(['Farkle', 'Whisper']);
      await expect(farkle).toBeEnabled();
      await expect(whisper).toBeDisabled();
      expect(await whisper.evaluate((node) => node instanceof HTMLButtonElement && node.disabled)).toBe(true);
      await expect(cards.nth(1)).toHaveCSS('opacity', '0.5');
      const first = (await cards.first().boundingBox())!, second = (await cards.last().boundingBox())!;
      if (width === 1366) expect(Math.abs(first.y - second.y)).toBeLessThan(1);
      else { expect(second.y).toBeGreaterThan(first.y + first.height); expect(first.height).toBeGreaterThanOrEqual(44); }
      await whisper.evaluate((node: HTMLButtonElement) => node.click());
      await expect(page).toHaveURL('/playground');
      await farkle.focus();
      await page.keyboard.press('Shift+Tab');
      await page.keyboard.press('Tab');
      await expect(farkle).toBeFocused();
      await expect(farkle).not.toHaveCSS('box-shadow', 'none');
      await page.keyboard.press('Tab');
      await expect(whisper).not.toBeFocused();
      await page.screenshot({ path: info.outputPath('playground.png') });
      await farkle.focus();
      await page.keyboard.press('Enter');
      await expect(page).toHaveURL('/playground/farkle');
      await expect(page.getByRole('heading', { name: 'Farkle', exact: true })).toBeVisible();
      await expect(page.locator('.farkle-table canvas')).toHaveCount(1);
      await expect(page.locator('.session-sidebar')).toHaveCount(0);
      await page.screenshot({ path: info.outputPath('farkle.png') });
      await openSidebar(page);
      const gameSidebar = page.locator('.farkle-sidebar');
      await expect(gameSidebar.locator('.sidebar-header [data-sidebar="menu-button"]')).toHaveText([
        common.farkle.newGame, common.farkle.myDice, common.farkle.shop, common.farkle.switchView,
      ]);
      await expect(gameSidebar.getByRole('button', { name: common.farkle.switchView, exact: true })).toBeDisabled();
      await expect(gameSidebar.getByRole('button', { name: labels.settings, exact: true })).toHaveCount(0);
      if (width === 390) await page.keyboard.press('Escape');
      await page.goBack();
      await expect(page).toHaveURL('/playground');
      await page.goForward();
      await expect(page).toHaveURL('/playground/farkle');
      await page.reload();
      await expect(page.getByRole('heading', { name: 'Farkle', exact: true })).toBeVisible();
      await openSidebar(page);
      await gameSidebar.getByRole('button', { name: common.back, exact: true }).click();
      await expect(page).toHaveURL('/playground');
      await openSidebar(page);
      await sidebar.getByRole('button', { name: labels.settings, exact: true }).click();
      await expect(page).toHaveURL('/settings');
      await backToChat(page);
      await expect(page).toHaveURL('/playground');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight)).toBe(true);
      expect(sessionReads).toEqual([]);
      expect(errors).toEqual([]);
    });

    test('leaving discards an unsent chat and its attachments without creating a session', async ({ page, request }) => {
      const before = await (await request.get('/api/sessions')).json();
      let creates = 0;
      page.on('request', (request) => {
        if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/sessions') creates++;
      });
      await page.goto('/new');
      await page.locator('.composer textarea').fill('Discard this draft');
      await page.locator('.composer input[type=file]').setInputFiles({ name: 'draft.txt', mimeType: 'text/plain', buffer: Buffer.from('Draft') });
      await expect(page.locator('.upload-ready')).toHaveCount(1);
      await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
      const dialog = page.getByRole('dialog', { name: labels.sessionSettings, exact: true });
      const original = await dialog.getByRole('spinbutton', { name: labels.maxChars, exact: true }).inputValue();
      await dialog.getByRole('spinbutton', { name: labels.maxChars, exact: true }).fill('500');
      await dialog.getByRole('button', { name: labels.save, exact: true }).click();
      await openPlayground(page);
      await expect(page.locator('.composer')).toHaveCount(0);
      await page.goBack();
      await expect(page).toHaveURL('/new');
      await expect(page.locator('.composer textarea')).toHaveValue('');
      await expect(page.locator('.attachment-chip')).toHaveCount(0);
      await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
      await expect(dialog.getByRole('spinbutton', { name: labels.maxChars, exact: true })).toHaveValue(original);
      await page.keyboard.press('Escape');
      expect(creates).toBe(0);
      expect((await (await request.get('/api/sessions')).json()).length).toBe(before.length);
    });

    test('late startup and session reads cannot select over Playground', async ({ page }) => {
      const startup = await holdResponse(page, '**/api/sessions');
      try {
        await page.goto('/');
        await startup.requested;
        await openPlayground(page);
      } finally { await startup.release(); }
      await openSidebar(page);
      const target = page.locator('.session-sidebar').getByRole('button', { name: session.title, exact: true });
      await expect(target).toBeVisible();
      await expect(page.locator('.session-select[aria-current="page"]')).toHaveCount(0);
      const details = await holdResponse(page, `**/api/sessions/${session.session_id}`);
      try {
        await target.click();
        await details.requested;
        await openPlayground(page);
      } finally { await details.release(); }
      await expect(page.getByRole('heading', { name: 'Playground', exact: true })).toBeVisible();
      await expect(page.locator('.composer')).toHaveCount(0);
      await openSidebar(page);
      await expect(page.locator('.session-select[aria-current="page"]')).toHaveCount(0);
      await target.click();
      await expect(page.locator('.chat-title')).toHaveText(session.title);
      await expect(page.locator('.composer textarea')).toBeEnabled();
    });

    test('Settings and Project leave guards preserve rejected navigation', async ({ page, request }) => {
      await page.goto('/playground');
      await openSidebar(page);
      await page.locator('.session-sidebar').getByRole('button', { name: labels.settings, exact: true }).click();
      await navigateSettings(page, settings.knowledge, settings.resources.settings);
      const chunk = page.getByLabel(knowledge.chunkSize, { exact: true });
      const edited = String(Number(await chunk.inputValue()) + 1);
      await chunk.fill(edited);
      await backToChat(page);
      await answerConfirmation(page, false, locale);
      await expect(page).toHaveURL('/settings?tab=knowledge&view=settings');
      if (width === 390) {
        await expect(page.locator('[data-sidebar="trigger"]')).toHaveAttribute('aria-expanded', 'true');
        await page.keyboard.press('Escape');
      }
      await expect(chunk).toHaveValue(edited);
      await backToChat(page);
      await answerConfirmation(page, true, locale);
      await expect(page).toHaveURL('/playground');

      const agents = await (await request.get('/api/personas?collection=agent')).json();
      const users = await (await request.get('/api/personas?collection=user')).json();
      const response = await request.post('/api/projects', { data: {
        kind: 'workspace', name: `Playground guard ${session.session_id}`, agent_persona_id: agents[0].id,
        cogita_persona_id: users[0].id, context_policy: {}, harness_enabled: false, tools_allowed: [],
      } });
      expect(response.ok()).toBe(true);
      const project = await response.json();
      try {
        await page.goto(`/projects/${project.id}`);
        await page.getByLabel(labels.projectName, { exact: true }).fill('Unsaved Playground guard');
        await openSidebar(page);
        await page.locator('.session-sidebar').getByRole('button', { name: 'Playground', exact: true }).click();
        await answerConfirmation(page, false, locale);
        await expect(page).toHaveURL(`/projects/${project.id}`);
        if (width === 390) {
          await expect(page.locator('[data-sidebar="trigger"]')).toHaveAttribute('aria-expanded', 'true');
          await page.keyboard.press('Escape');
        }
        await expect(page.getByLabel(labels.projectName, { exact: true })).toHaveValue('Unsaved Playground guard');
        await openSidebar(page);
        await page.locator('.session-sidebar').getByRole('button', { name: 'Playground', exact: true }).click();
        await answerConfirmation(page, true, locale);
        await expect(page).toHaveURL('/playground');
        if (width === 390) await expect(page.locator('[data-sidebar="trigger"]')).toHaveAttribute('aria-expanded', 'false');
        await page.goBack();
        await expect(page.getByLabel(labels.projectName, { exact: true })).toHaveValue(project.name);
        await page.getByLabel(labels.projectName, { exact: true }).fill('Browser forward guard');
        await page.evaluate(() => history.forward());
        await answerConfirmation(page, false, locale);
        await expect(page).toHaveURL(`/projects/${project.id}`);
        await page.evaluate(() => history.forward());
        await answerConfirmation(page, true, locale);
        await expect(page).toHaveURL('/playground');
      } finally { await request.delete(`/api/projects/${project.id}`); }
    });

    test('submitted work continues while queued messages wait for the conversation to reopen', async ({ page, request }) => {
      const posts: string[] = [];
      page.on('request', (request) => {
        if (request.method() === 'POST' && request.url().endsWith('/messages')) posts.push(request.postDataJSON().content);
      });
      await page.goto('/');
      const input = page.locator('.composer textarea');
      await input.fill('approval'); await input.press('Enter');
      await expect(page.locator('.approval-details')).toBeVisible();
      await input.fill('queued for return'); await input.press('Enter');
      await expect(page.getByRole('region', { name: chat.queue.label }).locator('li')).toHaveCount(1);
      await input.fill('Discard ordinary composer text');
      const waiting = await (await request.get(`/api/sessions/${session.session_id}`)).json();
      await openPlayground(page);
      const approved = await request.post(`/api/tools/approvals/${waiting.waiting_run_id}`, { data: { decision: 'approve' } });
      expect(approved.ok()).toBe(true);
      await expect.poll(async () => (await (await request.get(`/api/runs/${waiting.waiting_run_id}`)).json()).status).toBe('DONE');
      expect(posts).toEqual(['approval']);
      expect((await readMessages(request, session.session_id)).filter((message: { role: string }) => message.role === 'user')).toHaveLength(1);
      await openSidebar(page);
      await page.locator('.session-sidebar').getByRole('button', { name: session.title, exact: true }).click();
      await expect(input).toHaveValue('');
      await expect(page.locator('.status-done')).toHaveCount(2);
      expect(posts).toEqual(['approval', 'queued for return']);
      await expect(page.getByRole('region', { name: chat.queue.label })).toHaveCount(0);
    });
  });
}
