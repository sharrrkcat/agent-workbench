import { expect, test, type Page } from '@playwright/test';

async function settled(page: Page) {
  await expect.poll(() => page.locator('.composer').evaluate((node) =>
    node.getAnimations({ subtree: true }).filter((animation) => animation.playState === 'running').length,
  )).toBe(0);
}

async function compact(page: Page, touch: boolean) {
  const composer = page.locator('.composer');
  await expect(composer).toHaveAttribute('data-expanded', 'false');
  await settled(page);
  const input = composer.locator('textarea');
  const text = await input.evaluate((node) => {
    const box = node.getBoundingClientRect(), style = getComputedStyle(node);
    return { x: box.x + parseFloat(style.paddingLeft), right: box.right - parseFloat(style.paddingRight),
      center: box.y + box.height / 2, lines: (node.clientHeight - parseFloat(style.paddingTop)
        - parseFloat(style.paddingBottom)) / parseFloat(style.lineHeight) };
  });
  expect(Math.abs(text.lines - 1)).toBeLessThan(0.06);
  const buttons = await composer.locator('[data-slot=input-group-addon] button').all();
  const plus = (await buttons[0].boundingBox())!, model = (await buttons[1].boundingBox())!, send = (await buttons[2].boundingBox())!;
  expect(text.x).toBeGreaterThan(plus.x + plus.width);
  expect(text.right).toBeLessThan(model.x);
  expect(model.x + model.width).toBeLessThan(send.x);
  for (const box of [plus, model, send]) {
    expect(Math.abs(box.y + box.height / 2 - text.center)).toBeLessThan(1);
    if (touch) { expect(box.width).toBeGreaterThanOrEqual(44); expect(box.height).toBeGreaterThanOrEqual(44); }
  }
}

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test.describe(`Composer ${locale} ${width}`, () => {
      const touch = width === 390;
      test.use({ viewport: { width, height: 900 }, hasTouch: touch });
      test.beforeEach(async ({ page, request }) => {
        await request.post('/__test__/session');
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        await page.goto('/');
      });

      test('single lines, wrapping, newlines and attachments preserve a stable input', async ({ page }, info) => {
        const composer = page.locator('.composer'), input = composer.locator('textarea');
        await compact(page, touch);
        const original = (await input.elementHandle())!;
        await input.focus();
        await compact(page, touch);
        await input.fill(locale === 'en' ? 'Hello' : '你好');
        await compact(page, touch);
        const limit = await input.evaluate((node) => {
          // Measure the whole string, including the variable font's pair kerning.
          const style = getComputedStyle(node), character = document.createElement('span');
          character.style.font = style.font;
          character.textContent = 'W';
          document.body.append(character);
          const available = node.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
          let limit = 0;
          while (character.getBoundingClientRect().width <= available) {
            limit++;
            character.textContent += 'W';
          }
          character.remove();
          return limit;
        });
        await input.fill('W'.repeat(limit));
        await compact(page, touch);
        await input.press('End');
        await input.pressSequentially('WW');
        await expect(composer).toHaveAttribute('data-expanded', 'true');
        await settled(page);
        const expanded = (await input.boundingBox())!;
        expect(expanded.height).toBeGreaterThanOrEqual(56);
        const button = (await composer.locator('[data-slot=dropdown-menu-trigger]').first().boundingBox())!;
        expect(expanded.y + expanded.height).toBeLessThanOrEqual(button.y);
        expect(await original.evaluate((node) => node === document.querySelector('.composer textarea'))).toBe(true);
        await expect(input).toBeFocused();
        await input.press('Backspace');
        await input.press('Backspace');
        await compact(page, touch);
        await input.fill('Short');
        await input.press('Shift+Enter');
        await expect(composer).toHaveAttribute('data-expanded', 'true');
        await expect(input).toHaveValue('Short\n');
        await input.fill('中文自动换行测试'.repeat(150));
        await expect(composer).toHaveAttribute('data-expanded', 'true');
        await settled(page);
        expect((await input.boundingBox())!.height).toBeLessThanOrEqual(192);
        expect(await input.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
        await input.fill('English wrapped text '.repeat(60));
        await expect(composer).toHaveAttribute('data-expanded', 'true');
        await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
        await page.evaluate(() => navigator.clipboard.writeText('First line\nSecond line\n'));
        await input.press('Control+A');
        await input.press('Control+V');
        await expect(input).toHaveValue('First line\nSecond line\n');
        await settled(page);
        await page.screenshot({ path: info.outputPath('expanded.png') });
        await input.clear();
        await compact(page, touch);
        await composer.locator('input[type=file]').setInputFiles({ name: 'layout.txt', mimeType: 'text/plain', buffer: Buffer.from('Attachment') });
        await expect(page.locator('.attachment-chip')).toContainText('layout.txt');
        await compact(page, touch);
        await input.click();
        await expect(input).toBeFocused();
        await page.screenshot({ path: info.outputPath('compact.png') });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      });

      test('transitions reverse cleanly; composition, send and reduced motion work', async ({ page }) => {
        const composer = page.locator('.composer'), input = composer.locator('textarea');
        await compact(page, touch);
        await composer.evaluate((node) => {
          (window as any).composerHeights = [];
          node.addEventListener('transitionrun', (event) => {
            if (event.target !== node || (event as TransitionEvent).propertyName !== 'height') return;
            const start = performance.now();
            function sample() {
              (window as any).composerHeights.push(node.getBoundingClientRect().height);
              if (performance.now() - start < 220) requestAnimationFrame(sample);
            }
            requestAnimationFrame(sample);
          });
        });
        await input.fill('Line one\nLine two');
        await expect(composer).toHaveAttribute('data-expanded', 'true');
        await settled(page);
        await input.fill('Short');
        await compact(page, touch);
        const heights = await page.evaluate(() => (window as any).composerHeights as number[]);
        expect(new Set(heights.map((height) => Math.round(height))).size).toBeGreaterThan(3);
        expect(heights.some((height, index) => index > 0 && height > heights[index - 1])).toBe(true);
        expect(heights.some((height, index) => index > 0 && height < heights[index - 1])).toBe(true);
        await input.fill('First\nSecond');
        await input.fill('Short');
        await input.fill('First\nSecond\nThird');
        await expect(composer).toHaveAttribute('data-expanded', 'true');
        await settled(page);
        await input.fill('你好');
        await input.dispatchEvent('compositionstart');
        await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true });
        await input.dispatchEvent('compositionend', { data: '你好' });
        await expect(input).toHaveValue('你好');
        await expect(page.locator('.message-row.user')).toHaveCount(0);
        await input.press('Enter');
        await expect(input).toHaveValue('');
        await expect(page.locator('.message-row.user')).toHaveCount(1);
        await compact(page, touch);
        await expect(page.locator('.status-done')).toBeVisible();
        await page.emulateMedia({ reducedMotion: 'reduce' });
        await input.fill('First\nSecond');
        await expect(composer).toHaveAttribute('data-expanded', 'true');
        await expect(composer).toHaveCSS('transition-property', 'none');
        await expect(input).toHaveCSS('transition-property', 'none');
        expect(await composer.evaluate((node) => node.getAnimations().length)).toBe(0);
        expect(await input.evaluate((node) => node.getAnimations().length)).toBe(0);
        await input.clear();
        await compact(page, touch);
      });
    });
  }
}

test('available width and short viewports recalculate layout without losing the draft', async ({ page, request }) => {
  await request.post('/__test__/session');
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto('/');
  const composer = page.locator('.composer'), input = composer.locator('textarea');
  const draft = 'A line that fits on desktop but wraps in a narrow viewport.';
  await input.fill(draft);
  await compact(page, false);
  await composer.locator('[data-slot=dropdown-menu-trigger]').first().click();
  await expect(page.getByRole('menu')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 600 });
  await expect(composer).toHaveAttribute('data-expanded', 'true');
  await expect(page.getByRole('menu')).toBeVisible();
  await page.keyboard.press('Escape');
  await input.fill('Long line\n'.repeat(35));
  await settled(page);
  expect((await input.boundingBox())!.height).toBeLessThanOrEqual(180);
  await input.fill(draft);
  await page.setViewportSize({ width: 1366, height: 900 });
  await compact(page, false);
  await expect(input).toHaveValue(draft);
});
