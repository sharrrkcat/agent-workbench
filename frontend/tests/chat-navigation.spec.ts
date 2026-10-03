import { readMessages, mockHistory } from './history';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { answerConfirmation } from './controls';

async function navigationHistory(page: Page, request: APIRequestContext, count: number) {
  const session = await (await request.post('/__test__/session', { data: { long_history: true } })).json();
  const history = await readMessages(request, session.session_id);
  const original = history.find((message: { role: string }) => message.role === 'user');
  const messages = Array.from({ length: count }, (_, index) => ({ ...original,
    message_id: `navigation-${index}`, created_at: new Date(Date.UTC(2026, 0, 1, 0, index)).toISOString(),
    parts: [{ id: `text-${index}`, type: 'text', text: `Question ${index + 1}` }],
  }));
  await mockHistory(page, request, session.session_id, messages, []);
}

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test(`message navigation and composer ${locale} ${width}`, async ({ page, request }, info) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      await navigationHistory(page, request, 5);
      await page.goto('/');
      const input = page.locator('.composer textarea');
      await expect(input).toBeVisible();
      await expect(page.locator('.composer')).toHaveAttribute('data-expanded', 'false');
      await expect(page.locator('.composer')).toHaveCSS('border-radius', '20px');
      const toolbarButtons = page.locator('.composer [data-slot=input-group-addon] button');
      await expect(toolbarButtons).toHaveCount(4);
      for (const button of await toolbarButtons.all()) {
        const radius = await button.evaluate((node) => parseFloat(getComputedStyle(node).borderTopLeftRadius));
        expect(radius).toBeGreaterThanOrEqual((await button.boundingBox())!.height / 2);
      }
      const bubbles = page.locator('.message-row.user [data-slot=bubble-content]');
      await expect(bubbles.first()).toHaveCSS('border-radius', '24px');
      await expect(page.locator('.user-message-enter')).toHaveCount(0);
      const rail = page.locator('.user-message-navigation');
      if (width === 390) await expect(rail).toBeHidden();
      else {
        await expect(rail).toBeVisible();
        await expect(rail.getByRole('button')).toHaveCount(await bubbles.count());
        await expect(rail.getByRole('button').first()).toHaveCSS('height', '8px');
        await rail.getByRole('button').first().focus();
        await expect(page.locator('[data-slot=tooltip-content]')).toBeVisible();
        await rail.getByRole('button').first().press('Enter');
        await expect(rail.locator('[aria-current=step]')).toHaveCount(1);
        await expect(page.locator('.message-row.user').first()).toBeInViewport();
        await rail.getByRole('button').nth(2).click();
        await expect(rail.getByRole('button').nth(2)).toHaveAttribute('aria-current', 'step');
        const marks = await rail.locator('button > span').evaluateAll((nodes) => nodes.map((node) => {
          const box = node.getBoundingClientRect();
          return { x: box.x, y: box.y, width: box.width, height: box.height, color: getComputedStyle(node).backgroundColor };
        }));
        expect(marks.map((mark) => mark.width)).toEqual([12, 18, 24, 18, 12]);
        expect(new Set(marks.map((mark) => mark.x)).size).toBe(1);
        expect(marks.every((mark) => mark.height === 2)).toBe(true);
        expect(marks.slice(1).every((mark, index) => mark.y - marks[index].y === 8)).toBe(true);
        expect(marks[1].color).toBe(marks[0].color);
        expect(marks[3].color).toBe(marks[0].color);
        expect(marks[2].color).not.toBe(marks[0].color);
      }
      const plus = page.locator('.composer [data-slot=dropdown-menu-trigger]').first();
      await plus.focus();
      await plus.press('Enter');
      const menuItem = page.getByRole('menuitem', { name: locale === 'en' ? 'Add Photos & Files' : '添加照片与文件' });
      await expect(menuItem).toBeVisible();
      await expect(page.getByRole('menuitem')).toHaveCount(1);
      const chooser = page.waitForEvent('filechooser');
      await menuItem.click();
      await (await chooser).setFiles({ name: 'navigation.txt', mimeType: 'text/plain', buffer: Buffer.from('Attachment') });
      await expect(page.locator('.attachment-chip')).toContainText('navigation.txt');
      await page.screenshot({ path: info.outputPath('composer-navigation.png') });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }
}

test('first send animates once and historical reload does not; reduced motion disables animation', async ({ page, request }) => {
  await request.post('/__test__/session', { data: {} });
  await page.addInitScript(() => {
    (window as any).bubbleAnimations = [];
    document.addEventListener('animationstart', (event) => {
      if (event.animationName === 'user-message-blur-fade') (window as any).bubbleAnimations.push(event.animationName);
    });
  });
  await page.goto('/new');
  await expect(page.locator('.user-message-navigation')).toHaveCount(0);
  await page.locator('.composer textarea').fill('A new draft message');
  await page.locator('.composer textarea').press('Enter');
  await expect(page.locator('.message-row.user')).toHaveCount(1);
  await expect(page.locator('.user-message-navigation')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => (window as any).bubbleAnimations.length)).toBe(1);
  await expect(page.locator('.status-done')).toBeVisible();
  expect(await page.evaluate(() => (window as any).bubbleAnimations.length)).toBe(1);
  const user = page.locator('.message-row.user');
  await user.hover();
  await user.getByRole('button', { name: 'Edit message', exact: true }).click();
  await expect(user.locator('textarea')).toBeVisible();
  await user.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(await page.evaluate(() => (window as any).bubbleAnimations.length)).toBe(1);
  await page.reload();
  await expect(page.locator('.message-row.user')).toHaveCount(1);
  await expect(page.locator('.user-message-enter')).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.locator('.composer textarea').fill('Reduced motion message');
  await page.locator('.composer textarea').press('Enter');
  await expect(page.locator('.user-message-enter')).toHaveCSS('animation-name', 'none');
  await expect(page.locator('.status-done')).toHaveCount(2);
  await expect(page.locator('.user-message-navigation button')).toHaveCount(2);
});

test('navigation keeps earlier turns stable while streaming and removes deleted inputs', async ({ page, request }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await request.post('/__test__/session', { data: { long_history: true } });
  await page.goto('/');
  await page.locator('.composer textarea').fill('scroll-output');
  await page.locator('.composer textarea').press('Enter');
  const answer = page.locator('.reply-answer').last();
  await expect(answer).toContainText('Paragraph 18:');
  const ticks = page.locator('.user-message-navigation button');
  await expect(ticks).toHaveCount(2);
  await ticks.first().click();
  await expect(ticks.first()).toHaveAttribute('aria-current', 'step');
  const view = page.locator('.chat-view');
  await expect.poll(() => view.evaluate((node) => node.scrollTop)).toBe(0);
  const top = await view.evaluate((node) => node.scrollTop);
  await expect(answer).toContainText('Paragraph 28:');
  expect(Math.abs(await view.evaluate((node) => node.scrollTop) - top)).toBeLessThan(1);
  await page.locator('.latest-message-button').click();
  await expect(page.locator('.status-done')).toHaveCount(2);
  await ticks.last().click();
  const lastUser = page.locator('.message-row.user').last();
  await lastUser.hover();
  await lastUser.getByRole('button', { name: 'Delete message', exact: true }).click();
  await answerConfirmation(page, true);
  await expect(page.locator('.message-row.user')).toHaveCount(1);
  await expect(page.locator('.user-message-navigation')).toHaveCount(0);
});

test('long navigation scrolls internally and highlights the visible turn', async ({ page, request }, info) => {
  await page.setViewportSize({ width: 1366, height: 450 });
  await navigationHistory(page, request, 150);
  await page.goto('/');
  const rail = page.locator('.user-message-navigation');
  await expect(rail.locator('.user-message-tick')).toHaveCount(50);
  await expect.poll(() => rail.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
  await page.locator('.chat-view').evaluate((node) => { node.scrollTop = node.scrollHeight; });
  await expect(rail.locator('[aria-current=step]')).toHaveCount(1);
  await expect(rail.locator('[aria-current=step]')).toBeInViewport();
  await expect.poll(() => rail.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
  await page.locator('.chat-view').evaluate((node) => { node.scrollTop = 0; });
  await expect(rail.locator('.user-message-tick').first()).toHaveAttribute('aria-current', 'step');
  await expect(rail.locator('.user-message-tick').first()).toBeInViewport();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({ path: info.outputPath('long-navigation.png') });
});
