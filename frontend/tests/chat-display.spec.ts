import { expect, test, type Locator } from '@playwright/test';

async function previewEdges(preview: Locator) {
  return preview.evaluate((node) => {
    const outer = node.querySelector('.reasoning-window')!.getBoundingClientRect();
    const inner = node.querySelector('.reasoning-preview-text')!.getBoundingClientRect();
    return { left: inner.left - outer.left, right: inner.right - outer.right,
      height: outer.height, limit: parseFloat(getComputedStyle(node).lineHeight) };
  });
}

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test.describe(`chat display ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('reasoning follows the tail, preserves expansion and resets at completion', async ({ page, request }, info) => {
        await request.post('/__test__/session', { data: { show_full_processing: true } });
        await page.goto('/');
        await page.locator('.composer textarea').fill('reasoning-preview');
        await page.locator('.composer textarea').press('Enter');
        const preview = page.locator('.reasoning-preview');
        const toggle = page.locator('.reasoning-toggle');
        await expect(preview).toContainText('Latest reasoning 4.');
        await expect(toggle).toBeEnabled();
        await expect(preview.locator('.reasoning-ellipsis')).toHaveText('…');
        expect(await preview.locator('.reasoning-ellipsis').evaluate((node) => node === node.parentElement!.firstElementChild)).toBe(true);
        await expect(toggle).toHaveText('');
        await expect(page.locator('.reply-processing-header button')).toHaveCount(1);
        const iconBox = (await toggle.boundingBox())!;
        const previewBox = (await preview.boundingBox())!;
        expect(previewBox.x).toBeGreaterThanOrEqual(iconBox.x + iconBox.width);
        const lineHeight = await preview.evaluate((node) => parseFloat(getComputedStyle(node).lineHeight));
        expect(Math.abs(previewBox.y + lineHeight / 2 - iconBox.y - iconBox.height / 2)).toBeLessThan(1);
        await expect(preview).toHaveAttribute('data-streaming', 'true');
        const edges = await previewEdges(preview);
        expect(edges.height).toBeCloseTo(edges.limit, 0);
        expect(edges.left).toBeLessThan(-10);
        expect(Math.abs(edges.right)).toBeLessThan(1);
        await toggle.click();
        await expect(toggle).toHaveAttribute('aria-expanded', 'true');
        await expect(page.locator('.reasoning-content')).toContainText('Latest reasoning 5.');
        await expect(toggle).toHaveAttribute('aria-expanded', 'true');
        await expect(page.locator('.reply-answer')).toContainText('Reasoning finished.');
        await expect(toggle).toHaveAttribute('aria-expanded', 'false');
        await expect(preview).toHaveAttribute('data-streaming', 'false');
        await expect(preview.locator('.reasoning-preview-text')).toContainText('Preview beginning. Second line.');
        await expect(preview.locator('.reasoning-ellipsis')).toHaveText('…');
        expect(await preview.locator('.reasoning-ellipsis').evaluate((node) => node === node.parentElement!.lastElementChild)).toBe(true);
        expect(Math.abs((await previewEdges(preview)).left)).toBeLessThan(1);
        await expect(page.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        await page.locator('.processing-toggle').click();
        await toggle.click();
        await expect(page.locator('.reasoning-content')).toContainText('Latest reasoning 7.');
        await toggle.click();
        expect(Math.abs((await previewEdges(preview)).left)).toBeLessThan(1);
        await page.screenshot({ path: info.outputPath('reasoning-complete.png') });
        await page.reload();
        await page.locator('.processing-toggle').click();
        await expect(toggle).toHaveAttribute('aria-expanded', 'false');
        expect(Math.abs((await previewEdges(preview)).left)).toBeLessThan(1);
      });

      test('single-line previews handle long text and sidebar width changes', async ({ page, request }) => {
        const session = await (await request.post('/__test__/session', { data: { long_history: true } })).json();
        const history = await (await request.get(`/api/sessions/${session.session_id}/messages`)).json();
        const message = history.find((item: { parts: { type: string }[] }) => item.parts.some((part) => part.type === 'reasoning'));
        const part = message.parts.find((part: { type: string }) => part.type === 'reasoning');
        await page.route(`**/api/sessions/${session.session_id}/messages`, (route) => route.fulfill({ json: history }));
        for (const text of ['短思考', '开始思考，中英文 mixed text。'.repeat(30), 'Beginning' + 'x'.repeat(600) + 'End']) {
          part.text = text;
          await page.goto('/');
          await page.locator('.processing-toggle').click();
          const preview = page.locator('.reasoning-preview');
          await expect(preview.locator('.reasoning-preview-text')).toHaveText(text);
          await expect(preview.locator('.reasoning-ellipsis')).toHaveCount(text.length > 10 ? 1 : 0);
          const edges = await previewEdges(preview);
          expect(edges.height).toBeCloseTo(edges.limit, 0);
          expect(Math.abs(edges.left)).toBeLessThan(1);
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        }
        if (width === 1366) {
          // Choose a measured width between the open and closed sidebar sizes.
          await page.setViewportSize({ width: 900, height: 900 });
          const preview = page.locator('.reasoning-preview');
          const narrow = (await preview.boundingBox())!.width;
          await page.locator('[data-sidebar=trigger]').click();
          await expect.poll(async () => (await preview.boundingBox())!.width).toBeGreaterThan(narrow + 100);
          const wide = (await preview.boundingBox())!.width;
          const characterWidth = await preview.locator('.reasoning-preview-text').evaluate((node) => node.getBoundingClientRect().width / node.textContent!.length);
          part.text = 'x'.repeat(Math.floor((narrow + wide) / 2 / characterWidth));
          await page.reload();
          await page.locator('.processing-toggle').click();
          await expect(preview.locator('.reasoning-ellipsis')).toHaveCount(1);
          await page.locator('[data-sidebar=trigger]').click();
          await expect(preview.locator('.reasoning-ellipsis')).toHaveCount(0);
          await expect(page.locator('.reasoning-toggle')).toBeDisabled();
          await page.locator('[data-sidebar=trigger]').click();
          await expect(preview.locator('.reasoning-ellipsis')).toHaveCount(1);
        }
      });

      test('message bodies align with composer and disclosure arrows trail labels', async ({ page, request }, info) => {
        await request.post('/__test__/session', { data: { long_history: true } });
        await page.goto('/');
        await expect(page.locator('.reply-answer')).toBeVisible();
        const composer = (await page.locator('.composer').boundingBox())!;
        const answer = (await page.locator('.reply-answer').boundingBox())!;
        const user = (await page.locator('.message-row.user [data-slot=bubble]').boundingBox())!;
        expect(Math.abs(answer.x - composer.x)).toBeLessThan(1);
        expect(Math.abs(answer.x + answer.width - composer.x - composer.width)).toBeLessThan(1);
        expect(Math.abs(user.x + user.width - composer.x - composer.width)).toBeLessThan(1);
        for (const role of ['assistant', 'user']) {
          const row = page.locator(`.message-row.${role}`);
          const avatar = (await row.locator('.message-avatar').boundingBox())!;
          const name = (await row.locator('.message-meta strong').boundingBox())!;
          if (width === 390) {
            expect(avatar.y).toBeLessThan(name.y + name.height);
            expect(avatar.y + avatar.height).toBeGreaterThan(name.y);
            const body = (await row.locator(role === 'user' ? '[data-slot=bubble]' : '.reply-processing-header').boundingBox())!;
            expect(body.y).toBeGreaterThanOrEqual(avatar.y + avatar.height);
          } else if (role === 'assistant') {
            expect(avatar.x + avatar.width).toBeLessThan(composer.x);
          } else {
            expect(avatar.x).toBeGreaterThan(composer.x + composer.width);
          }
        }
        const clock = page.locator('.processing-toggle');
        const clockText = (await clock.locator('span').boundingBox())!;
        expect(Math.abs(clockText.x - answer.x)).toBeLessThan(1);
        await expect(clock.locator('.disclosure-arrow')).toHaveCSS('opacity', '1');
        await clock.click();
        const group = page.locator('.tool-group-toggle');
        await page.mouse.move(0, 0);
        await expect(group.locator('.disclosure-arrow')).toHaveCSS('opacity', width === 390 ? '1' : '0');
        await page.keyboard.press('Tab');
        await group.focus();
        await expect(group.locator('.disclosure-arrow')).toHaveCSS('opacity', '1');
        await group.click();
        const command = page.locator('.tool-command-toggle').first();
        for (const trigger of [clock, group, command]) {
          const label = (await trigger.locator('span').first().boundingBox())!;
          const arrow = (await trigger.locator('.disclosure-arrow').boundingBox())!;
          expect(arrow.x).toBeGreaterThanOrEqual(label.x + label.width);
        }
        await command.click();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: info.outputPath('aligned-messages.png') });
      });
    });
  }
}

test('cancelled reasoning returns to the beginning and remains expandable after reload', async ({ page, request }) => {
  await request.post('/__test__/session', { data: { show_full_processing: true } });
  await page.goto('/');
  await page.locator('.composer textarea').fill('reasoning-cancel');
  await page.locator('.composer textarea').press('Enter');
  await expect(page.locator('.reasoning-preview')).toContainText('Latest reasoning 4.');
  await page.locator('.reasoning-toggle').click();
  await page.locator('.composer').getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
  await page.reload();
  await page.locator('.processing-toggle').click();
  await expect(page.locator('.reasoning-toggle')).toBeEnabled();
  expect(Math.abs((await previewEdges(page.locator('.reasoning-preview'))).left)).toBeLessThan(1);
});

test('short reasoning becomes expandable after overflowing a narrower chat region', async ({ page, request }) => {
  const session = await (await request.post('/__test__/session', { data: { long_history: true } })).json();
  const history = await (await request.get(`/api/sessions/${session.session_id}/messages`)).json();
  const message = history.find((item: { parts: { type: string }[] }) => item.parts.some((part) => part.type === 'reasoning'));
  message.parts.find((part: { type: string }) => part.type === 'reasoning').text = 'A **formatted** reasoning preview with [a link](https://example.com) and `code`.\nNext line.';
  await page.route(`**/api/sessions/${session.session_id}/messages`, (route) => route.fulfill({ json: history }));
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto('/');
  await page.locator('.processing-toggle').click();
  await expect(page.locator('.reasoning-toggle')).toBeDisabled();
  await expect(page.locator('.reasoning-preview-text')).toHaveText('A formatted reasoning preview with a link and code. Next line.');
  await expect(page.locator('.reasoning-ellipsis')).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.reasoning-toggle')).toBeEnabled();
  await expect(page.locator('.reasoning-ellipsis')).toHaveText('…');
  await page.locator('.reasoning-toggle').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.reasoning-content strong')).toHaveText('formatted');
  await expect(page.locator('.reasoning-content a')).toHaveText('a link');
  await expect(page.locator('.reasoning-content code')).toHaveText('code');
  await page.keyboard.press('Enter');
  await page.setViewportSize({ width: 1366, height: 900 });
  await expect(page.locator('.reasoning-toggle')).toBeDisabled();
});

test('identity rows respond to available chat width when toggling the sidebar', async ({ page, request }) => {
  await request.post('/__test__/session', { data: { long_history: true } });
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto('/');
  const avatar = page.locator('.message-row.assistant .message-avatar');
  await expect(avatar).toHaveCSS('position', 'static');
  const sidebar = page.locator('[data-sidebar=trigger]');
  await sidebar.click();
  await expect(avatar).toHaveCSS('position', 'absolute');
  await sidebar.click();
  await expect(avatar).toHaveCSS('position', 'static');
  for (const width of [1024, 1036, 1050, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(async () => {
      const composer = (await page.locator('.composer').boundingBox())!;
      const body = (await page.locator('.reply-answer').boundingBox())!;
      return Math.max(Math.abs(composer.x - body.x), Math.abs(composer.width - body.width));
    }).toBeLessThan(1);
  }
});
