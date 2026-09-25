import { readFileSync } from 'node:fs';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { answerConfirmation, backToChat, navigateSettings, openSidebar } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=', 'base64');
const identity = (value: { name: string; system_prompt: string; avatar_attachment_id: string | null }) => ({
  name: value.name, system_prompt: value.system_prompt, avatar_attachment_id: value.avatar_attachment_id,
});

async function singleton(request: APIRequestContext) {
  return (await (await request.get('/api/personas?collection=user')).json())[0];
}

for (const locale of ['en', 'zh-CN']) {
  const labels = words(locale, 'personas');
  const settings = words(locale, 'settings');
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`Persona collections ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });
      const navigate = (page: Page, collection: string) => navigateSettings(page, settings.personas, labels.collections[collection],
        settings.sidebarGroups[['user', 'agent'].includes(collection) ? 'daily' : 'roleplay']);

      test('shared editors keep collections and resource permissions separate', async ({ page, request }, info) => {
        test.setTimeout(90000);
        const tag = `${locale}-${viewport.width}-${Date.now()}`;
        const user = await singleton(request);
        const userBindings = await (await request.get(`/api/personas/${user.id}/knowledge-bases`)).json();
        const cogita = (await (await request.get('/api/personas?collection=agent')).json()).find((p: { is_protected: boolean }) => p.is_protected);
        const models = await (await request.get('/api/models/profiles')).json();
        const base = await (await request.post('/api/knowledge/bases', { data: { name: `Facts ${tag}`, embedding_model_profile_id: models.find((m: { kind: string }) => m.kind === 'embedding').id } })).json();
        const book = await (await request.post('/api/worldbooks', { data: { name: `Lore ${tag}` } })).json();
        const createdIds: string[] = [];
        let sessionId = '';
        try {
          await page.goto('/settings?tab=personas');
          const panel = page.locator('[data-persona-collection="user"]');
          await expect(panel.getByLabel(labels.name, { exact: true })).toHaveValue(user.name);
          await expect(panel.getByRole('button', { name: labels.add, exact: true })).toHaveCount(0);
          await expect(panel.getByRole('tab', { name: labels.worldbook, exact: true })).toHaveCount(0);
          await panel.getByRole('tab', { name: labels.knowledge, exact: true }).click();
          await panel.getByRole('checkbox', { name: base.name, exact: true }).check();
          await panel.getByRole('button', { name: labels.save, exact: true }).click();
          await expect(panel.getByRole('status')).toHaveText(labels.saved);
          await navigate(page, 'agent');
          let defaultRow = page.locator('.persona-row').filter({ hasText: cogita.name });
          await expect(defaultRow.getByRole('button')).toHaveCount(1);
          await defaultRow.getByRole('button').click();
          let dialog = page.getByRole('dialog', { name: labels.edit, exact: true });
          await dialog.getByLabel(labels.name, { exact: true }).fill(`Cogita ${tag}`);
          await dialog.getByRole('button', { name: labels.save, exact: true }).click();
          await expect(dialog).toBeHidden();
          defaultRow = page.locator('.persona-row').filter({ hasText: `Cogita ${tag}` });
          await expect(defaultRow.getByRole('button')).toHaveCount(1);
          expect((await request.delete(`/api/personas/${cogita.id}`)).status()).toBe(409);

          for (const collection of ['agent', 'roleplay_user', 'character']) {
            await navigate(page, collection);
            if (collection !== 'agent') await expect(page.getByText(labels.emptyPersonas, { exact: true })).toBeVisible();
            await page.getByRole('button', { name: labels.add, exact: true }).click();
            dialog = page.getByRole('dialog', { name: labels.add, exact: true });
            const name = `${collection} ${tag}`;
            await dialog.getByLabel(labels.name, { exact: true }).fill(name);
            await dialog.getByLabel(labels.systemPrompt, { exact: true }).fill(`Prompt ${collection}`);
            const permitted = collection === 'agent' ? 'knowledge' : 'worldbook';
            const forbidden = collection === 'agent' ? 'worldbook' : 'knowledge';
            await expect(dialog.getByRole('tab', { name: labels[forbidden], exact: true })).toHaveCount(0);
            await dialog.getByRole('tab', { name: labels[permitted], exact: true }).click();
            await dialog.getByRole('checkbox', { name: collection === 'agent' ? base.name : book.name, exact: true }).check();
            const created = page.waitForResponse((r) => r.url().endsWith('/api/personas') && r.request().method() === 'POST');
            await dialog.getByRole('button', { name: labels.save, exact: true }).click();
            const persona = await (await created).json();
            createdIds.push(persona.id);
            expect(persona.collection).toBe(collection);
            await expect(dialog).toBeHidden();
            const row = page.locator('.persona-row').filter({ hasText: name });
            await row.getByRole('button', { name: labels.editNamed.replace('{{name}}', name), exact: true }).click();
            dialog = page.getByRole('dialog', { name: labels.edit, exact: true });
            await expect(dialog.getByLabel(labels.systemPrompt, { exact: true })).toHaveValue(`Prompt ${collection}`);
            await dialog.getByRole('tab', { name: labels[permitted], exact: true }).click();
            await expect(dialog.getByRole('checkbox', { name: collection === 'agent' ? base.name : book.name, exact: true })).toBeChecked();
            await dialog.getByRole('button', { name: words(locale, 'common').close, exact: true }).click();
          }

          const session = await (await request.post('/api/sessions', { data: { title: `Bindings ${tag}`, persona_id: createdIds[0] } })).json();
          sessionId = session.session_id;
          await page.goto('/');
          await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
          dialog = page.getByRole('dialog', { name: labels.sessionSettings, exact: true });
          await dialog.getByLabel(labels.agentPersona, { exact: true }).click();
          await expect(page.getByRole('option', { name: `agent ${tag}`, exact: true })).toBeVisible();
          await expect(page.getByRole('option', { name: `roleplay_user ${tag}`, exact: true })).toHaveCount(0);
          await expect(page.getByRole('option', { name: `character ${tag}`, exact: true })).toHaveCount(0);
          await page.keyboard.press('Escape');
          await dialog.getByRole('tab', { name: labels.knowledge, exact: true }).click();
          for (const section of [labels.userPersonaBindings, labels.agentPersonaBindings]) {
            const checkbox = dialog.getByRole('region', { name: section }).getByRole('checkbox', { name: base.name, exact: true });
            await expect(checkbox).toBeChecked();
            await expect(checkbox).toBeDisabled();
          }
          await page.screenshot({ path: info.outputPath('persona-knowledge.png') });
          await dialog.getByRole('button', { name: words(locale, 'common').close, exact: true }).click();
          await request.delete(`/api/sessions/${sessionId}`);
          sessionId = '';
          for (const [index, collection] of ['agent', 'roleplay_user', 'character'].entries()) {
            await page.goto(`/settings?tab=personas&view=${collection}`);
            const row = page.locator('.persona-row').filter({ hasText: `${collection} ${tag}` });
            await row.getByRole('button', { name: labels.deleteNamed.replace('{{name}}', `${collection} ${tag}`), exact: true }).click();
            await answerConfirmation(page, true, locale);
            await expect(row).toHaveCount(0);
            expect((await request.get(`/api/personas/${createdIds[index]}`)).status()).toBe(404);
          }
        } finally {
          if (sessionId) await request.delete(`/api/sessions/${sessionId}`);
          for (const id of createdIds) await request.delete(`/api/personas/${id}`);
          await request.patch(`/api/personas/${cogita.id}`, { data: identity(cogita) });
          await request.patch(`/api/personas/${user.id}/knowledge-bases`, { data: userBindings });
          await request.delete(`/api/knowledge/bases/${base.id}`);
          await request.delete(`/api/worldbooks/${book.id}`);
        }
      });

      test('historical user messages and context labels show the latest identity', async ({ page, request }, info) => {
        test.setTimeout(90000);
        const user = await singleton(request);
        const tag = `${locale}-${viewport.width}-${Date.now()}`;
        const first = await (await request.post('/api/sessions', { data: { title: `Identity first ${tag}` } })).json();
        const second = await (await request.post('/api/sessions', { data: { title: `Identity second ${tag}` } })).json();
        try {
          expect((await request.post(`/api/sessions/${first.session_id}/messages`, { data: { content: 'Historical user text' } })).ok()).toBe(true);
          await page.goto('/');
          await expect(page.locator('.message-row.user .message-meta strong')).toHaveText(user.name);
          await page.goto('/settings?tab=personas&view=user');
          const panel = page.locator('[data-persona-collection="user"]');
          await panel.getByLabel(labels.name, { exact: true }).fill(`Latest ${tag}`);
          await panel.getByLabel(labels.systemPrompt, { exact: true }).fill('Current personal background');
          await panel.locator('input[type="file"]').setInputFiles({ name: 'identity.png', mimeType: 'image/png', buffer: png });
          await expect(panel.locator('[data-slot="avatar-image"]')).toBeVisible();
          await panel.getByRole('button', { name: labels.save, exact: true }).click();
          await expect(panel.getByRole('status')).toHaveText(labels.saved);
          const saved = await singleton(request);
          expect(saved.name).toBe(`Latest ${tag}`);
          expect(saved.avatar_attachment_id).toBeTruthy();
          await backToChat(page);
          let row = page.locator('.message-row.user');
          await expect(row.locator('.message-meta strong')).toHaveText(saved.name);
          await expect(row.locator('[data-slot="avatar-image"]')).toHaveAttribute('src', new RegExp(saved.avatar_attachment_id));
          await page.reload();
          await expect(row.locator('.message-meta strong')).toHaveText(saved.name);
          await request.patch(`/api/personas/${user.id}`, { data: { name: `Live ${tag}` } });
          await expect(row.locator('.message-meta strong')).toHaveText(`Live ${tag}`);
          await request.patch(`/api/sessions/${first.session_id}`, { data: { context_policy: { mode: 'selected_message' } } });
          await page.locator('.composer-context [data-slot="select-trigger"]').click();
          await expect(page.getByRole('option', { name: `Live ${tag}: Historical user text`, exact: true })).toBeVisible();
          await page.keyboard.press('Escape');
          await openSidebar(page);
          await page.locator('.session-select').filter({ hasText: `Identity second ${tag}` }).click();
          await page.locator('.composer textarea').fill('New user text');
          await page.getByRole('button', { name: labels.send, exact: true }).click();
          row = page.locator('.message-row.user');
          await expect(row.locator('.message-meta strong')).toHaveText(`Live ${tag}`);
          await expect(row.locator('[data-slot="avatar-image"]')).toHaveAttribute('src', new RegExp(saved.avatar_attachment_id));
          await expect(page.locator('.message-row.assistant')).toHaveCount(1);
          await page.screenshot({ path: info.outputPath('latest-user-identity.png') });
          await expect(page.getByRole('button', { name: labels.cancel, exact: true })).toHaveCount(0);
          await page.goto('/settings?tab=personas&view=user');
          await page.getByRole('button', { name: labels.removeAvatar, exact: true }).click();
          await page.locator('[data-persona-collection="user"]').getByRole('button', { name: labels.save, exact: true }).click();
          await expect(page.getByRole('status')).toHaveText(labels.saved);
          await backToChat(page);
          await expect(page.locator('.message-row.user [data-slot="avatar-image"]')).toHaveCount(0);
          expect((await request.get(`/api/attachments/${saved.avatar_attachment_id}`)).status()).toBe(404);
        } finally {
          await request.patch(`/api/personas/${user.id}`, { data: identity(user) });
          await request.delete(`/api/sessions/${first.session_id}`);
          await request.delete(`/api/sessions/${second.session_id}`);
        }
      });
    });
  }
}
