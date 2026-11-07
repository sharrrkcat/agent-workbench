import { readFileSync } from 'node:fs';
import { expect, test, type APIResponse, type Locator } from '@playwright/test';
import { answerConfirmation, openSidebar } from './controls';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=', 'base64');
async function json(response: Promise<APIResponse>) {
  const result = await response;
  expect(result.ok(), await result.text()).toBe(true);
  return result.json();
}
async function columns(grid: Locator, count: number) {
  await expect.poll(() => grid.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length)).toBe(count);
  const gridBox = await grid.boundingBox();
  const listBox = await grid.page().locator('[data-character-card="memories"]').boundingBox();
  expect(listBox!.x).toBeCloseTo(gridBox!.x, 0);
  expect(listBox!.width).toBeCloseTo(gridBox!.width, 0);
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const words = (namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
  const labels = words('personas'), memory = words('memory'), llm = words('llm');
  test.describe(`Character settings cards ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test.beforeEach(async ({ page, request }) => {
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
    });

    test('independent card columns, expanding prompt and separate drawer widths', async ({ page, request }, info) => {
      const errors: string[] = [], resourceReads: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('request', (request) => { if (/\/api\/(knowledge\/bases|worldbooks)$/.test(request.url())) resourceReads.push(request.url()); });
      const owner = await json(request.post('/api/characters', { data: {
        kind: 'normal', name: 'A character with a long name that wraps comfortably across the profile card',
        system_prompt: Array.from({ length: 8 }, (_, index) => `Instruction ${index}: keep answers clear and useful.`).join('\n'),
      } }));
      try {
        await page.goto(`/characters/${owner.id}/settings`);
        const grid = page.locator('.character-settings-grid');
        await expect(page.locator('.character-settings [data-character-card]')).toHaveCount(7);
        for (const [column, cards] of [['profile', ['profile', 'memory']], ['execution', ['execution', 'context']], ['resources', ['knowledge', 'worldbook']]] as const) {
          const stack = grid.locator(`[data-character-column="${column}"]`);
          expect(await stack.locator('[data-character-card]').evaluateAll((elements) => elements.map((el) => el.getAttribute('data-character-card')))).toEqual(cards);
          const first = (await stack.locator('[data-character-card]').nth(0).boundingBox())!;
          const second = (await stack.locator('[data-character-card]').nth(1).boundingBox())!;
          expect(first.width).toBeCloseTo((await stack.boundingBox())!.width, 0);
          expect(second.width).toBeCloseTo(first.width, 0);
          expect(second.x).toBeCloseTo(first.x, 0);
          expect(second.y - first.y - first.height).toBeCloseTo(16, 0);
        }
        await expect(page.locator('.settings-header').getByRole('button', { name: labels.newSession, exact: true })).toHaveCount(0);
        await expect(grid.getByRole('tablist')).toHaveCount(0);
        await columns(grid, width === 390 ? 1 : 3);
        const profileCard = grid.locator('[data-character-card="profile"]');
        const prompt = profileCard.locator('[data-profile-prompt]');
        expect(await prompt.evaluate((element) => element.clientHeight <= parseFloat(getComputedStyle(element).lineHeight) * 4 + 1 && element.scrollHeight > element.clientHeight)).toBe(true);
        const cardBox = (await profileCard.boundingBox())!, avatarBox = (await profileCard.locator('[data-slot="avatar"]').boundingBox())!;
        expect(cardBox.height).toBeLessThan((await grid.locator('[data-character-card="execution"]').boundingBox())!.height);
        await expect(profileCard).toHaveCSS('padding-top', '32px');
        await expect(profileCard).toHaveCSS('padding-bottom', '32px');
        expect(avatarBox.x + avatarBox.width / 2).toBeCloseTo(cardBox.x + cardBox.width / 2, 0);
        for (const card of ['execution', 'context', 'memory']) await expect(grid.locator(`[data-character-card="${card}"]`).getByRole('button', { name: labels.save, exact: true })).toHaveCount(0);
        await expect(grid.getByText(labels.characterCards.resourceUnavailable, { exact: true })).toHaveCount(2);
        await page.screenshot({ path: info.outputPath('cards.png'), animations: 'disabled' });
        if (width === 1366) {
          await page.setViewportSize({ width: 1024, height: 900 });
          await columns(grid, 2);
          await page.screenshot({ path: info.outputPath('cards-two-columns.png'), animations: 'disabled' });
          await page.setViewportSize({ width: 1920, height: 900 });
          await columns(grid, 3);
          await page.setViewportSize({ width, height: 900 });
        }
        const trigger = page.getByRole('button', { name: labels.characterCards.editProfile, exact: true });
        await trigger.focus(); await trigger.press('Enter');
        const drawer = page.getByRole('dialog', { name: labels.characterCards.profile, exact: true });
        await expect(drawer).toHaveAttribute('data-swipe-direction', width === 390 ? 'down' : 'right');
        await expect(drawer.getByLabel(labels.characterName, { exact: true })).toBeInViewport();
        await expect(drawer.getByRole('checkbox')).toHaveCount(0);
        const textBox = (await drawer.getByLabel(labels.systemPrompt, { exact: true }).boundingBox())!;
        expect(textBox.height).toBeGreaterThan(250);
        await expect.poll(() => drawer.evaluate((element) => {
          const textarea = element.querySelector('textarea')!.getBoundingClientRect();
          const save = element.querySelector('[data-slot="drawer-footer"] button')!.getBoundingClientRect();
          return save.top - textarea.bottom;
        })).toBeCloseTo(16, 0);
        await expect(drawer.getByRole('button', { name: labels.save, exact: true })).toBeInViewport();
        if (width === 1366) expect((await drawer.boundingBox())!.width).toBeCloseTo(480, 0);
        await page.screenshot({ path: info.outputPath('profile-drawer.png'), animations: 'disabled' });
        await page.keyboard.press('Escape');
        await expect(drawer).toBeHidden(); await expect(trigger).toBeFocused();
        const toolsTrigger = page.getByRole('button', { name: labels.characterCards.configureTools, exact: true });
        const harnessRow = grid.locator('[data-slot="field"]').filter({ has: page.getByRole('switch', { name: labels.harness, exact: true }) });
        await expect(harnessRow.getByRole('button', { name: labels.characterCards.configureTools, exact: true })).toHaveText('');
        await toolsTrigger.click();
        const toolDrawer = page.getByRole('dialog', { name: labels.harnessSettings, exact: true });
        const tools = toolDrawer.getByRole('form', { name: labels.tools, exact: true });
        await expect(tools.getByRole('checkbox', { name: 'memory_list', exact: true })).toBeInViewport();
        await expect(toolDrawer.getByLabel(labels.characterName, { exact: true })).toHaveCount(0);
        await expect(toolDrawer.getByRole('button', { name: labels.close, exact: true })).toBeInViewport();
        if (width === 1366) expect((await toolDrawer.boundingBox())!.width).toBeCloseTo(384, 0);
        await page.screenshot({ path: info.outputPath('tools-drawer.png'), animations: 'disabled' });
        await toolDrawer.getByRole('button', { name: labels.close, exact: true }).click();
        await expect(toolDrawer).toBeHidden(); await expect(toolsTrigger).toBeFocused();
        const advancedTrigger = grid.getByRole('button', { name: labels.compactionAdvanced, exact: true });
        const compactionRow = grid.locator('[data-slot="field"]').filter({ has: page.getByRole('switch', { name: labels.autoCompaction, exact: true }) });
        await expect(compactionRow.getByRole('button', { name: labels.compactionAdvanced, exact: true })).toHaveText('');
        await advancedTrigger.click();
        const advanced = page.getByRole('dialog', { name: labels.compactionAdvanced, exact: true });
        await expect(advanced.getByLabel(labels.compactionTrigger, { exact: true })).toBeVisible();
        await expect(advanced.getByLabel(labels.characterName, { exact: true })).toHaveCount(0);
        if (width === 1366) expect((await advanced.boundingBox())!.width).toBeCloseTo(384, 0);
        await advanced.getByLabel(labels.compactionTrigger, { exact: true }).fill('85');
        await page.screenshot({ path: info.outputPath('advanced-drawer.png'), animations: 'disabled' });
        await advanced.getByRole('button', { name: labels.close, exact: true }).click();
        await answerConfirmation(page, false, locale);
        await expect(advanced.getByLabel(labels.compactionTrigger, { exact: true })).toHaveValue('85');
        await advanced.getByRole('button', { name: labels.close, exact: true }).click();
        await answerConfirmation(page, true, locale); await expect(advanced).toBeHidden();
        await expect(advancedTrigger).toBeFocused();
        await advancedTrigger.click();
        await expect(advanced.getByLabel(labels.compactionTrigger, { exact: true })).toHaveValue('80');
        await advanced.getByLabel(labels.compactionTrigger, { exact: true }).fill('85');
        await advanced.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(advanced.getByRole('status')).toHaveText(labels.saved);
        expect((await json(request.get(`/api/characters/${owner.id}`))).context_policy.compaction.trigger_percent).toBe(85);
        await advanced.getByRole('button', { name: labels.close, exact: true }).click();
        await expect(advanced).toBeHidden();
        await page.locator('[data-character-card="memories"]').scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath('memories-card.png'), animations: 'disabled' });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(resourceReads).toEqual([]); expect(errors).toEqual([]);
      } finally { await request.delete(`/api/characters/${owner.id}`); }
    });

    test('card changes autosave independently and keep shared memory and mounts', async ({ page, request }) => {
      const profiles = await json(request.get('/api/models/profiles'));
      const base = await json(request.post('/api/knowledge/bases', { data: { name: 'Retained mount', embedding_model_profile_id: profiles.find((p: { kind: string }) => p.kind === 'embedding').id } }));
      const book = await json(request.post('/api/worldbooks', { data: { name: 'Retained worldbook' } }));
      const owner = await json(request.post('/api/characters', { data: { kind: 'normal', name: 'Automatic saves', temperature: 0.4,
        tools_allowed: ['web_fetch'], memory_learning: 'manual', knowledge_base_ids: [base.id], worldbook_ids: [book.id] } }));
      const patches: Record<string, unknown>[] = [];
      page.on('request', (request) => { if (request.method() === 'PATCH' && request.url().endsWith(`/api/characters/${owner.id}`)) patches.push(request.postDataJSON()); });
      const current = () => json(request.get(`/api/characters/${owner.id}`));
      try {
        await page.goto(`/characters/${owner.id}/settings`);
        const execution = page.getByRole('form', { name: labels.characterCards.execution, exact: true });
        const memoryForm = page.getByRole('form', { name: labels.characterCards.memorySettings, exact: true });
        const context = page.getByRole('form', { name: labels.context, exact: true });
        const temperature = execution.getByLabel(llm.params.temperature, { exact: true });
        await temperature.fill('3'); await temperature.press('Tab');
        expect(patches).toEqual([]);
        await execution.getByRole('switch', { name: labels.reasoning, exact: true }).uncheck();
        await expect.poll(async () => (await current()).reasoning).toBe(false);
        expect(patches.at(-1)).toEqual({ reasoning: false });
        await expect(temperature).toHaveValue('3');
        await temperature.fill('0'); await temperature.press('Enter');
        await expect.poll(async () => (await current()).temperature).toBe(0);
        expect(patches.at(-1)).toEqual({ temperature: 0 });
        await temperature.fill(''); await temperature.press('Tab');
        await expect.poll(async () => (await current()).temperature).toBeNull();
        await memoryForm.getByRole('switch', { name: memory.readEnabled, exact: true }).uncheck();
        await expect.poll(async () => (await current()).memory_enabled).toBe(false);
        expect(patches.at(-1)).toEqual({ memory_enabled: false });
        await context.getByRole('button', { name: labels.messageWindow, exact: true }).click();
        await expect.poll(async () => (await current()).context_policy.strategy).toBe('message_window');
        await context.getByLabel(labels.maxMessages, { exact: true }).fill('7');
        await context.getByLabel(labels.maxMessages, { exact: true }).press('Tab');
        await expect.poll(async () => (await current()).context_policy.message_window.max_messages).toBe(7);
        expect(Object.keys(patches.at(-1)!)).toEqual(['context_policy']);
        await memoryForm.getByRole('button', { name: memory.automatic, exact: true }).click();
        await expect.poll(async () => (await current()).memory_learning).toBe('automatic');
        await page.getByRole('button', { name: labels.characterCards.configureTools, exact: true }).click();
        const tools = page.getByRole('dialog', { name: labels.harnessSettings, exact: true });
        await expect(tools.getByRole('checkbox', { name: 'memory_read', exact: true })).toBeChecked();
        await tools.getByRole('checkbox', { name: 'memory_forget', exact: true }).uncheck();
        await tools.getByRole('button', { name: labels.close, exact: true }).click();
        await answerConfirmation(page, true, locale); await expect(tools).toBeHidden();
        await expect(memoryForm.getByRole('button', { name: memory.automatic, exact: true })).toHaveAttribute('aria-pressed', 'true');
        await page.getByRole('button', { name: labels.characterCards.configureTools, exact: true }).click();
        await tools.getByRole('checkbox', { name: 'memory_write', exact: true }).uncheck();
        await tools.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(tools.getByRole('status')).toHaveText(labels.saved);
        expect(patches.at(-1)).toEqual({ memory_learning: 'manual' });
        await tools.getByRole('button', { name: labels.close, exact: true }).click(); await expect(tools).toBeHidden();
        await expect(memoryForm.getByRole('button', { name: memory.manual, exact: true })).toHaveAttribute('aria-pressed', 'true');
        await execution.getByRole('switch', { name: labels.harness, exact: true }).check();
        await expect.poll(async () => (await current()).harness_enabled).toBe(true);
        await context.getByRole('button', { name: labels.historyRetrieval, exact: true }).click();
        await expect.poll(async () => (await current()).context_policy.strategy).toBe('history_retrieval');
        await context.getByRole('button', { name: labels.compactionAdvanced, exact: true }).click();
        const advanced = page.getByRole('dialog', { name: labels.compactionAdvanced, exact: true });
        await advanced.getByLabel(labels.checkpointTokens, { exact: true }).fill('512');
        await advanced.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(advanced.getByRole('status')).toHaveText(labels.saved);
        await advanced.getByRole('button', { name: labels.close, exact: true }).click(); await expect(advanced).toBeHidden();
        await page.reload();
        expect(await current()).toMatchObject({ temperature: null, reasoning: false, harness_enabled: true,
          memory_learning: 'manual', memory_enabled: false, tools_allowed: ['web_fetch'], knowledge_base_ids: [base.id], worldbook_ids: [book.id],
          context_policy: { strategy: 'history_retrieval', message_window: { max_messages: 7 }, retrieval: { max_checkpoint_tokens: 512 } } });
      } finally {
        await request.delete(`/api/characters/${owner.id}`);
        await request.delete(`/api/knowledge/bases/${base.id}`); await request.delete(`/api/worldbooks/${book.id}`);
      }
    });

    test('autosave errors restore confirmed values and pending changes block departure', async ({ page, request }) => {
      const owner = await json(request.post('/api/characters', { data: { kind: 'normal', name: 'Autosave recovery', temperature: 0.4 } }));
      let release!: () => void;
      try {
        await page.goto(`/characters/${owner.id}/settings`);
        const execution = page.getByRole('form', { name: labels.characterCards.execution, exact: true });
        const reasoning = execution.getByRole('switch', { name: labels.reasoning, exact: true });
        await page.route(`**/api/characters/${owner.id}`, async (route) => {
          if (route.request().method() === 'PATCH') await route.fulfill({ status: 500, json: { error: { code: 'TEST_AUTOSAVE_FAILED', message: 'Try again' } } });
          else await route.continue();
        });
        await reasoning.click();
        await expect(execution.getByRole('alert')).toContainText('TEST_AUTOSAVE_FAILED');
        await expect(reasoning).toBeChecked();
        const temperature = execution.getByLabel(llm.params.temperature, { exact: true });
        await temperature.fill('1'); await temperature.press('Tab');
        await expect(temperature).toHaveValue('0.4');
        await page.unroute(`**/api/characters/${owner.id}`);
        const gate = new Promise<void>((resolve) => { release = resolve; });
        await page.route(`**/api/characters/${owner.id}`, async (route) => {
          if (route.request().method() === 'PATCH') { await gate; await route.continue(); } else await route.continue();
        });
        await reasoning.uncheck(); await expect(reasoning).toBeDisabled();
        await openSidebar(page);
        await page.locator('.session-sidebar').getByRole('button', { name: 'Playground', exact: true }).click();
        await expect(page).toHaveURL(`/characters/${owner.id}/settings`);
        if (width === 390) await page.keyboard.press('Escape');
        release();
        await expect(reasoning).toBeEnabled(); await expect(reasoning).not.toBeChecked();
        await expect(execution.getByRole('alert')).toHaveCount(0);
        expect((await json(request.get(`/api/characters/${owner.id}`))).reasoning).toBe(false);
      } finally { release?.(); await request.delete(`/api/characters/${owner.id}`); }
    });

    test('failed and pending saves retain edits; saved avatars survive drawer dismissal', async ({ page, request }) => {
      const owner = await json(request.post('/api/characters', { data: { kind: 'normal', name: 'Save recovery' } }));
      let releaseUpload!: () => void, releaseSave!: () => void;
      try {
        await page.goto(`/characters/${owner.id}/settings`);
        await page.getByRole('button', { name: labels.characterCards.editProfile, exact: true }).click();
        const drawer = page.getByRole('dialog', { name: labels.characterCards.profile, exact: true });
        const profile = drawer.getByRole('form', { name: labels.characterCards.profile, exact: true });
        const close = drawer.getByRole('button', { name: labels.close, exact: true });
        const save = profile.getByRole('button', { name: labels.save, exact: true });
        await profile.getByLabel(labels.characterName, { exact: true }).fill('Recovered profile');
        await page.route(`**/api/characters/${owner.id}`, async (route) => {
          if (route.request().method() === 'PATCH') await route.fulfill({ status: 500, json: { error: { code: 'TEST_SAVE_FAILED', message: 'Try again' } } });
          else await route.continue();
        });
        await save.click(); await expect(profile.getByRole('alert')).toContainText('TEST_SAVE_FAILED');
        await expect(profile.getByLabel(labels.characterName, { exact: true })).toHaveValue('Recovered profile');
        await page.unroute(`**/api/characters/${owner.id}`);
        const uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve; });
        await page.route('**/api/attachments', async (route) => { await uploadGate; await route.continue(); });
        const uploaded = page.waitForResponse((response) => response.url().endsWith('/api/attachments') && response.request().method() === 'POST');
        await profile.locator('input[type="file"]').setInputFiles({ name: 'avatar.png', mimeType: 'image/png', buffer: png });
        await expect(close).toBeDisabled(); await expect(save).toBeDisabled();
        await page.keyboard.press('Escape'); await expect(drawer).toBeVisible();
        releaseUpload(); await uploaded;
        await expect(profile.locator('[data-slot="avatar-image"]')).toBeVisible();
        const saveGate = new Promise<void>((resolve) => { releaseSave = resolve; });
        await page.route(`**/api/characters/${owner.id}`, async (route) => {
          if (route.request().method() === 'PATCH') { await saveGate; await route.continue(); } else await route.continue();
        });
        const savedResponse = page.waitForResponse((response) => response.url().endsWith(`/api/characters/${owner.id}`) && response.request().method() === 'PATCH');
        await save.click(); await expect(close).toBeDisabled();
        await page.keyboard.press('Escape'); await expect(drawer).toBeVisible();
        releaseSave(); const saved = await (await savedResponse).json();
        await expect(profile.getByRole('status')).toHaveText(labels.saved);
        await profile.getByLabel(labels.systemPrompt, { exact: true }).fill('Discard this prompt only');
        await close.click(); await answerConfirmation(page, true, locale); await expect(drawer).toBeHidden();
        await expect(page.locator('[data-character-card="profile"] [data-slot="avatar-image"]')).toBeVisible();
        expect((await request.get(`/api/attachments/${saved.avatar_attachment_id}`)).ok()).toBe(true);
        await page.reload();
        await page.getByRole('button', { name: labels.characterCards.editProfile, exact: true }).click();
        await expect(profile.getByLabel(labels.characterName, { exact: true })).toHaveValue('Recovered profile');
        await expect(profile.getByLabel(labels.systemPrompt, { exact: true })).toHaveValue('');
        await expect(profile.locator('[data-slot="avatar-image"]')).toBeVisible();
      } finally {
        releaseUpload?.(); releaseSave?.();
        await request.delete(`/api/characters/${owner.id}`);
      }
    });
  });
}
