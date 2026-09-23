import { readFileSync } from 'node:fs';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { answerConfirmation, openSidebar } from './controls';

const words = (locale: string) =>
  JSON.parse(
    readFileSync(new URL('../src/i18n/resources/' + locale + '/personas.json', import.meta.url), 'utf8'),
  );

async function fixture(request: APIRequestContext, longHistory = true) {
  const response = await request.post('/__test__/session', { data: { long_history: longHistory } });
  expect(response.ok()).toBe(true);
  return response.json();
}

async function noPageOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() => ({
        horizontal: document.documentElement.scrollWidth - innerWidth,
        vertical: document.documentElement.scrollHeight - innerHeight,
      })),
    )
    .toEqual({ horizontal: 0, vertical: 0 });
}

async function atLatest(page: Page) {
  await expect
    .poll(() =>
      page.locator('.chat-view').evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight),
    )
    .toBeLessThanOrEqual(32);
}

async function expandInPlace(trigger: Locator) {
  await trigger.scrollIntoViewIfNeeded();
  const before = (await trigger.boundingBox())!.y;
  await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await expect.poll(async () => Math.abs((await trigger.boundingBox())!.y - before)).toBeLessThanOrEqual(2);
}

for (const locale of ['en', 'zh-CN']) {
  const labels = words(locale);
  for (const viewport of [
    { width: 1366, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test.describe('Mira layout ' + locale + ' ' + viewport.width, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('agent-workbench.locale', value), locale);
      });

      test('fixed sidebar regions, title menus, deletion and responsive navigation', async ({
        page,
        request,
      }, info) => {
        const prefix = 'History ' + locale + ' ' + viewport.width + ' ';
        await Promise.all(
          Array.from({ length: 48 }, async (_, index) => {
            const response = await request.post('/api/sessions', { data: { title: prefix + index } });
            expect(response.ok()).toBe(true);
          }),
        );
        const session = await fixture(request);
        const title =
          (locale === 'en'
            ? 'A longer conversation title for the navigation layout. '
            : '用于验证侧栏单行标题与截断的较长对话名称。'
          )
            .repeat(4)
            .slice(0, 110)
            .trim() +
          ' ' +
          session.session_id.slice(0, 8);
        await request.patch('/api/sessions/' + session.session_id, { data: { title } });
        await page.goto('/');
        await expect(page.locator('.chat-title')).toHaveText(title);
        await expect(page.locator('.reply-answer')).toContainText('All 12 commands completed.');
        await openSidebar(page);
        const sidebar = page.locator('.session-sidebar');
        const list = sidebar.locator('.session-list');
        expect((await sidebar.boundingBox())!.width).toBeCloseTo(viewport.width === 390 ? 288 : 256, 1);
        await expect(sidebar.getByRole('button', { name: labels.featureOne, exact: true })).toBeDisabled();
        await expect(sidebar.getByRole('button', { name: labels.featureTwo, exact: true })).toBeDisabled();
        const currentRow = sidebar.locator('.session-item.selected');
        const currentTitle = currentRow.locator('.session-select > span');
        await expect(currentTitle).toHaveCSS('white-space', 'nowrap');
        await expect(currentRow.locator('small')).toHaveCount(0);
        await expect(currentRow.locator('.session-select')).toHaveAttribute('title', title);
        expect(await currentTitle.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);
        const header = await sidebar.locator('.sidebar-header').boundingBox();
        const footer = await sidebar.locator('.sidebar-footer').boundingBox();
        expect(await list.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
        await list.evaluate((node) => {
          node.scrollTop = node.scrollHeight;
        });
        expect((await sidebar.locator('.sidebar-header').boundingBox())!.y).toBe(header!.y);
        expect((await sidebar.locator('.sidebar-footer').boundingBox())!.y).toBe(footer!.y);

        const row = sidebar
          .locator('.session-item')
          .filter({ has: page.getByRole('button', { name: prefix + '0', exact: true }) });
        await row.scrollIntoViewIfNeeded();
        const menu = row.locator('.session-menu');
        if (viewport.width === 390) {
          await expect(menu).toHaveCSS('opacity', '1');
          for (const button of await sidebar.locator('button').all()) {
            const box = await button.boundingBox();
            if (box) {
              expect(Math.round(box.height * 1000)).toBeGreaterThanOrEqual(44000);
              expect(Math.round(box.width * 1000)).toBeGreaterThanOrEqual(44000);
            }
          }
        } else {
          await expect(menu).toHaveCSS('opacity', '0');
          await row.hover();
          await expect(menu).toHaveCSS('opacity', '1');
          await page.mouse.move(viewport.width - 1, 1);
          await menu.focus();
          await expect(menu).toHaveCSS('opacity', '1');
        }
        await menu.click();
        await expect(page.getByRole('menu')).toBeVisible();
        await expect(page.locator('.chat-title')).toHaveText(title);
        await expect(sidebar).toBeInViewport();
        const remove = page.getByRole('menuitem', { name: labels.deleteSession, exact: true });
        if (viewport.width === 390)
          await expect
            .poll(async () => Math.round((await remove.boundingBox())!.height * 1000))
            .toBeGreaterThanOrEqual(44000);
        await remove.click();
        await answerConfirmation(page, false, locale);
        await expect(menu).toBeFocused();
        await menu.click();
        await page.getByRole('menuitem', { name: labels.deleteSession, exact: true }).click();
        await answerConfirmation(page, true, locale);
        await expect(row).toHaveCount(0);
        await expect(page.locator('.chat-title')).toHaveText(title);
        await expect(page.locator('.reply-answer')).toContainText('All 12 commands completed.');
        await list.evaluate((node) => {
          node.scrollTop = 0;
        });
        await page.screenshot({ path: info.outputPath('sidebar.png') });

        const trigger = page.locator('[data-sidebar="trigger"]');
        if (viewport.width === 390) {
          await page.keyboard.press('Escape');
          await expect(sidebar).toBeHidden();
          await expect(trigger).toBeFocused();
          await openSidebar(page);
          await page.locator('[data-slot="sheet-overlay"]').click({ position: { x: 380, y: 400 } });
          await expect(sidebar).toBeHidden();
          await expect(trigger).toBeFocused();
          await openSidebar(page);
          await sidebar
            .locator('.sidebar-header')
            .getByRole('button', { name: labels.newSession, exact: true })
            .click();
          await expect(sidebar).toBeHidden();
          await expect(page.locator('.chat-title')).toHaveText(labels.newSession);
          await expect(page.locator('.chat-empty')).toContainText(labels.startChat);
          await openSidebar(page);
          await sidebar.getByRole('button', { name: title, exact: true }).click();
          await expect(sidebar).toBeHidden();
          await expect(page.locator('.reply-answer')).toContainText('All 12 commands completed.');
          await openSidebar(page);
          await sidebar.getByRole('button', { name: labels.settings, exact: true }).click();
          await expect(page).toHaveURL(/\/settings$/);
          await expect(sidebar).toHaveCount(0);
          await page.setViewportSize({ width: viewport.width, height: 480 });
          await expect
            .poll(() => page.evaluate(() => document.documentElement.scrollHeight > innerHeight))
            .toBe(true);
          await page.mouse.move(200, 240);
          await page.mouse.wheel(0, 600);
          await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
        } else {
          await trigger.click();
          await expect(trigger).toHaveAttribute('aria-expanded', 'false');
          await expect(sidebar).toHaveAttribute('inert', '');
          await expect
            .poll(() => page.locator('.workspace').evaluate((node) => node.getBoundingClientRect().x))
            .toBe(0);
          await noPageOverflow(page);
          await page.reload();
          await expect(trigger).toHaveAttribute('aria-expanded', 'true');
          expect(await page.evaluate(() => document.cookie.includes('sidebar_state'))).toBe(false);
        }
      });

      test('Markdown stays within the reading column and the composer grows within its limit', async ({
        page,
        request,
      }, info) => {
        const session = await fixture(request);
        const history = await (await request.get('/api/sessions/' + session.session_id + '/messages')).json();
        const answer = history.filter((message: { role: string }) => message.role === 'assistant').at(-1);
        const columns = Array.from({ length: 14 }, (_, index) => 'Column ' + index);
        const markdown = [
          '# A readable answer',
          'Paragraph with **strong text**, *emphasis*, and a [link](https://example.com).',
          '## Next steps',
          '- First item\n- Second item\n  - Nested item',
          '1. First step\n2. Second step',
          '> A quoted observation.',
          'An inline \`value\` and a long code block:',
          '~~~text\n' + 'long_line_'.repeat(160) + '\n~~~',
          '| ' +
            columns.join(' | ') +
            ' |\n| ' +
            columns.map(() => '---').join(' | ') +
            ' |\n| ' +
            columns.join(' | ') +
            ' |',
          'Last paragraph.',
        ].join('\n\n');
        answer.parts = [{ id: 'layout-answer', type: 'text', format: 'markdown', text: markdown }];
        await page.route('**/api/sessions/' + session.session_id + '/messages', (route) =>
          route.fulfill({ json: history }),
        );
        await page.goto('/');
        const body = page.locator('.reply-answer');
        await expect(body.getByRole('heading', { name: 'A readable answer' })).toBeVisible();
        await expect(body).toHaveCSS('font-size', '16px');
        await expect(body.locator('ul').first()).toHaveCSS('list-style-type', 'disc');
        await expect(body.locator('ol')).toHaveCSS('list-style-type', 'decimal');
        const code = body.locator('pre');
        expect(await code.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);
        const table = body.locator('.markdown-table');
        expect(await table.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);
        expect((await page.locator('.conversation-content').boundingBox())!.width).toBeLessThanOrEqual(768);
        await noPageOverflow(page);
        const input = page.locator('.composer textarea');
        const initial = (await input.boundingBox())!.height;
        await input.fill(Array.from({ length: 35 }, (_, index) => 'Draft line ' + index).join('\n'));
        await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(initial);
        expect((await input.boundingBox())!.height).toBeLessThanOrEqual(192);
        expect(await input.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
        await input.press('Shift+Enter');
        await expect(page.locator('article[data-run-id]')).toHaveCount(1);
        await noPageOverflow(page);
        await input.clear();
        await expect.poll(async () => (await input.boundingBox())!.height).toBe(initial);
        await page.screenshot({ path: info.outputPath('chat-layout.png') });
      });

      test('disclosures preserve their position and session selection opens the latest content', async ({
        page,
        request,
      }) => {
        const previous = await fixture(request, false);
        const session = await fixture(request);
        const previousTitle = 'Other layout session ' + previous.session_id;
        const currentTitle = 'Current layout session ' + session.session_id;
        await request.patch('/api/sessions/' + previous.session_id, {
          data: { title: previousTitle },
        });
        await request.patch('/api/sessions/' + session.session_id, {
          data: { title: currentTitle },
        });
        await page.goto('/');
        await expect(page.locator('.reply-answer')).toContainText('All 12 commands completed.');
        await expandInPlace(page.locator('.processing-toggle'));
        await expandInPlace(page.locator('.tool-group-toggle'));
        await expandInPlace(page.locator('.tool-command-toggle').first());
        await noPageOverflow(page);
        await openSidebar(page);
        await page
          .locator('.session-sidebar')
          .getByRole('button', { name: previousTitle, exact: true })
          .click();
        await expect(page.locator('.chat-empty')).toBeVisible();
        await openSidebar(page);
        await page
          .locator('.session-sidebar')
          .getByRole('button', { name: currentTitle, exact: true })
          .click();
        await expect(page.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        await expect(page.locator('.reply-answer')).toContainText('All 12 commands completed.');
        await atLatest(page);
      });
    });
  }

  for (const viewport of [
    { width: 767, height: 720 },
    { width: 768, height: 720 },
    { width: 1024, height: 480 },
    { width: 390, height: 480 },
  ]) {
    test(
      'layout boundary ' + locale + ' ' + viewport.width + 'x' + viewport.height,
      async ({ page, request }) => {
        await page.setViewportSize(viewport);
        await page.addInitScript((value) => localStorage.setItem('agent-workbench.locale', value), locale);
        await fixture(request);
        await page.goto('/');
        await expect(page.locator('.reply-answer')).toContainText('All 12 commands completed.');
        const trigger = page.locator('[data-sidebar="trigger"]');
        await expect(trigger).toHaveAttribute('aria-expanded', viewport.width < 768 ? 'false' : 'true');
        await expect(page.locator('.composer textarea')).toBeInViewport();
        await expect(page.locator('.status-bar')).toBeInViewport();
        const title = (await page.locator('.chat-title').boundingBox())!;
        const model = (await page.locator('.chat-model-control').boundingBox())!;
        expect(model.y > title.y + title.height).toBe(viewport.width < 768);
        await noPageOverflow(page);
        await openSidebar(page);
        await expect(page.locator('.sidebar-footer')).toBeInViewport();
        await expect(page.locator('.sidebar-header')).toBeInViewport();
      },
    );
  }
}
