import { readFileSync } from 'node:fs';
import { expect, test, type Locator } from '@playwright/test';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=', 'base64');
const image = { name: 'photo.png', mimeType: 'image/png', buffer: png };
const text = { name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('A text attachment') };
const card = '[data-slot="attachment"]';
const bubble = '[data-slot="bubble"]';
async function keyboardClick(button: Locator) { await button.focus(); await button.press('Enter'); }

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`Chat attachments ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page, request }) => {
        const session = await (await request.post('/__test__/session')).json();
        await request.patch(`/api/sessions/${session.session_id}`, { data: { harness_enabled: false } });
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('mixed cards, previews, edit cancellation and failed-save retry', async ({ page, request }, info) => {
        await page.goto('/');
        const input = page.locator('.composer textarea');
        await input.fill('Review both attachments');
        await expect(page.locator('.composer input[type=file]')).toBeEnabled();
        await page.locator('.composer input[type=file]').setInputFiles([image, text]);
        await expect(page.locator('.upload-ready')).toHaveCount(2);
        const imageCard = page.locator('.attachment-strip [data-orientation=vertical]');
        const fileCard = page.locator('.attachment-strip [data-orientation=horizontal]');
        await expect(imageCard).toHaveCSS('width', '120px');
        await expect(imageCard).toContainText(`PNG · ${png.length} B`);
        await expect(fileCard).toContainText(`TXT · ${text.buffer.length} B`);
        const removeImage = imageCard.getByRole('button', { name: labels.removeAttachment.replace('{{name}}', image.name), exact: true });
        const imageBox = (await imageCard.boundingBox())!, removeBox = (await removeImage.boundingBox())!;
        const bottomDifference = await page.locator('.attachment-strip').evaluate((group) => {
          const image = group.querySelector('[data-orientation=vertical]')!.getBoundingClientRect();
          const file = group.querySelector('[data-orientation=horizontal]')!.getBoundingClientRect();
          return Math.abs(image.bottom - file.bottom);
        });
        expect(bottomDifference).toBeLessThanOrEqual(1);
        expect(removeBox.y).toBeLessThan(imageBox.y);
        expect(removeBox.x + removeBox.width).toBeGreaterThan(imageBox.x + imageBox.width - 1);
        if (width === 390) expect(removeBox.width).toBeGreaterThanOrEqual(44);
        expect(await removeImage.evaluate((node) => {
          const box = node.getBoundingClientRect();
          return node.contains(document.elementFromPoint(box.left + box.width / 2, box.top + 3));
        })).toBe(true);
        await page.screenshot({ path: info.outputPath('composer-attachments.png') });
        await imageCard.getByRole('button', { name: labels.previewImage.replace('{{name}}', image.name), exact: true }).click();
        await expect(page.getByRole('dialog').locator('img')).toHaveJSProperty('naturalWidth', 1);
        await page.keyboard.press('Escape');
        await page.locator('.composer').getByRole('button', { name: labels.send, exact: true }).click();
        const user = page.locator('.message-row.user').last();
        const attachments = user.locator('.message-attachments');
        await expect(attachments.locator(card)).toHaveCount(2);
        await expect(user.locator(`${bubble} ${card}`)).toHaveCount(0);
        await expect(attachments.locator('[data-orientation=vertical]')).toHaveCSS('width', '160px');
        await expect(attachments.locator('[data-orientation=vertical] [data-slot=attachment-title]')).toHaveCount(0);
        await expect(attachments.locator('[data-orientation=vertical] [data-slot=attachment-description]')).toHaveCount(0);
        const sentFile = user.locator('[data-orientation=horizontal]');
        const sentImage = user.locator('[data-orientation=vertical]');
        await expect(sentFile).toContainText(text.name);
        const assertMessageOrder = async () => {
          const file = (await sentFile.boundingBox())!, image = (await sentImage.boundingBox())!;
          const body = (await user.locator(bubble).boundingBox())!;
          expect(file.y + file.height).toBeLessThanOrEqual(body.y + 1);
          expect(image.y).toBeGreaterThanOrEqual(body.y + body.height - 1);
        };
        await assertMessageOrder();
        await page.screenshot({ path: info.outputPath('sent-attachments.png'), animations: 'disabled' });
        await expect(user.getByRole('button', { name: labels.editMessage, exact: true })).toBeEnabled();
        const edit = user.getByRole('button', { name: labels.editMessage, exact: true });
        const save = user.getByRole('button', { name: labels.save, exact: true });
        await keyboardClick(edit);
        await assertMessageOrder();
        await page.screenshot({ path: info.outputPath('editing-mixed-attachments.png'), animations: 'disabled' });
        await user.getByRole('button', { name: labels.removeAttachment.replace('{{name}}', text.name), exact: true }).click();
        await expect(attachments.locator(card)).toHaveCount(1);
        await user.getByRole('button', { name: labels.cancel, exact: true }).click();
        await expect(attachments.locator(card)).toHaveCount(2);
        await keyboardClick(edit);
        await user.getByRole('button', { name: labels.removeAttachment.replace('{{name}}', image.name), exact: true }).click();
        await page.route('**/api/messages/*/edit', (route) => route.fulfill({ status: 503,
          json: { error: { code: 'EDIT_FAILURE', message: 'Edit failed' } } }));
        await save.click();
        await expect(user.getByRole('textbox', { name: labels.messageText, exact: true })).toHaveValue('Review both attachments');
        await expect(attachments.locator(card)).toHaveCount(1);
        await expect(attachments).toContainText(text.name);
        await page.screenshot({ path: info.outputPath('editing-attachments.png') });
        await page.unroute('**/api/messages/*/edit');
        await save.click();
        await expect(edit).toBeEnabled();
        const sessions = await (await request.get('/api/sessions')).json();
        const history = await (await request.get(`/api/sessions/${sessions[0].session_id}/messages`)).json();
        expect(history.find((message: { role: string }) => message.role === 'user').metadata.attachments.map((item: { name: string }) => item.name)).toEqual([text.name]);
        await page.reload();
        await expect(attachments.locator(card)).toHaveCount(1);
        await expect(attachments).toContainText(text.name);
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
      });

      test('first send clears before acceptance and preserves the next draft after a lost response', async ({ page }, info) => {
        await page.goto('/new');
        await expect(page.locator('.composer input[type=file]')).toBeEnabled();
        await page.locator('.composer input[type=file]').setInputFiles(image);
        await expect(page.locator('.upload-ready')).toHaveCount(1);
        const input = page.locator('.composer textarea');
        await input.fill('Submitted question');
        let releaseSubmit!: () => void, releaseResponse!: () => void;
        const submitGate = new Promise<void>((resolve) => { releaseSubmit = resolve; });
        const responseGate = new Promise<void>((resolve) => { releaseResponse = resolve; });
        let posts = 0;
        await page.route('**/api/sessions/*/messages', async (route) => {
          if (route.request().method() !== 'POST') return route.continue();
          posts++;
          await submitGate;
          await route.fetch();
          await responseGate;
          await route.fulfill({ status: 503, json: { error: { code: 'LOST_RESPONSE', message: 'Response lost' } } });
        });
        await page.locator('.composer').getByRole('button', { name: labels.send, exact: true }).click();
        try {
          await expect(input).toHaveValue('');
          await expect(input).toBeDisabled();
          await expect(page.locator('.attachment-strip')).toHaveCount(0);
          releaseSubmit();
          await expect(page.locator('.message-row.user .message-attachments img')).toHaveCount(1);
          await expect(input).toBeEnabled();
          await input.fill('Next draft survives');
          await input.press('Enter');
          expect(posts).toBe(1);
          await expect(input).toHaveValue('Next draft survives');
          await page.screenshot({ path: info.outputPath('sending-next-draft.png') });
        } finally { releaseSubmit(); releaseResponse(); }
        await expect(page.locator('.composer').getByRole('button', { name: labels.send, exact: true })).toBeEnabled();
        await expect(input).toHaveValue('Next draft survives');
        await expect(page.locator('.attachment-strip')).toHaveCount(0);
        await expect(page.locator('.message-row.user')).toHaveCount(1);
      });

      test('file-only messages have no empty bubble and cannot be saved empty', async ({ page }) => {
        await page.goto('/');
        await expect(page.locator('.composer input[type=file]')).toBeEnabled();
        await page.locator('.composer input[type=file]').setInputFiles(text);
        await expect(page.locator('.upload-ready')).toHaveCount(1);
        await page.locator('.composer').getByRole('button', { name: labels.send, exact: true }).click();
        const user = page.locator('.message-row.user').last();
        await expect(user.locator('.message-attachments')).toContainText(text.name);
        await expect(user.locator(bubble)).toHaveCount(0);
        const edit = user.getByRole('button', { name: labels.editMessage, exact: true });
        await expect(edit).toBeEnabled();
        await keyboardClick(edit);
        await user.getByRole('button', { name: labels.removeAttachment.replace('{{name}}', text.name), exact: true }).click();
        const save = user.getByRole('button', { name: labels.save, exact: true });
        await expect(save).toBeDisabled();
        await user.getByRole('textbox', { name: labels.messageText, exact: true }).fill('Text replaces the file');
        await save.click();
        await expect(edit).toBeEnabled();
        await page.reload();
        await expect(user.locator('.message-attachments')).toHaveCount(0);
        await expect(user.locator(bubble)).toHaveText('Text replaces the file');
      });
    });
  }
}

test('a rejected image submission restores its usable preview and retries without another upload', async ({ page, request }) => {
  await request.post('/__test__/session');
  await page.addInitScript(() => localStorage.setItem('cogita.locale', 'en'));
  let posts = 0, uploads = 0;
  page.on('request', (request) => { if (new URL(request.url()).pathname === '/api/attachments' && request.method() === 'POST') uploads++; });
  await page.route('**/api/sessions/*/messages', (route) => {
    if (route.request().method() !== 'POST' || posts++ > 0) return route.continue();
    return route.fulfill({ status: 503, json: { error: { code: 'SEND_FAILED', message: 'Try again' } } });
  });
  await page.goto('/new');
  const picker = page.locator('.composer input[type=file]');
  await expect(picker).toBeEnabled();
  await picker.setInputFiles(image);
  await expect(page.locator('.upload-ready')).toHaveCount(1);
  await page.locator('.composer textarea').fill('Recover this image');
  const send = page.locator('.composer').getByRole('button', { name: 'Send', exact: true });
  await send.click();
  await expect(page.locator('.composer textarea')).toHaveValue('Recover this image');
  await expect(page.locator('.attachment-strip img')).toHaveJSProperty('naturalWidth', 1);
  await page.locator('.attachment-strip').getByRole('button', { name: 'Preview photo.png', exact: true }).click();
  await expect(page.getByRole('dialog').locator('img')).toHaveJSProperty('naturalWidth', 1);
  await page.keyboard.press('Escape');
  await send.click();
  await expect(page.locator('.message-row.user .message-attachments img')).toHaveJSProperty('naturalWidth', 1);
  await expect(page.locator('.attachment-strip')).toHaveCount(0);
  expect(uploads).toBe(1);
  expect(posts).toBe(2);
});
