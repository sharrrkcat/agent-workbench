import { readFileSync } from 'node:fs';
import { expect, test, type APIRequestContext, type APIResponse, type Page } from '@playwright/test';
import { answerConfirmation, chooseOption, openSidebar } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const result = await response; expect(result.ok(), await result.text()).toBe(true); return result.json(); }
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight)).toBe(true);
}
async function personas(request: APIRequestContext, collection: string) { return json(request.get(`/api/personas?collection=${collection}`)); }

for (const locale of ['en', 'zh-CN']) {
  const labels = words(locale, 'personas'), llm = words(locale, 'llm');
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`Projects ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test.beforeEach(async ({ page, request }) => {
        await request.post('/__test__/session');
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('Workspace creation, sparse overrides, inherited resources and guarded navigation', async ({ page, request }, info) => {
        const tag = `${locale}-${viewport.width}-${Date.now()}`;
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        const models = await json(request.get('/api/models/profiles'));
        const agent = await json(request.post('/api/personas', { data: { collection: 'agent', name: `Agent ${tag}` } }));
        const bases = [];
        for (const name of ['Project', 'Extra']) bases.push(await json(request.post('/api/knowledge/bases', {
          data: { name: `${name} ${tag}`, embedding_model_profile_id: models.find((model: { kind: string }) => model.kind === 'embedding').id },
        })));
        let projectId = '';
        try {
          await page.goto('/');
          await openSidebar(page);
          await page.locator('.session-sidebar').getByRole('button', { name: labels.newWorkspace, exact: true }).click();
          let dialog = page.getByRole('dialog', { name: labels.newWorkspace, exact: true });
          await dialog.getByLabel(labels.projectName, { exact: true }).fill(`Workspace ${tag}`);
          await chooseOption(dialog.getByLabel(labels.defaultAgentPersona, { exact: true }), agent.name);
          await dialog.getByLabel(labels.projectPrompt, { exact: true }).fill('Project instructions');
          await dialog.getByRole('checkbox', { name: 'read_file', exact: true }).uncheck();
          await dialog.getByRole('tab', { name: labels.knowledge, exact: true }).click();
          await dialog.getByRole('checkbox', { name: bases[0].name, exact: true }).check();
          const created = page.waitForResponse((r) => r.url().endsWith('/api/projects') && r.request().method() === 'POST');
          await dialog.getByRole('button', { name: labels.createProject, exact: true }).click();
          const project = await (await created).json();
          projectId = project.id;
          expect(project.kind).toBe('workspace');
          expect(project.knowledge_base_ids).toEqual([bases[0].id]);
          await expect(dialog).toBeHidden();
          await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
          expect(await json(request.get(`/api/projects/${projectId}/sessions`))).toEqual([]);
          await page.locator('.settings-header').getByRole('button', { name: labels.newSession, exact: true }).click();
          await expect(page).toHaveURL(new RegExp(`/projects/${projectId}\\?session=`));
          const sessionId = new URL(page.url()).searchParams.get('session')!;
          expect((await json(request.get(`/api/sessions/${sessionId}`))).overrides).toEqual({});
          await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
          dialog = page.getByRole('dialog', { name: labels.sessionSettings, exact: true });
          await expect(dialog.getByLabel(labels.agentPersona, { exact: true })).toContainText(agent.name);
          await expect(dialog.getByRole('checkbox', { name: 'read_file', exact: true })).toBeDisabled();
          await expect(dialog.getByLabel(labels.collections.user, { exact: true })).toHaveCount(0);
          await dialog.getByRole('switch', { name: labels.harnessEnabled, exact: true }).check();
          await dialog.getByRole('spinbutton', { name: llm.params.temperature, exact: true }).fill('0');
          await dialog.getByRole('tab', { name: labels.knowledge, exact: true }).click();
          const inherited = dialog.getByRole('region', { name: labels.projectBindings }).getByRole('checkbox', { name: bases[0].name, exact: true });
          await expect(inherited).toBeChecked();
          await expect(inherited).toBeDisabled();
          await dialog.getByRole('region', { name: labels.sessionAdditions }).getByRole('checkbox', { name: bases[1].name, exact: true }).check();
          const saved = page.waitForRequest((r) => r.url().endsWith(`/api/sessions/${sessionId}`) && r.method() === 'PATCH');
          await dialog.getByRole('button', { name: labels.save, exact: true }).click();
          expect((await saved).postDataJSON()).toEqual({ overrides: { harness_enabled: true, temperature: 0 } });
          await expect(dialog).toBeHidden();
          await page.locator('.composer textarea').fill('Workspace question');
          await page.locator('.composer').getByRole('button', { name: labels.send, exact: true }).click();
          await expect(page.locator('.reply-answer')).toContainText('Browser final answer.');
          await page.locator('.composer textarea').fill('Retained draft');
          await json(request.patch(`/api/projects/${projectId}`, { data: { temperature: 0.85, context_policy: { mode: 'current_message' } } }));
          await expect(page.locator('.composer textarea')).toHaveValue('Retained draft');
          await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
          dialog = page.getByRole('dialog', { name: labels.sessionSettings, exact: true });
          await expect(dialog.getByRole('spinbutton', { name: llm.params.temperature, exact: true })).toHaveValue('0');
          await dialog.getByRole('button', { name: labels.restoreInheritanceFor.replace('{{field}}', llm.params.temperature), exact: true }).click();
          await expect(dialog.getByRole('spinbutton', { name: llm.params.temperature, exact: true })).toHaveValue('0.85');
          await json(request.patch(`/api/projects/${projectId}/knowledge-bases`, { data: { knowledge_base_ids: bases.map((base) => base.id) } }));
          await dialog.getByRole('tab', { name: labels.knowledge, exact: true }).click();
          const newlyInherited = dialog.getByRole('region', { name: labels.projectBindings }).getByRole('checkbox', { name: bases[1].name, exact: true });
          await expect(newlyInherited).toBeChecked();
          await expect(newlyInherited).toBeDisabled();
          const extraBinding = dialog.getByRole('region', { name: labels.sessionAdditions }).getByRole('checkbox', { name: bases[1].name, exact: true });
          await extraBinding.click();
          await expect(extraBinding).toHaveCount(0);
          await dialog.getByRole('button', { name: labels.save, exact: true }).click();
          await expect(dialog).toBeHidden();
          expect((await json(request.get(`/api/sessions/${sessionId}`))).overrides).toEqual({ harness_enabled: true });
          const refreshedBindings = await json(request.get(`/api/sessions/${sessionId}/knowledge-bases`));
          expect(refreshedBindings.knowledge_base_ids).toEqual([]);
          expect(refreshedBindings.effective_knowledge_base_ids).toEqual(bases.map((base) => base.id));
          await page.reload();
          await expect(page.locator('.reply-answer')).toContainText('Browser final answer.');
          await openSidebar(page);
          await page.locator(`[data-project-id="${projectId}"] .project-select`).click();
          await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
          await page.getByLabel(labels.projectName, { exact: true }).fill('Unsaved name');
          await page.evaluate(() => history.back());
          await answerConfirmation(page, false, locale);
          await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
          await expect(page.getByLabel(labels.projectName, { exact: true })).toHaveValue('Unsaved name');
          await page.evaluate(() => history.back());
          await answerConfirmation(page, true, locale);
          await expect(page).toHaveURL(new RegExp(`session=${sessionId}$`));
          await openSidebar(page);
          const row = page.locator(`[data-project-id="${projectId}"] .session-item`);
          await row.getByRole('button', { name: labels.sessionActions.replace('{{title}}', labels.newSession), exact: true }).click();
          await page.getByRole('menuitem', { name: labels.deleteSession, exact: true }).click();
          await answerConfirmation(page, true, locale);
          await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
          expect(await json(request.get(`/api/projects/${projectId}/sessions`))).toEqual([]);
          await openSidebar(page);
          await expect(page.getByText(labels.noProjectSessions, { exact: true })).toBeVisible();
          await page.screenshot({ path: info.outputPath('workspace-project.png') });
          await noOverflow(page);
          expect(errors).toEqual([]);
        } finally {
          if (projectId) await request.delete(`/api/projects/${projectId}`);
          await request.delete(`/api/personas/${agent.id}`);
          for (const base of bases) await request.delete(`/api/knowledge/bases/${base.id}`);
        }
      });

      test('Timeline requires roleplay identities and provides settings without conversation controls', async ({ page, request }, info) => {
        const tag = `${locale}-${viewport.width}-${Date.now()}`;
        const identities = [];
        for (const collection of ['character', 'roleplay_user']) identities.push(await json(request.post('/api/personas', { data: { collection, name: `${collection} ${tag}` } })));
        const book = await json(request.post('/api/worldbooks', { data: { name: `World ${tag}` } }));
        let projectId = '';
        try {
          await page.goto('/');
          await openSidebar(page);
          await page.locator('.session-sidebar').getByRole('button', { name: labels.newTimeline, exact: true }).click();
          const dialog = page.getByRole('dialog', { name: labels.newTimeline, exact: true });
          await dialog.getByLabel(labels.projectName, { exact: true }).fill(`Timeline ${tag}`);
          await dialog.getByRole('button', { name: labels.createProject, exact: true }).click();
          await expect(dialog.getByRole('alert')).toContainText(labels.projectRequired);
          await chooseOption(dialog.getByLabel(labels.characterPersona, { exact: true }), identities[0].name);
          await chooseOption(dialog.getByLabel(labels.timelineUserPersona, { exact: true }), identities[1].name);
          await expect(dialog.getByRole('switch', { name: labels.harnessEnabled, exact: true })).toHaveCount(0);
          await expect(dialog.getByRole('tab', { name: labels.knowledge, exact: true })).toHaveCount(0);
          await dialog.getByRole('tab', { name: labels.worldbook, exact: true }).click();
          await dialog.getByRole('checkbox', { name: book.name, exact: true }).check();
          const created = page.waitForResponse((r) => r.url().endsWith('/api/projects') && r.request().method() === 'POST');
          await dialog.getByRole('button', { name: labels.createProject, exact: true }).click();
          const project = await (await created).json();
          projectId = project.id;
          expect(project.worldbook_ids).toEqual([book.id]);
          await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
          await expect(page.locator('.composer')).toHaveCount(0);
          await expect(page.locator('.settings-header').getByRole('button', { name: labels.newSession, exact: true })).toHaveCount(0);
          expect((await request.post(`/api/projects/${projectId}/sessions`, { data: {} })).status()).toBe(409);
          await page.reload();
          await expect(page.getByLabel(labels.characterPersona, { exact: true })).toContainText(identities[0].name);
          await page.getByLabel(labels.projectName, { exact: true }).fill(`Renamed ${tag}`);
          await page.getByRole('button', { name: labels.save, exact: true }).click();
          await expect(page.getByRole('status')).toContainText(labels.projectSaved);
          await page.screenshot({ path: info.outputPath('timeline-project.png') });
          await noOverflow(page);
          await openSidebar(page);
          await page.getByRole('button', { name: labels.projectActions.replace('{{name}}', `Renamed ${tag}`), exact: true }).click();
          await page.getByRole('menuitem', { name: labels.deleteProject, exact: true }).click();
          await answerConfirmation(page, true, locale);
          await expect(page).toHaveURL(/\/$/);
          await expect(page.locator('.composer textarea')).toBeVisible();
          expect((await request.get(`/api/worldbooks/${book.id}`)).ok()).toBe(true);
          expect((await personas(request, 'user')).length).toBe(1);
        } finally {
          if (projectId) await request.delete(`/api/projects/${projectId}`);
          for (const persona of identities) await request.delete(`/api/personas/${persona.id}`);
          await request.delete(`/api/worldbooks/${book.id}`);
        }
      });
    });
  }
}

test('A delayed Workspace session creation preserves a later settings navigation', async ({ page, request }) => {
  const labels = words('en', 'personas');
  await request.post('/__test__/session');
  await page.addInitScript(() => localStorage.setItem('cogita.locale', 'en'));
  const agents = await personas(request, 'agent'), users = await personas(request, 'user');
  const project = await json(request.post('/api/projects', { data: {
    kind: 'workspace', name: 'Delayed creation', agent_persona_id: agents[0].id, cogita_persona_id: users[0].id,
    context_policy: { mode: 'session' }, harness_enabled: false, tools_allowed: [],
  } }));
  let release!: () => void, started!: () => void, createdSessionId = '';
  const held = new Promise<void>((resolve) => { release = resolve; });
  const submitted = new Promise<void>((resolve) => { started = resolve; });
  await page.route(`**/api/projects/${project.id}/sessions`, async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch();
    createdSessionId = (await response.json()).session_id;
    started();
    await held;
    await route.fulfill({ response });
  });
  try {
    await page.goto(`/projects/${project.id}`);
    await expect(page.getByLabel(labels.projectName, { exact: true })).toHaveValue(project.name);
    await page.locator('.settings-header').getByRole('button', { name: labels.newSession, exact: true }).click();
    await submitted;
    await openSidebar(page);
    await page.locator('.sidebar-settings-button').click();
    await expect(page).toHaveURL(/\/settings$/);
    const refreshed = page.waitForResponse((r) => r.url().endsWith(`/api/sessions/${createdSessionId}`) && r.request().method() === 'GET');
    release();
    await refreshed;
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.locator('.settings-sidebar')).toBeVisible();
    expect((await json(request.get(`/api/projects/${project.id}/sessions`))).map((session: { session_id: string }) => session.session_id)).toEqual([createdSessionId]);
  } finally {
    release();
    await request.delete(`/api/projects/${project.id}`);
  }
});
