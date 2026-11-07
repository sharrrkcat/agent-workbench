import { readFileSync } from 'node:fs';
import { expect, test, type APIResponse } from '@playwright/test';
import { answerConfirmation, chooseOption, openSidebar } from './controls';

async function json(response: Promise<APIResponse>) {
  const result = await response; expect(result.ok(), await result.text()).toBe(true); return result.json();
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const labels = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/memory.json`, import.meta.url), 'utf8'));
  const personas = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  test.describe(`Memory ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
    test('manage, publish and explicitly keep private Session memories', async ({ page, request }, info) => {
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message));
      const persona = await json(request.post('/api/personas', { data: { name: `Memory user ${locale} ${width}` } }));
      const owner = await json(request.post('/api/characters', { data: { kind: 'normal', name: `Memory Character ${locale} ${width}`, persona_id: persona.id } }));
      const session = await json(request.post(`/api/characters/${owner.id}/sessions`, { data: { title: 'Private tea', memory_isolation: 'isolated' } }));
      await json(request.post(`/api/sessions/${session.session_id}/messages`, { data: { content: 'I like oolong tea.' } }));
      await page.goto(`/characters/${owner.id}?session=${session.session_id}`);
      await page.getByRole('button', { name: personas.sessionSettings, exact: true }).click();
      const settings = page.getByRole('dialog', { name: personas.sessionSettings });
      await expect(settings.getByText(labels.boundPersona, { exact: true })).toBeVisible();
      await expect(settings.getByRole('combobox', { name: personas.persona, exact: true })).toHaveCount(0);
      await settings.getByRole('tab', { name: labels.title, exact: true }).click();
      await settings.getByRole('button', { name: labels.add, exact: true }).click();
      const editor = page.getByRole('dialog', { name: labels.add, exact: true });
      await editor.getByLabel(labels.summary, { exact: true }).fill('Oolong preference');
      await editor.getByLabel(labels.body, { exact: true }).fill('The user prefers oolong tea.');
      await editor.getByRole('button', { name: labels.save, exact: true }).click();
      await expect(editor).toBeHidden();
      await settings.getByRole('button', { name: 'Oolong preference', exact: true }).click();
      await settings.getByRole('button', { name: labels.actions, exact: true }).click();
      await page.getByRole('menuitem', { name: labels.publish, exact: true }).click();
      await answerConfirmation(page, true, locale);
      const stored = await json(request.get('/api/memories', { params: { character_id: owner.id } }));
      expect(stored.total).toBe(2);
      const original = stored.items.find((entry: { pool: string }) => entry.pool === 'character');
      await page.screenshot({ path: info.outputPath('session-memory.png'), animations: 'disabled' });
      await page.keyboard.press('Escape');
      await openSidebar(page);
      const row = page.locator(`[data-character-id="${owner.id}"]`);
      await row.locator('.session-menu').click();
      await page.getByRole('menuitem', { name: personas.deleteSession, exact: true }).click();
      const deletion = page.getByRole('dialog', { name: labels.deleteOwner.replace('{{name}}', session.title) });
      await expect(deletion.getByRole('button', { name: labels.deleteConfirm, exact: true })).toBeDisabled();
      const local = deletion.getByRole('group', { name: labels.deleteLocal.replace('{{count}}', '1') }).last();
      await local.getByRole('button', { name: labels.keep, exact: true }).click();
      const general = deletion.getByRole('group', { name: labels.deleteGeneral.replace('{{count}}', '1') }).last();
      await general.getByRole('button', { name: labels.keep, exact: true }).click();
      await expect(deletion.getByText(labels.keepSessionNotice)).toBeVisible();
      await page.screenshot({ path: info.outputPath('delete-memory-choice.png'), animations: 'disabled' });
      await deletion.getByRole('button', { name: labels.deleteConfirm, exact: true }).click();
      await expect(deletion).toBeHidden();
      const kept = await json(request.get(`/api/memories/${original.id}`));
      expect(kept.session_id).toBeNull(); expect(kept.persona_id).toBe(persona.id);
      await page.goto('/settings?tab=memory');
      await chooseOption(page.getByRole('combobox', { name: labels.persona, exact: true }), persona.name);
      await expect(page.locator('[data-memory-id]')).toHaveCount(2);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
      const preview = await json(request.get(`/api/characters/${owner.id}/memory-deletion-preview`));
      await json(request.delete(`/api/characters/${owner.id}`, { data: { expected_revision: preview.revision, local: 'delete', general: 'delete' } }));
      await request.delete(`/api/personas/${persona.id}`);
    });

    test('save from a message, edit, transfer Character memories and forget', async ({ page, request }, info) => {
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message));
      const owner = await json(request.post('/api/characters', { data: { kind: 'normal', name: `Source ${locale} ${width}` } }));
      const target = await json(request.post('/api/characters', { data: { kind: 'normal', name: `Target ${locale} ${width}` } }));
      const session = await json(request.post(`/api/characters/${owner.id}/sessions`, { data: { title: 'Source conversation' } }));
      const result = await json(request.post(`/api/sessions/${session.session_id}/messages`, { data: { content: 'My confirmed tea is oolong.' } }));
      const userId = result.run.metadata.input_message_id;
      await page.goto(`/characters/${owner.id}?session=${session.session_id}`);
      const user = page.locator(`article[data-message-id="${userId}"]`);
      await user.hover();
      await user.getByRole('button', { name: labels.fromMessage, exact: true }).click();
      const editor = page.getByRole('dialog', { name: labels.add, exact: true });
      await expect(editor.getByLabel(labels.body, { exact: true })).toHaveValue('My confirmed tea is oolong.');
      await editor.getByLabel(labels.summary, { exact: true }).fill('Saved from message');
      await editor.getByRole('button', { name: labels.save, exact: true }).click();
      await expect(editor).toBeHidden();
      await page.goto(`/characters/${owner.id}/settings`);
      await chooseOption(page.getByRole('combobox', { name: labels.session, exact: true }), session.title);
      await page.getByRole('button', { name: 'Saved from message', exact: true }).click();
      await page.getByRole('button', { name: labels.actions, exact: true }).click();
      await page.getByRole('menuitem', { name: labels.edit, exact: true }).click();
      const edit = page.getByRole('dialog', { name: labels.edit, exact: true });
      await edit.getByLabel(labels.body, { exact: true }).fill('Manually confirmed oolong preference.');
      await edit.getByRole('button', { name: labels.save, exact: true }).click();
      await expect(edit).toBeHidden();
      await expect(page).toHaveURL(`/characters/${owner.id}/settings`);
      await openSidebar(page);
      const ownerRow = page.locator(`[data-character-id="${owner.id}"]`);
      await ownerRow.getByRole('button', { name: personas.characterActions.replace('{{name}}', owner.name), exact: true }).click();
      await page.getByRole('menuitem', { name: personas.deleteCharacter, exact: true }).click();
      const deletion = page.getByRole('dialog', { name: labels.deleteOwner.replace('{{name}}', owner.name), exact: true });
      await deletion.getByRole('button', { name: labels.transfer, exact: true }).click();
      await chooseOption(deletion.getByRole('combobox', { name: labels.destination, exact: true }), target.name);
      await deletion.getByRole('button', { name: labels.deleteConfirm, exact: true }).click();
      await expect(deletion).toBeHidden();
      await page.goto(`/characters/${target.id}/settings`);
      await page.getByRole('button', { name: 'Saved from message', exact: true }).click();
      await expect(page.getByText('Manually confirmed oolong preference.', { exact: true })).toBeVisible();
      await page.screenshot({ path: info.outputPath('transferred-memory.png'), animations: 'disabled' });
      await page.getByRole('button', { name: labels.origin, exact: true }).click();
      const source = page.getByRole('dialog', { name: labels.origin, exact: true });
      await expect(source.getByText(labels.sourceSession.replace('{{name}}', labels.deletedSource).replace('{{id}}', session.session_id), { exact: true })).toBeVisible();
      await page.keyboard.press('Escape'); await expect(source).toBeHidden();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.getByRole('button', { name: labels.actions, exact: true }).click();
      await page.getByRole('menuitem', { name: labels.delete, exact: true }).click();
      await answerConfirmation(page, true, locale);
      await expect(page.getByText(labels.empty, { exact: true })).toBeVisible();
      expect(errors).toEqual([]);
      await json(request.delete(`/api/characters/${target.id}`));
    });

    test('compact toolbar preserves refresh positions and empty cards fit their content', async ({ page, request }, info) => {
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const persona = await json(request.post('/api/personas', { data: { name: 'Memory badge' } }));
      const owner = await json(request.post('/api/characters', { data: { kind: 'normal', name: 'Memory layout', persona_id: persona.id } }));
      for (let index = 0; index < 12; index++) await json(request.post('/api/memories', { data: {
        character_id: owner.id, persona_id: persona.id, pool: 'character', summary: `Fact ${index}`, body: `Remembered fact ${index}.`, pinned: false,
      } }));
      let release: (() => void) | undefined;
      try {
        for (const destination of [`/characters/${owner.id}/settings`, '/settings?tab=memory']) {
          await page.goto(destination);
          const manager = page.locator('[data-memory-manager]');
          if (destination.startsWith('/characters/')) {
            const settings = page.locator('[data-character-card="memory"]');
            await settings.getByRole('button', { name: labels.add, exact: true }).click();
            const editor = page.getByRole('dialog', { name: labels.add, exact: true });
            await expect(editor).toBeVisible(); await editor.getByRole('button', { name: labels.cancel, exact: true }).click();
            await expect(editor).toBeHidden();
            await expect(manager.getByRole('button', { name: labels.add, exact: true })).toHaveCount(0);
          } else await chooseOption(manager.getByRole('combobox', { name: labels.character, exact: true }), owner.name);
          await expect(manager.locator('[data-memory-id]')).toHaveCount(12);
          await expect(manager.locator('.memory-results')).toHaveAttribute('aria-busy', 'false');
          const row = manager.locator('[data-memory-id]').first();
          const summary = row.getByRole('button').first();
          await expect(summary.locator('[data-slot="badge"]')).toHaveText(persona.name);
          await summary.click();
          await expect(row.getByText(/Remembered fact/)).toBeVisible();
          await expect(row.locator('[data-slot="card"]')).toContainText(/Remembered fact/);
          await row.getByRole('button', { name: labels.origin, exact: true }).click();
          const source = page.getByRole('dialog', { name: labels.origin, exact: true });
          await expect(source.getByText(labels.manualSource, { exact: true })).toBeVisible();
          await page.keyboard.press('Escape'); await expect(source).toBeHidden();
          await expect(row.getByRole('button', { name: labels.origin, exact: true })).toBeFocused();
          await row.getByRole('button', { name: labels.actions, exact: true }).click();
          await expect(page.getByRole('menuitem')).toHaveCount(3);
          await page.keyboard.press('Escape'); await expect(page.getByRole('menu')).toBeHidden();
          const toolbar = manager.locator('.memory-toolbar');
          const selectors = toolbar.getByRole('combobox');
          const controls = await toolbar.locator('.memory-search input, [data-slot="select-trigger"]').evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().y));
          expect(Math.max(...controls) - Math.min(...controls)).toBeLessThan(2);
          await toolbar.scrollIntoViewIfNeeded();
          const top = (await toolbar.boundingBox())!.y;
          let reads = 0;
          const gate = new Promise<void>((resolve) => { release = resolve; });
          await page.route('**/api/memories?**', async (route) => { reads++; await gate; await route.continue(); });
          for (const filter of [labels.persona, labels.pool, labels.session]) {
            const trigger = selectors.filter({ hasText: filter });
            await trigger.click();
            expect(Math.abs((await toolbar.boundingBox())!.y - top)).toBeLessThan(2);
            await page.locator('[data-slot="select-content"][data-open]').getByRole('option', {
              name: filter === labels.pool && destination.startsWith('/characters/') ? labels.characterPool : labels.all, exact: true,
            }).click();
            await expect(trigger).toHaveAttribute('aria-expanded', 'false');
            expect(Math.abs((await toolbar.boundingBox())!.y - top)).toBeLessThan(2);
          }
          expect(reads).toBe(0);
          await chooseOption(manager.getByRole('combobox', { name: labels.persona, exact: true }), persona.name);
          await expect(manager.locator('.memory-results')).toHaveAttribute('aria-busy', 'true');
          await expect(row.getByText(/Remembered fact/)).toBeVisible();
          expect(Math.abs((await toolbar.boundingBox())!.y - top)).toBeLessThan(2);
          release!();
          await expect(manager.locator('.memory-results')).toHaveAttribute('aria-busy', 'false');
          await expect(row.getByText(/Remembered fact/)).toBeVisible();
          expect(Math.abs((await toolbar.boundingBox())!.y - top)).toBeLessThan(2);
          await page.unroute('**/api/memories?**');
          await chooseOption(manager.getByRole('combobox', { name: labels.pool, exact: true }), labels.general);
          await expect(manager.getByText(labels.empty, { exact: true })).toBeVisible();
          expect((await manager.boundingBox())!.height).toBeLessThan(320);
          await expect(manager.getByRole('button', { name: labels.previous, exact: true })).toBeInViewport();
          await toolbar.evaluate((element) => { element.scrollLeft = 0; });
          await page.screenshot({ path: info.outputPath(destination.startsWith('/characters/') ? 'character-memory-empty.png' : 'settings-memory-empty.png'), animations: 'disabled' });
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
          await chooseOption(manager.getByRole('combobox', { name: labels.pool, exact: true }), labels.characterPool);
          await expect(manager.locator('[data-memory-id]')).toHaveCount(12);
          await summary.click(); await expect(row.getByText(/Remembered fact/)).toBeVisible();
          await toolbar.evaluate((element) => { element.scrollLeft = 0; });
          await page.screenshot({ path: info.outputPath(destination.startsWith('/characters/') ? 'character-memory-cards.png' : 'settings-memory-cards.png'), animations: 'disabled' });
        }
      } finally {
        release?.();
        const preview = await json(request.get(`/api/characters/${owner.id}/memory-deletion-preview`));
        await json(request.delete(`/api/characters/${owner.id}`, { data: { expected_revision: preview.revision, local: 'delete', general: 'delete' } }));
        await request.delete(`/api/personas/${persona.id}`);
      }
    });
  });
}
