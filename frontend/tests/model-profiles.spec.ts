import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { modelKinds, type ModelProfile } from '../src/types/models';
import { newModel } from '../src/components/settings/models/profileDefaults';
import { fillCombobox, navigateModelSettings } from './controls';

const directories = { llm: 'llms', embedding: 'embeddings', reranker: 'rerankers',
  image_embedding: 'image_embeddings', vision: 'vision', tts: 'tts', asr: 'asr', processor: 'processors' };

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`model profile cards ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('local kinds show cards, local suggestions and persistent enable switches', async ({ page, request }, info) => {
        test.setTimeout(90000);
        const profiles: ModelProfile[] = [];
        for (const kind of modelKinds.filter((kind) => kind !== 'image_generation')) {
          const response = await request.post('/api/models/profiles', { data: {
            ...newModel(kind), name: `${kind} ${'LongModelName'.repeat(5)} ${locale} ${width}`,
            alias: `profile-card-${kind}-${locale.toLowerCase()}-${width}`,
            model_ref: `${directories[kind]}/card-fixture`,
          } });
          expect(response.ok(), await response.text()).toBe(true);
          profiles.push(await response.json());
        }
        await page.route('**/api/models/inventory?*', (route) => {
          const kind = new URL(route.request().url()).searchParams.get('kind');
          const profile = profiles.find((item) => item.kind === kind)!;
          return route.fulfill({ json: [{ kind, name: 'card-fixture', model_ref: profile.model_ref,
            state: 'unavailable', error_code: 'MODEL_UNAVAILABLE' }] });
        });
        await page.goto('/settings?tab=models&view=llm');
        for (const profile of profiles) {
          await navigateModelSettings(page, profile.kind);
          const card = page.getByRole('group', { name: profile.name, exact: true });
          await expect(card).toHaveAttribute('data-slot', 'card');
          await expect(card).toContainText(profile.alias);
          await expect(card.getByText(labels.localRuntime, { exact: true })).toBeVisible();
          await expect(card).not.toContainText(profile.model_ref);
          await expect(card).not.toContainText('1.0.0');
          await expect(card.getByRole('switch', { name: labels.modelEnabled.replace('{{name}}', profile.name), exact: true })).toBeChecked();
          await expect(card.getByRole('button', { name: labels.edit, exact: true })).toBeVisible();
          await expect(card.getByRole('button', { name: labels.load, exact: true })).toBeVisible();
          await expect(page.getByRole('button', { name: labels.refresh, exact: true })).toHaveCount(1);
          await expect(page.locator('.models-panel > .model-heading')).toHaveCount(0);
          expect(await card.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
          if (profile.kind === 'llm') await page.screenshot({ path: info.outputPath('model-cards.png') });
          await page.getByRole('button', { name: labels.addModel, exact: true }).click();
          const dialog = page.getByRole('dialog');
          const source = dialog.getByLabel(labels.source, { exact: true });
          await expect(source.locator('[data-slot="select-value"]')).toHaveText(labels.localRuntime);
          const reference = dialog.getByLabel(labels.modelRef, { exact: true });
          await reference.press('ArrowDown');
          await page.getByRole('option', { name: profile.model_ref, exact: true }).click();
          await expect(reference).toHaveValue(profile.model_ref);
          await expect(dialog.getByLabel(labels.alias, { exact: true })).toHaveValue(profile.model_ref.replaceAll('/', '-'));
          await expect(dialog.getByRole('switch', { name: labels.enabled, exact: true })).toHaveCount(0);
          await expect(dialog.getByLabel(labels.name, { exact: true })).toHaveValue(profile.model_ref);
          await dialog.getByRole('button', { name: labels.close, exact: true }).click();
        }

        await navigateModelSettings(page, 'llm');
        const profile = profiles.find((item) => item.kind === 'llm')!;
        const card = page.getByRole('group', { name: profile.name, exact: true });
        const toggle = card.getByRole('switch');
        let release!: () => void;
        const pending = new Promise<void>((resolve) => { release = resolve; });
        const endpoint = `**/api/models/profiles/${profile.id}`;
        await page.route(endpoint, async (route) => {
          if (route.request().method() === 'PATCH') await pending;
          await route.continue();
        });
        const changed = page.waitForRequest((value) => value.method() === 'PATCH' && value.url().endsWith(`/profiles/${profile.id}`));
        await toggle.focus();
        await toggle.press('Space');
        expect((await changed).postDataJSON()).toEqual({ enabled: false });
        await expect(toggle).toBeDisabled();
        await expect(toggle).toBeChecked();
        await expect(card.getByRole('button', { name: labels.edit, exact: true })).toBeDisabled();
        release();
        await expect(toggle).not.toBeChecked();
        await expect(toggle).toBeEnabled();
        await page.unroute(endpoint);
        await page.route(endpoint, (route) => route.fulfill({ status: 409, json: {
          error: { code: 'MODEL_BUSY', message: 'Fixture model is busy' },
        } }), { times: 1 });
        await toggle.click();
        await expect(page.getByRole('alert')).toContainText('MODEL_BUSY: Fixture model is busy');
        await expect(toggle).toBeEnabled();
        await expect(toggle).not.toBeChecked();
        await toggle.click();
        await expect(toggle).toBeChecked();
        await expect(toggle).toBeEnabled();
        await page.reload();
        await expect(toggle).toBeChecked();
        for (const item of profiles) await request.delete(`/api/models/profiles/${item.id}`);
      });

      test('new model identity and required windows survive source changes and directory inspection', async ({ page, request }) => {
        const provider = await (await request.post('/api/models/providers', { data: {
          name: `Creation provider ${locale} ${width}`, connection: { base_url: 'https://provider.test/v1' },
        } })).json();
        await page.route(`**/api/models/providers/${provider.id}/models`, (route) => route.fulfill({ json: { models: ['Org/Remote V2'] } }));
        let release!: () => void;
        const pending = new Promise<void>((resolve) => { release = resolve; });
        await page.route('**/api/models/inspect?*', async (route) => {
          await pending;
          await route.fulfill({ json: { kind: 'llm', model_ref: 'llms/Test', engine: 'transformers',
            architecture: 'Qwen', main_model_ref: null, mmproj_ref: null, model_files: [], diagnostics: [] } });
        });
        await page.goto('/settings?tab=models&view=llm');
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const reference = dialog.getByLabel(labels.modelRef, { exact: true });
        const name = dialog.getByLabel(labels.name, { exact: true });
        const alias = dialog.getByLabel(labels.alias, { exact: true });
        const context = dialog.getByLabel(labels.contextWindow, { exact: true });
        const save = dialog.getByRole('button', { name: labels.save, exact: true });
        const choose = async (label: string) => {
          await source.click();
          await page.getByRole('option', { name: label, exact: true }).click();
        };
        await expect(context).toHaveValue('4096');
        await choose(provider.name);
        await expect(context).toHaveValue('4096');
        await reference.press('ArrowDown');
        await page.getByRole('option', { name: 'Org/Remote V2', exact: true }).click();
        await expect(name).toHaveValue('Org/Remote V2');
        await expect(alias).toHaveValue('org-remote-v2');
        await choose(labels.localRuntime);
        await context.fill('');
        await choose(provider.name);
        await expect(context).toHaveValue('258000');
        await context.fill('64000');
        await choose(labels.localRuntime);
        await expect(context).toHaveValue('64000');
        await name.fill('');
        await fillCombobox(reference, 'llms/Test');
        await expect(name).toHaveValue('llms/Test');
        await expect(alias).toHaveValue('org-remote-v2');
        release();
        await expect(dialog.getByText(labels.engines.transformers, { exact: true }).first()).toBeVisible();
        await expect(context).toHaveValue('64000');
        await alias.fill('');
        await fillCombobox(reference, 'llms/Other');
        await expect(name).toHaveValue('llms/Test');
        await expect(alias).toHaveValue('llms-other');
        for (const invalid of ['', '511', '512.5', '1048577']) {
          await context.fill(invalid);
          await save.click();
          await expect(dialog).toBeVisible();
          expect(await context.evaluate((node: HTMLInputElement) => node.validity.valid)).toBe(false);
        }
        await context.fill('');
        await choose(provider.name);
        await expect(context).toHaveValue('258000');
        await fillCombobox(reference, 'Org/Manual');
        await alias.fill(`creation-${locale.toLowerCase()}-${width}`);
        await context.fill('');
        await save.click();
        expect(await context.evaluate((node: HTMLInputElement) => node.validity.valueMissing)).toBe(true);
        await context.fill('258000');
        const created = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/api/models/profiles'));
        await save.click();
        const response = await created;
        expect(response.ok(), await response.text()).toBe(true);
        const profile = await response.json();
        expect(profile.context_window_tokens).toBe(258000);
        expect(profile.enabled).toBe(true);
        await expect(dialog).toHaveCount(0);
        const card = page.getByRole('group', { name: profile.name, exact: true });
        await card.getByRole('switch').click();
        await expect(card.getByRole('switch')).not.toBeChecked();
        await card.getByRole('button', { name: labels.edit, exact: true }).click();
        await expect(dialog.getByRole('switch', { name: labels.enabled, exact: true })).toHaveCount(0);
        await name.fill('');
        await alias.fill('');
        await fillCombobox(reference, 'Org/Edited');
        await expect(name).toHaveValue('');
        await expect(alias).toHaveValue('');
        await name.fill(profile.name);
        await alias.fill(profile.alias);
        await context.fill('');
        await save.click();
        await expect(dialog).toHaveCount(0);
        const saved = await (await request.get(`/api/models/profiles/${profile.id}`)).json();
        expect(saved.enabled).toBe(false);
        expect(saved.context_window_tokens).toBe(null);
        await request.delete(`/api/models/profiles/${profile.id}`);
        await request.delete(`/api/models/providers/${provider.id}`);
      });

      test('provider badges and existing unbound drafts require a source for edit and copy', async ({ page, request }, info) => {
        const provider = await (await request.post('/api/models/providers', { data: {
          name: `${'ConnectedProvider'.repeat(6)} ${locale} ${width}`, connection: { base_url: 'https://provider.test/v1' },
        } })).json();
        const external = await (await request.post('/api/models/profiles', { data: {
          ...newModel('llm'), name: `External card ${locale} ${width}`, alias: `profile-external-${locale.toLowerCase()}-${width}`,
          source: { type: 'provider', provider_profile_id: provider.id }, model_ref: 'hidden-remote-reference',
        } })).json();
        const draft = await (await request.post('/api/models/profiles', { data: {
          ...newModel('reranker'), name: `Unconfigured card ${locale} ${width}`, alias: `profile-unconfigured-${locale.toLowerCase()}-${width}`,
          source: null, model_ref: 'rerankers/missing',
        } })).json();
        await page.goto('/settings?tab=models&view=llm');
        const card = page.getByRole('group', { name: external.name, exact: true });
        const sourceBadge = card.getByText(provider.name, { exact: true });
        await expect(sourceBadge).toBeVisible();
        expect(await sourceBadge.evaluate((node) => node.scrollHeight <= node.clientHeight + 1)).toBe(true);
        await expect(card).not.toContainText(external.model_ref);
        await expect(card.getByRole('button', { name: labels.load, exact: true })).toHaveCount(0);
        expect(await card.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
        await page.screenshot({ path: info.outputPath('provider-model-card.png') });
        await navigateModelSettings(page, 'reranker');
        const unconfigured = page.getByRole('group', { name: draft.name, exact: true });
        await expect(unconfigured.getByText(labels.unconfigured, { exact: true })).toBeVisible();
        const dialog = page.getByRole('dialog');
        const source = dialog.getByLabel(labels.source, { exact: true });
        const save = dialog.getByRole('button', { name: labels.save, exact: true });
        for (const action of [labels.duplicate, labels.edit]) {
          await unconfigured.getByRole('button', { name: action, exact: true }).click();
          await expect(source.locator('[data-slot="select-value"]')).toHaveText(labels.selectModelSource);
          await expect(source).toBeEnabled();
          await expect(save).toBeDisabled();
          await source.click();
          await expect(page.getByRole('option')).toHaveText([labels.localRuntime]);
          await page.getByRole('option', { name: labels.localRuntime, exact: true }).click();
          await expect(dialog.getByLabel(labels.modelRef, { exact: true })).toHaveValue(draft.model_ref);
          await expect(save).toBeEnabled();
          if (action === labels.edit) await save.click();
          else await dialog.getByRole('button', { name: labels.close, exact: true }).click();
          await expect(dialog).toHaveCount(0);
        }
        expect((await (await request.get(`/api/models/profiles/${draft.id}`)).json()).source.type).toBe('local');
        await request.delete(`/api/models/profiles/${draft.id}`);
        await request.delete(`/api/models/profiles/${external.id}`);
        await request.delete(`/api/models/providers/${provider.id}`);
      });

      test('directory loading, filtering, failures and refreshed candidates preserve manual input', async ({ page, request }) => {
        let release!: () => void;
        const pending = new Promise<void>((resolve) => { release = resolve; });
        let mode = 'loading';
        let calls = 0;
        await page.route('**/api/models/inventory?kind=llm', async (route) => {
          calls++;
          if (mode === 'loading') await pending;
          if (mode === 'failed') return route.fulfill({ status: 500, json: {
            error: { code: 'INVENTORY_ERROR', message: 'Fixture directory read failed' },
          } });
          return route.fulfill({ json: mode === 'empty' ? [] : [
            { kind: 'llm', name: mode, model_ref: `llms/${mode}`, state: 'unavailable', error_code: 'MODEL_UNAVAILABLE' },
          ] });
        });
        await page.goto('/settings?tab=models&view=llm');
        expect(calls).toBe(0);
        const add = page.getByRole('button', { name: labels.addModel, exact: true });
        const dialog = page.getByRole('dialog');
        const reference = dialog.getByLabel(labels.modelRef, { exact: true });
        const close = dialog.getByRole('button', { name: labels.close, exact: true });
        await add.click();
        await reference.press('ArrowDown');
        await expect(page.getByText(labels.referenceSuggestions.loading, { exact: true })).toBeVisible();
        mode = 'first';
        release();
        await page.getByRole('option', { name: 'llms/first', exact: true }).click();
        await expect(reference).toHaveValue('llms/first');
        await reference.fill('llms/manual');
        await expect(page.getByText(labels.referenceSuggestions.noMatch, { exact: true })).toBeVisible();
        await reference.press('Tab');
        await close.click();
        mode = 'second';
        await add.click();
        await reference.press('ArrowDown');
        await expect(page.getByRole('option')).toHaveText(['llms/second']);
        await page.keyboard.press('Escape');
        await close.click();
        mode = 'empty';
        await add.click();
        await reference.press('ArrowDown');
        await expect(page.getByText(labels.referenceSuggestions.noDirectories, { exact: true })).toBeVisible();
        await page.keyboard.press('Escape');
        await close.click();
        mode = 'failed';
        await add.click();
        await expect(dialog.getByRole('status')).toContainText(labels.referenceSuggestions.localUnavailable);
        await fillCombobox(reference, 'llms/manual');
        const alias = `profile-manual-${locale.toLowerCase()}-${width}`;
        await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toHaveCount(0);
        const saved = (await (await request.get('/api/models/profiles')).json()).find((item: ModelProfile) => item.alias === alias);
        expect(saved.model_ref).toBe('llms/manual');
        expect(saved.source.type).toBe('local');
        expect(calls).toBe(4);
        await request.delete(`/api/models/profiles/${saved.id}`);
      });
    });
  }
}
