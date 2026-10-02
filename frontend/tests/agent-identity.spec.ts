import { readFileSync } from 'node:fs';
import { expect, test, type APIResponse } from '@playwright/test';

const words = (locale: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=', 'base64');
async function json(response: Promise<APIResponse>) {
  const result = await response;
  expect(result.ok(), await result.text()).toBe(true);
  return result.json();
}

for (const locale of ['en', 'zh-CN']) {
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`Agent identity ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      for (const kind of ['ordinary', 'workspace']) {
        test(`${kind} history follows original personas through edits, streaming and deletion`, async ({ page, request }, info) => {
          test.setTimeout(90000);
          const labels = words(locale);
          await page.addInitScript((language) => {
            localStorage.setItem('cogita.locale', language);
            const sockets: WebSocket[] = [];
            Object.assign(window, { testSessionSockets: sockets });
            const NativeSocket = window.WebSocket;
            window.WebSocket = class extends NativeSocket {
              constructor(url: string | URL, protocols?: string | string[]) {
                super(url, protocols);
                if (String(url).includes('/api/ws/')) sockets.push(this);
              }
            };
          }, locale);
          const first = await json(request.post('/api/personas', { data: { collection: 'agent', name: 'First agent' } }));
          const second = await json(request.post('/api/personas', { data: { collection: 'agent', name: 'Second agent' } }));
          const user = (await json(request.get('/api/personas?collection=user')))[0];
          let projectId = '', sessionId = '';
          try {
            if (kind === 'workspace') {
              const project = await json(request.post('/api/projects', { data: {
                kind: 'workspace', name: 'Identity workspace', agent_persona_id: first.id, cogita_persona_id: user.id,
                context_policy: {}, harness_enabled: true, tools_allowed: ['read_file'],
              } }));
              projectId = project.id;
              sessionId = (await json(request.post(`/api/projects/${projectId}/sessions`, { data: {} }))).session_id;
            } else {
              sessionId = (await json(request.post('/api/sessions', { data: {
                persona_id: first.id, context_policy: {}, harness_enabled: true, tools_allowed: ['read_file'],
              } }))).session_id;
            }
            const sessionPath = `/api/sessions/${sessionId}`;
            const firstReply = await json(request.post(sessionPath + '/messages', { data: { content: 'First historical input' } }));
            await json(request.patch(kind === 'workspace' ? `/api/projects/${projectId}` : sessionPath,
              { data: kind === 'workspace' ? { agent_persona_id: second.id } : { persona_id: second.id } }));
            const secondReply = await json(request.post(sessionPath + '/messages', { data: { content: 'Second historical input' } }));
            await page.goto(projectId ? `/projects/${projectId}?session=${sessionId}` : '/');
            const firstRow = page.locator(`.message-row[data-run-id="${firstReply.run.run_id}"]`);
            const secondRow = page.locator(`.message-row[data-run-id="${secondReply.run.run_id}"]`);
            await expect(firstRow.locator('strong').first()).toHaveText(first.name);
            await expect(secondRow.locator('strong').first()).toHaveText(second.name);
            for (const name of ['Latest agent', 'Replaced avatar']) {
              const upload = await json(request.post('/api/attachments', { multipart: { file: { name: 'avatar.png', mimeType: 'image/png', buffer: png } } }));
              const avatar = upload.uri.split('/').pop();
              await json(request.patch(`/api/personas/${first.id}`, { data: { name, avatar_attachment_id: avatar } }));
              await expect(firstRow.locator('strong').first()).toHaveText(name);
              await expect(firstRow.locator('[data-slot="avatar-image"]')).toHaveAttribute('src', new RegExp(avatar));
              await expect(secondRow.locator('strong').first()).toHaveText(second.name);
            }
            await json(request.patch(`/api/personas/${first.id}`, { data: { avatar_attachment_id: null } }));
            await expect(firstRow.locator('[data-slot="avatar-image"]')).toHaveCount(0);
            await page.reload();
            await expect(firstRow.locator('strong').first()).toHaveText('Replaced avatar');
            // Close the real session socket, edit while disconnected, then check reconnect reconciliation.
            await page.evaluate(async () => {
              const { testSessionSockets } = window as unknown as { testSessionSockets: WebSocket[] };
              const socket = testSessionSockets.at(-1)!;
              await new Promise<void>((resolve) => { socket.addEventListener('close', () => resolve(), { once: true }); socket.close(); });
            });
            await json(request.patch(`/api/personas/${first.id}`, { data: { name: 'After reconnect' } }));
            await expect(firstRow.locator('strong').first()).toHaveText('After reconnect');
            await json(request.delete(`/api/personas/${first.id}`));
            await expect(firstRow.locator('strong').first()).toHaveText(labels.deletedPersona);
            await expect(firstRow.locator('.reply-answer')).toHaveText('Browser final answer.');
            await page.locator('.composer textarea').fill('cancel-stream');
            await page.locator('.composer textarea').press('Enter');
            await expect(page.locator('.reply-answer').last()).toContainText('Incomplete streamed answer.');
            await json(request.patch(`/api/personas/${second.id}`, { data: { name: 'Live agent' } }));
            await expect(page.locator('.message-row.assistant .message-meta strong').last()).toHaveText('Live agent');
            await page.getByRole('button', { name: labels.cancel, exact: true }).click();
            await expect(page.getByRole('button', { name: labels.cancel, exact: true })).toHaveCount(0);
            await page.locator('.composer textarea').fill('approval');
            await page.locator('.composer textarea').press('Enter');
            await expect.poll(async () => (await json(request.get(sessionPath))).waiting_run_id).toBeTruthy();
            const waiting = (await json(request.get(sessionPath))).waiting_run_id;
            await json(request.patch(`/api/personas/${second.id}`, { data: { name: 'Approval agent' } }));
            const waitingRow = page.locator(`.message-row[data-run-id="${waiting}"]`);
            await expect(waitingRow.locator('.message-meta strong')).toHaveText('Approval agent');
            await json(request.post(`/api/tools/approvals/${waiting}`, { data: { decision: 'approve' } }));
            await expect(waitingRow.locator('.reply-answer')).toHaveText('Browser final answer.');
            await expect(waitingRow.locator('.message-meta strong')).toHaveText('Approval agent');
            await expect(secondRow.locator('.message-meta strong')).toHaveText('Approval agent');
            await page.screenshot({ path: info.outputPath('live-agent-identity.png') });
          } finally {
            if (sessionId) {
              for (const run of await json(request.get(`/api/sessions/${sessionId}/runs`))) {
                if (!['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status)) await request.post(`/api/runs/${run.run_id}/cancel`);
              }
              await request.delete(`/api/sessions/${sessionId}`);
            }
            if (projectId) await request.delete(`/api/projects/${projectId}`);
            await request.delete(`/api/personas/${first.id}`);
            await request.delete(`/api/personas/${second.id}`);
          }
        });
      }
    });
  }
}
