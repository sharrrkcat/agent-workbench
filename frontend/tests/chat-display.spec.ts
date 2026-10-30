import { readMessages, mockHistory } from './history';
import { expect, test, type Page } from '@playwright/test';

const reasoningTrigger = '[data-reasoning-id] [data-slot=trace-collapsible-trigger]';
const reasoningContent = '[data-reasoning-id] [data-slot=trace-collapsible-content]';
const toolTrigger = '[data-slot=trace-collapsible-trigger]';

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test.describe(`chat display ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('reasoning shows measured time, preserves expansion and reloads its duration', async ({ page, request }, info) => {
        const session = await (await request.post('/__test__/session', { data: { show_full_processing: true } })).json();
        await page.goto('/');
        const input = page.locator('.composer textarea');
        await input.fill('reasoning-live');
        await input.press('Enter');
        const toggle = page.locator(reasoningTrigger);
        await expect(toggle).toHaveText(locale === 'en' ? 'Thinking…' : '正在思考…');
        await expect(toggle).toHaveAttribute('aria-expanded', 'false');
        await expect(page.locator(reasoningContent)).toHaveCount(0);
        await toggle.click();
        await expect(page.locator(reasoningContent)).toContainText('Latest reasoning 2.');
        await expect(toggle).toHaveAttribute('aria-expanded', 'true');
        await expect(page.locator(reasoningContent)).toContainText('Latest reasoning 4.');
        await expect(toggle).toHaveAttribute('aria-expanded', 'true');
        await page.screenshot({ path: info.outputPath('reasoning-live.png') });
        await expect(page.locator('.reply-answer')).toContainText('Reasoning finished.');
        await expect(toggle).toHaveText(locale === 'en' ? /^Thought for \d+s$/ : /^思考了 \d+ 秒$/);
        const timedLabel = await toggle.innerText();
        await expect(toggle).toHaveAttribute('aria-expanded', 'false');
        await toggle.click();
        await expect(page.locator('.reply-answer')).toContainText('Final answer.');
        await expect(toggle).toHaveAttribute('aria-expanded', 'true');
        await expect(page.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        const history = await readMessages(request, session.session_id);
        const part = history.flatMap((message) => message.parts).find((part) => part.type === 'reasoning');
        expect(part.duration_ms).toBeGreaterThan(5000);
        await page.reload();
        await page.locator('.processing-toggle').click();
        await expect(toggle).toHaveText(timedLabel);
        await expect(toggle).toHaveAttribute('aria-expanded', 'false');
        await toggle.click();
        await expect(page.locator(reasoningContent)).toContainText('Latest reasoning 7.');
        await noOverflow(page);
        await page.screenshot({ path: info.outputPath('reasoning-completed.png') });
      });

      test('unknown and zero durations stay expandable and render full Markdown', async ({ page, request }, info) => {
        const session = await (await request.post('/__test__/session', { data: { long_history: true } })).json();
        const history = await readMessages(request, session.session_id);
        const message = history.find((item) => item.parts.some((part) => part.type === 'reasoning'));
        const original = message.parts.find((part) => part.type === 'reasoning');
        message.parts = [
          { ...original, text: 'A **formatted** thought with [a link](https://example.com) and `code`.\n\nNext line.\n\n```js\nconst ready = true;\n```' },
          { id: 'zero-duration', type: 'reasoning', text: 'Zero-duration thought.', duration_ms: 0 },
          { id: 'rounded-duration', type: 'reasoning', text: 'Another thought.', duration_ms: 2001 },
          ...message.parts.filter((part) => part.type !== 'reasoning'),
        ];
        await mockHistory(page, request, session.session_id, history);
        await page.goto('/');
        await page.locator('.processing-toggle').click();
        const toggles = page.locator(reasoningTrigger);
        await expect(toggles).toHaveText(locale === 'en'
          ? ['Thought', 'Thought for 0s', 'Thought for 3s']
          : ['已思考', '思考了 0 秒', '思考了 3 秒']);
        await toggles.first().focus();
        await page.keyboard.press('Enter');
        const content = page.locator(reasoningContent);
        await expect(content.locator('strong')).toHaveText('formatted');
        await expect(content.locator('a')).toHaveText('a link');
        await expect(content.locator('p code')).toHaveText('code');
        await expect(content).toContainText('Next line.');
        await expect(toggles.first()).toHaveCSS('font-size', '14px');
        await expect(content.locator('.part-markdown')).toHaveCSS('font-size', '14px');
        await expect(content.locator('[data-slot=trace-collapsible-content-inner]')).toHaveCSS('border-left-width', '1px');
        await expect(content.locator('[data-slot=code-block]')).toHaveAttribute('data-size', 'sm');
        await expect(content.locator('[data-slot=code-block-content]')).toHaveCSS('font-size', '14px');
        await expect(toggles.first().locator(':scope > [data-slot=trace-icon]')).toHaveCSS('rotate', '90deg');
        await expect(content).toHaveCSS('transition-duration', '0.2s');
        await page.screenshot({ path: info.outputPath('reasoning-markdown.png') });
        await page.keyboard.press('Enter');
        await expect(content).toHaveCount(0);
        await toggles.nth(1).click();
        await expect(page.locator(reasoningContent)).toHaveText('Zero-duration thought.');
        await noOverflow(page);
      });

      test('tools show arguments in their titles and expand directly to shadcn results', async ({ page, request }, info) => {
        const session = await (await request.post('/__test__/session', { data: { long_history: true } })).json();
        const history = await readMessages(request, session.session_id);
        const calls = history.flatMap((item) => item.parts).filter((part) => part.type === 'tool_call');
        const longValue = 'ABC ' + 'long request/'.repeat(100) + ' END';
        calls[0].arguments = { value: longValue };
        calls[1].arguments = { path: 'data/knowledge/note.txt', max_bytes: 2000 };
        await mockHistory(page, request, session.session_id, history);
        await page.goto('/');
        const clock = page.locator('.processing-toggle');
        await clock.click();
        const tools = page.locator('[data-tool-call-id]');
        await expect(tools).toHaveCount(12);
        await expect(page.locator('.tool-group, .processing-timeline, .reasoning-preview')).toHaveCount(0);
        const first = tools.first();
        const title = first.locator('[data-slot=trace-title]');
        await expect(title).toHaveText(`${locale === 'en' ? 'Ran' : '已运行'} test_other ${longValue}`);
        expect(await title.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);
        await expect(title).toHaveCSS('text-overflow', 'ellipsis');
        await expect(tools.nth(1).locator('[data-slot=trace-title]')).toContainText('path=data/knowledge/note.txt max_bytes=2000');
        await expect(first.getByRole('button')).toHaveCount(1);
        await expect(first.locator(toolTrigger)).toHaveAttribute('aria-expanded', 'false');
        await first.locator(toolTrigger).click();
        const result = first.locator('[data-slot=trace-collapsible-content]');
        await expect(result.locator('pre')).toHaveCount(1);
        await expect(result).toContainText('large-result:');
        await expect(result).not.toContainText(longValue);
        await expect(page.locator('button button')).toHaveCount(0);

        const body = (await page.locator('.reply-answer').boundingBox())!;
        const composer = (await page.locator('.composer').boundingBox())!;
        expect(Math.abs(body.x - composer.x)).toBeLessThan(1);
        expect(Math.abs(body.width - composer.width)).toBeLessThan(1);
        expect(Math.abs((await clock.boundingBox())!.x - body.x)).toBeLessThan(1);
        const reasoningX = (await page.locator('[data-reasoning-id]').boundingBox())!.x;
        expect(Math.abs(reasoningX - body.x)).toBeLessThan(1);
        await expect(page.locator('.processing-toggle [data-slot=trace-title]')).toHaveCSS('font-size', '14px');
        await expect(title).toHaveCSS('font-size', '14px');
        await expect(page.locator('[id^=processing-] > [data-slot=trace-collapsible-content-inner]')).toHaveCSS('border-left-width', '0px');
        for (const block of await tools.all()) {
          expect(Math.abs((await block.boundingBox())!.x - reasoningX)).toBeLessThan(1);
        }
        await expect(result.locator('[data-slot=trace-collapsible-content-inner]')).toHaveCSS('border-left-width', '1px');
        await expect(result.locator('[data-slot=code-block]')).toHaveAttribute('data-size', 'sm');
        await expect(result.locator('[data-slot=code-block-content]')).toHaveCSS('font-size', '14px');
        await expect(clock).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
        await expect(clock.locator(':scope > [data-slot=trace-icon]')).toHaveCSS('rotate', '90deg');
        await noOverflow(page);
        await page.screenshot({ path: info.outputPath('flat-tools.png') });
      });

      test('reduced motion keeps disclosures usable without shimmer or transitions', async ({ page, request }) => {
        await page.emulateMedia({ reducedMotion: 'reduce' });
        await request.post('/__test__/session', { data: { show_full_processing: true } });
        await page.goto('/');
        await page.locator('.composer textarea').fill('reasoning-cancel');
        await page.locator('.composer textarea').press('Enter');
        await expect(page.locator(reasoningTrigger)).toHaveText(locale === 'en' ? 'Thinking…' : '正在思考…');
        for (const title of await page.locator('[data-status=running] > [data-slot=trace-title]').all()) {
          await expect(title).toHaveCSS('animation-name', 'none');
          await expect(title).toHaveCSS('background-image', 'none');
        }
        await page.locator(reasoningTrigger).click();
        await expect(page.locator(reasoningContent)).toHaveCSS('transition-property', 'none');
        await expect(page.locator(reasoningContent)).toContainText('Reasoning beginning.');
        await page.locator('.composer').getByRole('button', { name: locale === 'en' ? 'Cancel' : '取消', exact: true }).click();
        await expect(page.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
      });
    });
  }
}

test('cancelled reasoning retains its content and measured duration after reload', async ({ page, request }) => {
  const session = await (await request.post('/__test__/session', { data: { show_full_processing: true } })).json();
  await page.goto('/');
  await page.locator('.composer textarea').fill('reasoning-cancel');
  await page.locator('.composer textarea').press('Enter');
  await page.locator(reasoningTrigger).click();
  await expect(page.locator(reasoningContent)).toContainText('Latest reasoning 2.');
  await page.locator('.composer').getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
  const part = (await readMessages(request, session.session_id)).flatMap((message) => message.parts).find((part) => part.type === 'reasoning');
  expect(part.duration_ms).toBeGreaterThan(1500);
  await page.reload();
  await page.locator('.processing-toggle').click();
  await expect(page.locator(reasoningTrigger)).toHaveText(`Thought for ${Math.ceil(part.duration_ms / 1000)}s`);
  await page.locator(reasoningTrigger).click();
  await expect(page.locator(reasoningContent)).toContainText('Latest reasoning 2.');
});

test('identity rows respond to available chat width when toggling the sidebar', async ({ page, request }) => {
  await request.post('/__test__/session', { data: { long_history: true } });
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto('/');
  const avatar = page.locator('.message-row.assistant .message-avatar');
  async function expectAlignedAvatars() {
    for (const row of await page.locator('.message-row').all()) {
      const avatarBox = (await row.locator('.message-avatar').boundingBox())!;
      const headerBox = (await row.locator('.message-meta').boundingBox())!;
      expect(avatarBox.width).toBe(48);
      expect(avatarBox.height).toBe(48);
      expect(Math.abs(avatarBox.y - headerBox.y)).toBeLessThan(1);
    }
  }
  await expect(avatar).toHaveCSS('position', 'static');
  await expectAlignedAvatars();
  const sidebar = page.locator('[data-sidebar=trigger]');
  await sidebar.click();
  await expect(avatar).toHaveCSS('position', 'absolute');
  await expectAlignedAvatars();
  await sidebar.click();
  await expect(avatar).toHaveCSS('position', 'static');
  for (const width of [1024, 1036, 1050, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(async () => {
      const composer = (await page.locator('.composer').boundingBox())!;
      const body = (await page.locator('.reply-answer').boundingBox())!;
      return Math.max(Math.abs(composer.x - body.x), Math.abs(composer.width - body.width));
    }).toBeLessThan(1);
    await expectAlignedAvatars();
    await noOverflow(page);
  }
});
