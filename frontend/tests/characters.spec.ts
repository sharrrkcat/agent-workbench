import { readFileSync } from 'node:fs';
import { expect, test, type APIResponse } from '@playwright/test';
import { COGITA_CHARACTER_ID } from '../src/types/chat';
import { answerConfirmation, chooseOption, openSidebar } from './controls';

async function json(response: Promise<APIResponse>) {
  const result = await response;
  expect(result.ok(), await result.text()).toBe(true);
  return result.json();
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const labels = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  const llm = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  test.describe(`Characters ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test.beforeEach(async ({ page, request }) => {
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
    });

    test('Session overrides replace complete defaults and restore inheritance', async ({ page, request }) => {
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      const personas = [];
      for (const name of ['First user', 'Second user']) personas.push(await json(request.post('/api/personas', { data: { name } })));
      const embedding = (await json(request.get('/api/models/profiles'))).find((model: { kind: string }) => model.kind === 'embedding');
      const bases = [];
      for (const name of ['First mount', 'Second mount']) bases.push(await json(request.post('/api/knowledge/bases', { data: { name, embedding_model_profile_id: embedding.id } })));
      const book = await json(request.post('/api/worldbooks', { data: { name: 'Character worldbook' } }));
      const character = await json(request.post('/api/characters', { data: { kind: 'normal', name: 'Inherited Character',
        persona_id: personas[0].id, temperature: 0.6, tools_allowed: [], knowledge_base_ids: [bases[0].id], worldbook_ids: [book.id] } }));
      try {
        const first = await json(request.post(`/api/characters/${character.id}/sessions`, { data: { title: 'Overrides' } }));
        const sibling = await json(request.post(`/api/characters/${character.id}/sessions`, { data: { title: 'Inherited sibling' } }));
        await page.goto(`/characters/${character.id}?session=${first.session_id}`);
        await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
        const dialog = page.getByRole('dialog', { name: labels.sessionSettings, exact: true });
        await chooseOption(dialog.getByLabel(labels.persona, { exact: true }), personas[1].name);
        await dialog.getByLabel(llm.params.temperature, { exact: true }).fill('0');
        await dialog.getByRole('switch', { name: labels.reasoning, exact: true }).uncheck();
        await dialog.getByRole('checkbox', { name: 'test_echo', exact: true }).check();
        await dialog.getByRole('button', { name: labels.messageWindow, exact: true }).click();
        await dialog.getByLabel(labels.maxMessages, { exact: true }).fill('5');
        await dialog.getByRole('tab', { name: labels.resources, exact: true }).click();
        await expect(dialog.getByText(labels.mountsInactive, { exact: true })).toBeVisible();
        await dialog.getByRole('checkbox', { name: bases[0].name, exact: true }).uncheck();
        await dialog.getByRole('checkbox', { name: bases[1].name, exact: true }).check();
        await dialog.getByRole('checkbox', { name: book.name, exact: true }).uncheck();
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toBeHidden();
        const saved = await json(request.get(`/api/sessions/${first.session_id}`));
        expect(saved.overrides).toMatchObject({ persona_id: personas[1].id, temperature: 0, reasoning: false,
          tools_allowed: ['test_echo'], knowledge_base_ids: [bases[1].id], worldbook_ids: [],
          context_policy: { strategy: 'message_window', message_window: { max_messages: 5 } } });
        await json(request.patch(`/api/characters/${character.id}`, { data: { temperature: 0.9,
          knowledge_base_ids: bases.map((base) => base.id), context_policy: { strategy: 'message_window', message_window: { max_messages: 12 } } } }));
        expect((await json(request.get(`/api/sessions/${sibling.session_id}`))).effective).toMatchObject({
          knowledge_base_ids: bases.map((base) => base.id), context_policy: { message_window: { max_messages: 12 } }, generation: { temperature: 0.9 } });
        expect((await json(request.get(`/api/sessions/${first.session_id}`))).effective).toMatchObject({
          knowledge_base_ids: [bases[1].id], context_policy: { message_window: { max_messages: 5 } }, generation: { temperature: 0 } });
        await page.reload();
        await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
        for (const field of [labels.persona, llm.params.temperature, labels.reasoning, labels.tools, labels.context]) {
          await dialog.getByRole('button', { name: labels.restoreInheritanceFor.replace('{{field}}', field), exact: true }).click();
        }
        await dialog.getByRole('tab', { name: labels.resources, exact: true }).click();
        for (const field of [labels.knowledge, labels.worldbook]) {
          await dialog.getByRole('button', { name: labels.restoreInheritanceFor.replace('{{field}}', field), exact: true }).click();
        }
        await expect(dialog.getByRole('checkbox', { name: bases[0].name, exact: true })).toBeChecked();
        await expect(dialog.getByRole('checkbox', { name: book.name, exact: true })).toBeChecked();
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toBeHidden();
        expect((await json(request.get(`/api/sessions/${first.session_id}`))).overrides).toEqual({});
        expect(errors).toEqual([]);
      } finally {
        await request.delete(`/api/characters/${character.id}`);
        for (const persona of personas) await request.delete(`/api/personas/${persona.id}`);
        for (const base of bases) await request.delete(`/api/knowledge/bases/${base.id}`);
        await request.delete(`/api/worldbooks/${book.id}`);
      }
    });

    test('remembered Sessions, settings history and cascade deletion follow their Character', async ({ page, request }, info) => {
      const character = await json(request.post('/api/characters', { data: { kind: 'normal', name: 'Navigation Character' } }));
      try {
        const first = await json(request.post(`/api/characters/${character.id}/sessions`, { data: { title: 'First conversation' } }));
        const second = await json(request.post(`/api/characters/${character.id}/sessions`, { data: { title: 'Second conversation' } }));
        await page.goto(`/characters/${character.id}?session=${first.session_id}`);
        await expect(page.locator('.chat-title')).toHaveText(first.title);
        await page.reload();
        await expect(page.locator('.chat-title')).toHaveText(first.title);
        await openSidebar(page);
        await page.locator(`[data-character-id="${COGITA_CHARACTER_ID}"] .character-select`).click();
        await expect(page).toHaveURL(`/characters/${COGITA_CHARACTER_ID}`);
        await openSidebar(page);
        const characterRow = page.locator(`[data-character-id="${character.id}"]`);
        await characterRow.locator('.character-select').click();
        await expect(page.locator('.chat-title')).toHaveText(first.title);
        await openSidebar(page);
        await characterRow.getByRole('button', { name: second.title, exact: true }).click();
        await expect(page.locator('.chat-title')).toHaveText(second.title);
        await openSidebar(page);
        await characterRow.getByRole('button', { name: labels.characterActions.replace('{{name}}', character.name), exact: true }).click();
        await page.getByRole('menuitem', { name: labels.characterSettings, exact: true }).click();
        await expect(page).toHaveURL(`/characters/${character.id}/settings`);
        await page.getByLabel(labels.characterName, { exact: true }).fill('Unsaved Character');
        await page.evaluate(() => history.back());
        await answerConfirmation(page, false, locale);
        await expect(page.getByLabel(labels.characterName, { exact: true })).toHaveValue('Unsaved Character');
        await page.evaluate(() => history.back());
        await answerConfirmation(page, true, locale);
        await expect(page).toHaveURL(`/characters/${character.id}?session=${second.session_id}`);
        await expect(page.locator('.chat-title')).toHaveText(second.title);
        await openSidebar(page);
        await characterRow.getByRole('button', { name: labels.characterActions.replace('{{name}}', character.name), exact: true }).click();
        await page.getByRole('menuitem', { name: labels.deleteCharacter, exact: true }).click();
        await page.getByRole('dialog').getByRole('button', { name: locale === 'en' ? 'Delete owner' : '删除归属对象', exact: true }).click();
        await expect(characterRow).toHaveCount(0);
        await expect(page).toHaveURL('/');
        expect((await request.get(`/api/sessions/${first.session_id}`)).status()).toBe(404);
        expect((await request.get(`/api/sessions/${second.session_id}`)).status()).toBe(404);
        await openSidebar(page);
        const cogita = page.locator(`[data-character-id="${COGITA_CHARACTER_ID}"]`);
        await cogita.getByRole('button', { name: labels.characterActions.replace('{{name}}', 'Cogita'), exact: true }).click();
        await expect(page.getByRole('menuitem', { name: labels.deleteCharacter, exact: true })).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('protected-character.png') });
      } finally { await request.delete(`/api/characters/${character.id}`); }
    });
  });
}
