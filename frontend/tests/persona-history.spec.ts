import { readFileSync } from 'node:fs';
import { expect, test, type APIResponse } from '@playwright/test';
import { readMessages, readRuns } from './history';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=', 'base64');
async function json(response: Promise<APIResponse>) {
  const value = await response;
  expect(value.ok(), await value.text()).toBe(true);
  return value.json();
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const labels = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  test.describe(`Persona history ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('original user authors and the fixed Character update live through edits, retries and deletion', async ({ page, request }, info) => {
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const first = await json(request.post('/api/personas', { data: { name: 'First user', background: 'Original user background' } }));
      const second = await json(request.post('/api/personas', { data: { name: 'Second user' } }));
      const character = await json(request.post('/api/characters', { data: { kind: 'normal', name: 'Fixed Character', persona_id: first.id } }));
      const session = await json(request.post(`/api/characters/${character.id}/sessions`, { data: {} }));
      const path = `/api/sessions/${session.session_id}`;
      try {
        const reply = await json(request.post(path + '/messages', { data: { content: 'First historical input' } }));
        const input = (await readMessages(request, session.session_id)).find((message) => message.role === 'user');
        await json(request.patch(path, { data: { overrides: { persona_id: second.id } } }));
        await page.goto(`/characters/${character.id}?session=${session.session_id}`);
        const originalUser = page.locator(`[data-message-id="${input.message_id}"]`);
        await expect(originalUser.locator('.message-meta strong')).toHaveText(first.name);
        const avatar = await json(request.post('/api/attachments', { multipart: { file: { name: 'avatar.png', mimeType: 'image/png', buffer: png } } }));
        const avatarId = avatar.uri.split('/').pop();
        await json(request.patch(`/api/personas/${first.id}`, { data: { name: 'Renamed original user', avatar_attachment_id: avatarId, background: 'Updated original background' } }));
        await expect(originalUser.locator('.message-meta strong')).toHaveText('Renamed original user');
        await expect(originalUser.locator('[data-slot="avatar-image"]')).toHaveAttribute('src', new RegExp(avatarId));
        const retried = await json(request.post(`/api/runs/${reply.run.run_id}/retry`));
        expect(retried.run.persona_id).toBe(first.id);
        expect((await json(request.get(path))).effective.persona_id).toBe(second.id);
        await expect(page.locator(`[data-run-id="${retried.run.run_id}"] .reply-answer`)).toHaveText('Browser final answer.');
        await page.locator('.composer textarea').fill('Second historical input');
        await page.locator('.composer textarea').press('Enter');
        await expect(page.locator('.message-row.user .message-meta strong')).toHaveText(['Renamed original user', second.name]);
        await expect(page.locator('.reply-answer')).toHaveCount(2);
        await json(request.patch(`/api/characters/${character.id}`, { data: { name: 'Renamed Character' } }));
        await expect(page.locator('.message-row.assistant .message-meta strong')).toHaveText(['Renamed Character', 'Renamed Character']);
        await json(request.patch(`/api/characters/${character.id}`, { data: { persona_id: second.id } }));
        await json(request.delete(`/api/personas/${first.id}`));
        await expect(originalUser.locator('.message-meta strong')).toHaveText(labels.deletedPersona);
        await page.reload();
        await expect(originalUser.locator('.message-meta strong')).toHaveText(labels.deletedPersona);
        const before = await readMessages(request, session.session_id);
        expect((await request.post(`/api/runs/${retried.run.run_id}/retry`)).status()).toBe(404);
        expect((await readMessages(request, session.session_id)).map((message) => message.message_id)).toEqual(before.map((message) => message.message_id));
        await page.screenshot({ path: info.outputPath('original-persona-history.png') });
      } finally {
        for (const run of await readRuns(request, session.session_id)) {
          if (!['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status)) await request.post(`/api/runs/${run.run_id}/cancel`);
        }
        await request.delete(`/api/characters/${character.id}`);
        await request.delete(`/api/personas/${first.id}`);
        await request.delete(`/api/personas/${second.id}`);
      }
    });
  });
}
