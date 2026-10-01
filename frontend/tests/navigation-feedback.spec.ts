import { readFileSync } from 'node:fs';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { navigateModelSettings, openSidebar } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
const status = '[data-slot="loading-status"]';

async function holdResponse(page: Page, url: string, fail = false) {
  let release!: () => void, started!: () => void;
  const completed: Array<Promise<void>> = [];
  let released = false;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const requested = new Promise<void>((resolve) => { started = resolve; });
  await page.route(url, async (route) => {
    if (released) return route.continue();
    const response = await route.fetch();
    const completion = held.then(() => route.fulfill(fail ? { status: 503, json: { error: { code: 'TEST_FAILURE', message: 'Retry loading' } } } : { response }));
    completed.push(completion);
    started();
    await completion;
  });
  return { requested, release: async () => { released = true; release(); await Promise.all(completed); } };
}

async function workspace(request: APIRequestContext) {
  const agents = await (await request.get('/api/personas?collection=agent')).json();
  const users = await (await request.get('/api/personas?collection=user')).json();
  const response = await request.post('/api/projects', { data: {
    kind: 'workspace', name: 'Navigation project', agent_persona_id: agents[0].id, cogita_persona_id: users[0].id,
    context_policy: { mode: 'session' }, harness_enabled: false, tools_allowed: [],
  } });
  expect(response.ok()).toBe(true);
  const project = await response.json();
  for (const title of ['First session with a long title that must leave space for its menu', 'Second session', 'Third session']) {
    const created = await request.post(`/api/projects/${project.id}/sessions`, { data: { title } });
    expect(created.ok()).toBe(true);
  }
  return project.id as string;
}

async function pauseClock(page: Page) {
  const time = new Date();
  await page.clock.install({ time });
  await page.clock.pauseAt(time);
}

for (const locale of ['en', 'zh-CN']) {
  const common = words(locale, 'common'), labels = words(locale, 'personas');
  const settings = words(locale, 'settings'), llm = words(locale, 'llm');
  for (const width of [1366, 390]) {
    test.describe(`Navigation feedback ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page, request }) => {
        await request.post('/__test__/session');
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('Project loading, isolated row interactions and aligned actions', async ({ page, request }, info) => {
        const id = await workspace(request);
        const pending: Array<{ release: () => Promise<void> }> = [];
        try {
          await page.goto('/');
          await expect(page.locator('.composer textarea')).toBeVisible();
          await openSidebar(page);
          await pauseClock(page);
          const project = page.locator(`[data-project-id="${id}"]`);
          const heading = project.locator('.project-select');
          const rows = project.locator('.session-item');
          const initial = await holdResponse(page, `**/api/projects/${id}/sessions`);
          pending.push(initial);
          await heading.click();
          await initial.requested;
          await expect(project.getByText(labels.noProjectSessions, { exact: true })).toHaveCount(0);
          await page.clock.runFor(199);
          await expect(project.locator(status)).toHaveCount(0);
          await page.clock.runFor(1);
          await expect(project.locator(status)).toHaveText(common.loading);
          await expect(project.locator(status)).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
          expect((await project.locator(status).boundingBox())!.height).toBeLessThanOrEqual(28);
          await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0);
          await heading.click();
          await expect(project.locator(status)).toHaveCount(0);
          await initial.release();
          await page.clock.runFor(300);
          await expect(project.locator(status)).toHaveCount(0);
          await heading.click();
          await expect(rows).toHaveCount(3);
          await expect(project.locator(status)).toHaveCount(0);
          await page.clock.resume();

          const projectMenu = project.getByRole('button', { name: labels.projectActions.replace('{{name}}', 'Navigation project'), exact: true });
          const create = project.getByRole('button', { name: labels.newProjectSession.replace('{{name}}', 'Navigation project'), exact: true });
          const menus = rows.locator('.session-menu');
          if (width === 1366) {
            await page.mouse.move(600, 400);
            await expect(create).toHaveCSS('opacity', '0');
            for (const menu of await menus.all()) await expect(menu).toHaveCSS('opacity', '0');
            await heading.hover();
            await expect(create).toHaveCSS('opacity', '1');
            for (const menu of await menus.all()) await expect(menu).toHaveCSS('opacity', '0');
            for (let index = 0; index < 3; index++) {
              await rows.nth(index).locator('.session-select').hover();
              await expect(create).toHaveCSS('opacity', '0');
              await expect(heading).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
              for (let other = 0; other < 3; other++) {
                await expect(menus.nth(other)).toHaveCSS('opacity', index === other ? '1' : '0');
                await expect(rows.nth(other).locator('.session-select')).toHaveCSS('background-color', index === other ? 'oklch(0.269 0 0)' : 'rgba(0, 0, 0, 0)');
              }
            }
            await page.mouse.move(600, 400);
            await rows.first().locator('.session-select').focus();
            await page.keyboard.press('Tab');
            await expect(menus.first()).toBeFocused();
            await expect(menus.first()).toHaveCSS('opacity', '1');
            await expect(menus.nth(1)).toHaveCSS('opacity', '0');
            await page.keyboard.press('Enter');
          } else {
            for (const button of await project.locator('button').all()) {
              const box = (await button.boundingBox())!;
              expect(box.height).toBeGreaterThanOrEqual(44);
              expect(box.width).toBeGreaterThanOrEqual(44);
            }
            for (const menu of await menus.all()) await expect(menu).toHaveCSS('opacity', '1');
            await menus.first().click();
          }
          await expect(page.getByRole('menu')).toBeVisible();
          await expect(menus.first()).toHaveCSS('opacity', '1');
          await page.keyboard.press('Escape');
          await expect(menus.first()).toBeFocused();
          const parentBox = (await projectMenu.boundingBox())!;
          for (const row of await rows.all()) {
            const menu = (await row.locator('.session-menu').boundingBox())!;
            expect(Math.abs(menu.x + menu.width / 2 - parentBox.x - parentBox.width / 2)).toBeLessThanOrEqual(1);
            const title = (await row.locator('.session-select > span').boundingBox())!;
            expect(title.x + title.width).toBeLessThanOrEqual(menu.x);
          }
          expect(await project.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);

          await heading.click();
          const refresh = await holdResponse(page, `**/api/projects/${id}/sessions`, true);
          pending.push(refresh);
          await heading.click();
          await refresh.requested;
          if (width === 1366) {
            await page.mouse.move(600, 400);
            await expect(create).toHaveCSS('opacity', '0');
            for (const menu of await menus.all()) await expect(menu).toHaveCSS('opacity', '0');
          }
          await page.clock.runFor(300);
          await expect(rows).toHaveCount(3);
          await expect(project.locator(status)).toHaveCount(0);
          await refresh.release();
          await expect(project.getByRole('alert')).toContainText('Retry loading');
          const retry = await holdResponse(page, `**/api/projects/${id}/sessions`);
          pending.push(retry);
          await project.getByRole('button', { name: settings.resources.refresh, exact: true }).click();
          await retry.requested;
          await expect(project.getByRole('alert')).toHaveCount(0);
          await retry.release();
          await expect(rows).toHaveCount(3);
          await page.screenshot({ path: info.outputPath('project-navigation.png') });
        } finally {
          for (const held of pending) await held.release();
          await request.delete(`/api/projects/${id}`);
        }
      });

      test('session transitions reset delayed feedback and ignore late responses', async ({ page, request }) => {
        const id = await workspace(request);
        const sessions = await (await request.get(`/api/projects/${id}/sessions`)).json();
        const pending: Array<{ release: () => Promise<void> }> = [];
        try {
          await page.goto('/');
          await expect(page.locator('.composer textarea')).toBeVisible();
          await openSidebar(page);
          const project = page.locator(`[data-project-id="${id}"]`);
          await project.locator('.project-select').click();
          await expect(project.locator('.session-item')).toHaveCount(3);
          const header = await page.locator('.topbar').elementHandle();
          const composer = await page.locator('.composer textarea').elementHandle();
          await pauseClock(page);
          const first = await holdResponse(page, `**/api/sessions/${sessions[0].session_id}/messages`);
          pending.push(first);
          await project.getByRole('button', { name: sessions[0].title, exact: true }).click();
          await first.requested;
          await expect(page).toHaveURL(new RegExp(`session=${sessions[0].session_id}`));
          await expect(page.locator('.chat-title')).toHaveText(sessions[0].title);
          expect(await header!.evaluate((node) => node === document.querySelector('.topbar'))).toBe(true);
          expect(await composer!.evaluate((node) => node === document.querySelector('.composer textarea'))).toBe(true);
          await expect(page.locator('.chat-empty')).toHaveCount(0);
          await expect(page.getByRole('button', { name: labels.send, exact: true })).toBeDisabled();
          await expect(page.getByRole('button', { name: labels.attach, exact: true })).toBeDisabled();
          await expect(page.getByRole('button', { name: labels.sessionSettings, exact: true })).toBeDisabled();
          await page.clock.runFor(199);
          await expect(page.locator('.workspace').locator(status)).toHaveCount(0);
          await page.clock.runFor(1);
          await expect(page.locator('.workspace').locator(status)).toHaveText(common.loading);
          await openSidebar(page);
          const second = await holdResponse(page, `**/api/sessions/${sessions[1].session_id}/messages`);
          pending.push(second);
          await project.getByRole('button', { name: sessions[1].title, exact: true }).click();
          await second.requested;
          await expect(page.locator('.chat-title')).toHaveText(sessions[1].title);
          await expect(page.locator('.workspace').locator(status)).toHaveCount(0);
          await page.clock.runFor(199);
          await expect(page.locator('.workspace').locator(status)).toHaveCount(0);
          await second.release();
          await expect(page.locator('.chat-title')).toHaveText(sessions[1].title);
          await first.release();
          await page.clock.runFor(300);
          await expect(page.locator('.chat-title')).toHaveText(sessions[1].title);
          await expect(page.locator('.workspace').locator(status)).toHaveCount(0);
          await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0);
          expect(await header!.evaluate((node) => node === document.querySelector('.topbar'))).toBe(true);
          expect(await composer!.evaluate((node) => node === document.querySelector('.composer textarea'))).toBe(true);
          await page.clock.resume();
          await openSidebar(page);
          await expect(project.locator('.project-select')).toHaveAttribute('data-active', '');
          await expect(project.locator('.session-item.selected')).toHaveCount(1);
          const ordinary = page.locator('.session-sidebar [data-sidebar="menu"] > .session-item .session-select').first();
          const ordinaryTitle = await ordinary.getAttribute('title');
          await ordinary.click();
          await expect(page.locator('.chat-title')).toHaveText(ordinaryTitle!);
          await expect(page.locator('.workspace').locator(status)).toHaveCount(0);
        } finally {
          for (const held of pending) await held.release();
          await request.delete(`/api/projects/${id}`);
        }
      });

      test('ordinary selection keeps the shell, preserves repeated-click input and retries locally', async ({ page, request }) => {
        const response = await request.post('/api/sessions', { data: { title: 'Retry target' } });
        expect(response.ok()).toBe(true);
        const target = await response.json();
        const pending: Array<{ release: () => Promise<void> }> = [];
        try {
          await page.goto('/');
          await expect(page.getByRole('button', { name: labels.sessionSettings, exact: true })).toBeEnabled();
          await openSidebar(page);
          const rows = page.locator('.session-sidebar [data-sidebar="menu"] > .session-item .session-select');
          await rows.filter({ hasNotText: 'Retry target' }).first().click();
          await expect(page.getByRole('button', { name: labels.sessionSettings, exact: true })).toBeEnabled();
          const header = await page.locator('.topbar').elementHandle();
          const composer = await page.locator('.composer textarea').elementHandle();
          const failed = await holdResponse(page, `**/api/sessions/${target.session_id}/messages`, true);
          pending.push(failed);
          await openSidebar(page);
          await rows.filter({ hasText: 'Retry target' }).click();
          await failed.requested;
          await expect(page.locator('.chat-title')).toHaveText('Retry target');
          await expect(page.locator('.chat-empty')).toHaveCount(0);
          await failed.release();
          await expect(page.locator('.chat-view').getByRole('alert')).toContainText('Retry loading');
          await expect(page.getByRole('button', { name: labels.attach, exact: true })).toBeDisabled();
          const retry = await holdResponse(page, `**/api/sessions/${target.session_id}/messages`);
          pending.push(retry);
          await page.locator('.chat-view').getByRole('button', { name: settings.resources.refresh, exact: true }).click();
          await retry.requested;
          await expect(page.locator('.chat-view').getByRole('alert')).toHaveCount(0);
          await retry.release();
          await expect(page.getByRole('button', { name: labels.sessionSettings, exact: true })).toBeEnabled();
          await page.locator('.composer textarea').fill('Keep input');
          await openSidebar(page);
          await rows.filter({ hasText: 'Retry target' }).click();
          await expect(page.locator('.composer textarea')).toHaveValue('Keep input');
          expect(await header!.evaluate((node) => node === document.querySelector('.topbar'))).toBe(true);
          expect(await composer!.evaluate((node) => node === document.querySelector('.composer textarea'))).toBe(true);
        } finally {
          for (const held of pending) await held.release();
          await request.delete(`/api/sessions/${target.session_id}`);
        }
      });

      test('direct links and cross-Project history preserve the conversation shell', async ({ page, request }) => {
        const firstId = await workspace(request), secondId = await workspace(request);
        const first = (await (await request.get(`/api/projects/${firstId}/sessions`)).json())[0];
        const second = (await (await request.get(`/api/projects/${secondId}/sessions`)).json())[1];
        const details = await holdResponse(page, `**/api/sessions/${first.session_id}`);
        try {
          await page.goto(`/projects/${firstId}?session=${first.session_id}`);
          await details.requested;
          await expect(page.locator('.chat-title')).toHaveText(common.loading);
          const header = await page.locator('.topbar').elementHandle();
          const composer = await page.locator('.composer textarea').elementHandle();
          await expect(page.locator('.composer textarea')).toBeDisabled();
          await details.release();
          await expect(page.locator('.chat-title')).toHaveText(first.title);
          await expect(page.getByRole('button', { name: labels.sessionSettings, exact: true })).toBeEnabled();
          await openSidebar(page);
          const project = page.locator(`[data-project-id="${secondId}"]`);
          await project.locator('.project-select').click();
          await project.getByRole('button', { name: second.title, exact: true }).click();
          await expect(page).toHaveURL(new RegExp(`/projects/${secondId}\\?session=${second.session_id}`));
          await expect(page.locator('.chat-title')).toHaveText(second.title);
          await page.goBack();
          await expect(page.locator('.chat-title')).toHaveText(first.title);
          await page.goForward();
          await expect(page.locator('.chat-title')).toHaveText(second.title);
          await expect(page.getByRole('button', { name: labels.sessionSettings, exact: true })).toBeEnabled();
          expect(await header!.evaluate((node) => node === document.querySelector('.topbar'))).toBe(true);
          expect(await composer!.evaluate((node) => node === document.querySelector('.composer textarea'))).toBe(true);
        } finally {
          await details.release();
          await request.delete(`/api/projects/${firstId}`);
          await request.delete(`/api/projects/${secondId}`);
        }
      });

      test('settings and Runtime use compact delayed feedback', async ({ page, request }) => {
        await request.post('/__test__/runtimes', { data: {} });
        const pending: Array<{ release: () => Promise<void> }> = [];
        try {
          await pauseClock(page);
          const resources = await holdResponse(page, '**/api/knowledge/bases');
          const runtime = await holdResponse(page, '**/api/models/local-runtime/catalog');
          pending.push(resources, runtime);
          await page.goto('/settings?tab=knowledge');
          await resources.requested;
          await page.clock.runFor(199);
          await expect(page.locator('.settings-content').locator(status)).toHaveCount(0);
          await page.clock.runFor(1);
          await expect(page.locator('.settings-content').locator(status)).toContainText(common.loading);
          await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0);
          await resources.release();
          await expect(page.locator('.settings-content').locator(status)).toHaveCount(0);
          await page.clock.resume();
          await navigateModelSettings(page, 'localRuntime');
          await runtime.requested;
          await expect(page.locator('.runtime-packages').locator(status)).toHaveText(common.loading);
          await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0);
          await runtime.release();
          await expect(page.locator('.runtime-package')).toHaveCount(2);
          const storage = await holdResponse(page, '**/api/models/local-runtime/storage');
          pending.push(storage);
          await page.getByRole('button', { name: llm.storage.scan, exact: true }).click();
          await storage.requested;
          await expect(page.locator('.runtime-storage').locator(status)).toHaveText(common.loading);
          await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0);
          await storage.release();
          await expect(page.locator('.runtime-storage-summary')).toBeVisible();
          const refresh = await holdResponse(page, '**/api/models/local-runtime/storage');
          pending.push(refresh);
          await page.getByRole('button', { name: llm.storage.scan, exact: true }).click();
          await refresh.requested;
          await page.clock.runFor(300);
          await expect(page.locator('.runtime-storage-summary')).toBeVisible();
          await expect(page.locator('.runtime-storage').locator(status)).toHaveCount(0);
          await refresh.release();
        } finally {
          for (const held of pending) await held.release();
        }
      });
    });
  }
}
