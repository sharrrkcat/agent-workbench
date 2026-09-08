import { expect, test, type Page, type APIRequestContext } from '@playwright/test';

const labels = (locale: string) => locale === 'en' ? {
  addBook: 'Add worldbook', addBase: 'Add knowledge base', name: 'Name', baseName: 'Knowledge base name', save: 'Save', config: 'Configuration',
  entry: 'New entry', content: 'Content', entries: 'Entries', keywords: 'Keywords', match: 'Match test', matchText: 'Test text',
  sourceTitle: 'Title', text: 'Text', paste: 'Paste text', upload: 'Upload files', index: 'Add and index', close: 'Close', chunks: 'Chunks',
  searchTab: 'Search test', query: 'Query', search: 'Search', preview: 'Source details', embedding: 'Embedding profile',
  back: 'Back', reset: 'Reset', collapse: 'Collapse entry', globals: 'Global settings', enabled: 'Enable worldbook context',
  advanced: 'Advanced', maxContext: 'Maximum context characters', rerank: 'Enable optional reranker', retry: 'Retry remaining',
} : {
  addBook: '添加世界书', addBase: '添加知识库', name: '名称', baseName: '知识库名称', save: '保存', config: '配置',
  entry: '新建条目', content: '条目正文', entries: '条目', keywords: '关键词', match: '匹配测试', matchText: '测试文本',
  sourceTitle: '标题', text: '文本', paste: '粘贴文本', upload: '上传文件', index: '添加并索引', close: '关闭', chunks: '分块',
  searchTab: '检索测试', query: '查询文本', search: '检索', preview: '来源详情', embedding: '嵌入模型配置',
  back: '返回', reset: '重置', collapse: '折叠条目', globals: '全局设置', enabled: '启用世界书上下文',
  advanced: '高级设置', maxContext: '最大上下文字符数', rerank: '启用可选重排模型', retry: '重试未完成项',
};

async function noOverflow(page: Page) {
  const overflow = await page.evaluate(() => [...document.querySelectorAll('body, .settings-page, .settings-content, .resource-panel, .worldbook-entry-card, .worldbook-entry-card-header, .app-modal-panel')]
    .filter((element) => element.clientWidth && element.scrollWidth > element.clientWidth + 1).map((element) => element.className || element.tagName));
  expect(overflow).toEqual([]);
}

async function modelId(request: APIRequestContext) {
  const models = await (await request.get('/api/models/profiles')).json();
  return models.find((model: { alias: string }) => model.alias === 'resource-embedding').id;
}

for (const locale of ['en', 'zh-CN']) for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
  test.describe(`resources ${locale} ${viewport.width}`, () => {
    test.use({ viewport, hasTouch: viewport.width === 390 });
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => localStorage.setItem('agent-workbench.locale', value), locale);
    });
    const l = labels(locale);

    test('worldbook card structure, independent drafts, toggles, ordering and match', async ({ page, request }, info) => {
      await page.goto('/settings?tab=worldbook');
      await page.getByRole('button', { name: l.addBook, exact: true }).click();
      await page.getByLabel(l.name, { exact: true }).fill(`World ${locale} ${viewport.width}`);
      const createdBook = page.waitForResponse((response) => response.url().endsWith('/api/worldbooks') && response.request().method() === 'POST');
      await page.getByRole('button', { name: l.save, exact: true }).click();
      const book = await (await createdBook).json();
      await expect(page.getByRole('tab', { name: l.entries, exact: true })).toHaveAttribute('aria-selected', 'true');
      const ids: string[] = [];
      for (const name of ['Alpha', 'Beta']) {
        await page.getByRole('button', { name: l.entry, exact: true }).click();
        const card = page.locator('[data-entry-id="new"]');
        await card.getByLabel(l.name, { exact: true }).fill(name);
        await card.getByLabel(l.keywords, { exact: true }).fill('alpha');
        await card.getByLabel(l.content, { exact: true }).fill(`${name} facts`);
        const created = page.waitForResponse((response) => response.url().endsWith('/entries') && response.request().method() === 'POST');
        await card.getByRole('button', { name: l.save, exact: true }).click();
        ids.push((await (await created).json()).id);
      }
      const first = page.locator(`[data-entry-id="${ids[0]}"]`), second = page.locator(`[data-entry-id="${ids[1]}"]`);
      expect(await first.locator('.worldbook-entry-card-header > *').evaluateAll((elements) => elements.map((element) => element.className))).toEqual([
        'drag-handle', 'icon-button resource-icon', 'worldbook-entry-toggle-cell', 'worldbook-entry-card-title', 'worldbook-entry-card-actions',
      ]);
      await first.getByLabel(l.content, { exact: true }).fill('Unsaved Alpha draft');
      await second.getByLabel(l.content, { exact: true }).fill('Updated Beta facts');
      await second.getByRole('button', { name: l.save, exact: true }).click();
      await expect(second.locator('.resource-badge.warning')).toHaveCount(0);
      await expect(first.getByLabel(l.content, { exact: true })).toHaveValue('Unsaved Alpha draft');
      const toggle = first.getByRole('switch');
      await toggle.click(); await expect(toggle).toHaveAttribute('aria-checked', 'false'); await expect(toggle).toBeEnabled();
      await expect(first.getByLabel(l.content, { exact: true })).toHaveValue('Unsaved Alpha draft');
      await page.route(`**/api/worldbook-entries/${ids[0]}`, async (route) => {
        if (route.request().method() === 'PATCH') await route.fulfill({ status: 422, json: { error: { code: 'TEST_TOGGLE', message: 'Toggle failed' } } }); else await route.continue();
      });
      await toggle.click(); await expect(first.getByRole('alert')).toContainText('Toggle failed');
      await expect(toggle).toHaveAttribute('aria-checked', 'false');
      await page.unroute(`**/api/worldbook-entries/${ids[0]}`);
      await first.getByRole('button', { name: l.reset, exact: true }).click();
      await expect(first.getByLabel(l.content, { exact: true })).toHaveValue('Alpha facts');
      await toggle.click(); await expect(toggle).toBeEnabled();
      await noOverflow(page); await first.screenshot({ path: info.outputPath('worldbook-expanded.png') });
      await first.getByRole('button', { name: l.collapse, exact: true }).click();
      await second.getByRole('button', { name: l.collapse, exact: true }).click();
      await second.locator('.drag-handle').focus(); await second.locator('.drag-handle').press('ArrowUp');
      await expect.poll(async () => (await (await request.get(`/api/worldbooks/${book.id}/entries`)).json())[0].id).toBe(ids[1]);
      const handle = second.locator('.drag-handle'); await handle.scrollIntoViewIfNeeded();
      const from = await handle.boundingBox(), to = await first.locator('header').boundingBox();
      await page.mouse.move(from!.x + 12, from!.y + 12); await page.mouse.down(); await page.mouse.move(to!.x + 100, to!.y + 12, { steps: 8 }); await page.mouse.up();
      await expect.poll(async () => (await (await request.get(`/api/worldbooks/${book.id}/entries`)).json())[0].id).toBe(ids[0]);
      if (viewport.width === 390) {
        const cdp = await page.context().newCDPSession(page);
        const source = await first.locator('.drag-handle').boundingBox(), target = await second.locator('header').boundingBox();
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: source!.x + 12, y: source!.y + 12 }] });
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: target!.x + 90, y: target!.y + 16 }] });
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
        await expect.poll(async () => (await (await request.get(`/api/worldbooks/${book.id}/entries`)).json())[0].id).toBe(ids[1]);
        const handle = await first.locator('.drag-handle').boundingBox(), top = await second.locator('header').boundingBox();
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: handle!.x + 12, y: handle!.y + 12 }] });
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: top!.x + 90, y: top!.y + 16 }] });
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
        await expect(page.locator('.worldbook-entry-card.dragging')).toHaveCount(0);
        expect((await (await request.get(`/api/worldbooks/${book.id}/entries`)).json())[0].id).toBe(ids[1]);
        await cdp.detach();
      }
      await noOverflow(page); await page.screenshot({ path: info.outputPath('worldbook-entries.png') });
      await page.getByRole('tab', { name: l.match, exact: true }).click();
      await page.getByLabel(l.matchText, { exact: true }).fill('alpha');
      await page.getByRole('button', { name: l.match, exact: true }).click();
      await expect(page.locator('.worldbook-match-entry-card')).toHaveCount(2);
      await page.getByRole('tab', { name: l.config, exact: true }).click();
      await page.getByLabel(l.name, { exact: true }).fill('Unsaved book');
      page.once('dialog', (dialog) => dialog.dismiss());
      await page.locator('.resource-heading').getByRole('button', { name: l.back, exact: true }).click();
      await expect(page.getByLabel(l.name, { exact: true })).toHaveValue('Unsaved book');
      page.once('dialog', (dialog) => dialog.accept());
      await page.locator('.resource-heading').getByRole('button', { name: l.back, exact: true }).click();
      await expect(page.getByRole('button', { name: l.addBook, exact: true })).toBeVisible();
      await page.getByRole('tab', { name: l.globals, exact: true }).click();
      await page.locator('.resource-advanced > summary').click();
      await page.getByLabel(l.maxContext, { exact: true }).fill(String(9000 + viewport.width));
      await page.getByRole('button', { name: l.save, exact: true }).click();
      await expect.poll(async () => (await (await request.get('/api/worldbook/settings')).json()).worldbook_max_context_chars).toBe(9000 + viewport.width);
      await noOverflow(page);
    });

    test('knowledge paste, upload partial retry, previews, rebuild and retrieval', async ({ page, request }, info) => {
      await page.goto('/settings?tab=knowledge');
      await page.getByRole('button', { name: l.addBase, exact: true }).click();
      await page.getByLabel(l.baseName, { exact: true }).fill(`Facts ${locale} ${viewport.width}`);
      await page.getByLabel(l.embedding, { exact: true }).selectOption(await modelId(request));
      const created = page.waitForResponse((response) => response.url().endsWith('/api/knowledge/bases') && response.request().method() === 'POST');
      await page.getByRole('button', { name: l.save, exact: true }).click();
      const base = await (await created).json();
      await page.getByRole('button', { name: l.paste, exact: true }).click();
      let dialog = page.getByRole('dialog');
      await dialog.getByLabel(l.sourceTitle, { exact: true }).fill('Alpha fact');
      await dialog.getByLabel(l.text, { exact: true }).fill('# Alpha\nUseful alpha fact.');
      await dialog.getByRole('button', { name: l.index, exact: true }).click();
      await expect(page.locator('.knowledge-source-preview')).toContainText('Useful alpha fact.');
      await page.locator('.knowledge-chunk summary').click();
      await expect(page.locator('.knowledge-chunk pre')).toContainText('Useful alpha fact.');
      await page.getByRole('dialog').getByRole('button', { name: l.close, exact: true }).click();
      await page.getByRole('button', { name: l.upload, exact: true }).click();
      dialog = page.getByRole('dialog');
      await dialog.locator('input[type=file]').setInputFiles([
        { name: 'first.txt', mimeType: 'text/plain', buffer: Buffer.from('first alpha file') },
        { name: 'second.md', mimeType: 'text/markdown', buffer: Buffer.from('# Second\nsecond alpha file') },
      ]);
      let fail = true;
      await page.route('**/api/knowledge/bases/*/sources', async (route) => {
        const body = route.request().method() === 'POST' ? route.request().postDataJSON() : null;
        if (fail && body?.title === 'second.md') { fail = false; await route.fulfill({ status: 400, json: { error: { code: 'MODEL_UNAVAILABLE', message: 'Temporary model failure' } } }); }
        else await route.continue();
      });
      await dialog.getByRole('button', { name: l.index, exact: true }).click();
      await expect(dialog).toContainText('Temporary model failure');
      await dialog.getByRole('button', { name: l.retry, exact: true }).click();
      await expect(dialog.getByRole('button', { name: l.index, exact: true })).toBeDisabled();
      const sources = await (await request.get(`/api/knowledge/bases/${base.id}/sources`)).json();
      expect(sources).toHaveLength(3); expect(sources.filter((source: { title: string }) => source.title === 'first.txt')).toHaveLength(1);
      await dialog.getByRole('button', { name: l.close, exact: true }).click();
      await expect(page.locator('.knowledge-source-preview')).toContainText('second alpha file');
      await noOverflow(page); await page.screenshot({ path: info.outputPath('knowledge-source.png') });
      await page.getByRole('dialog').getByRole('button', { name: l.close, exact: true }).click();
      await expect(page.locator('.knowledge-sources-table tbody tr')).toHaveCount(3);
      await noOverflow(page); await page.screenshot({ path: info.outputPath('knowledge-sources.png') });
      await page.getByRole('button', { name: locale === 'en' ? 'Rebuild all' : '全部重建', exact: true }).click();
      await expect(page.locator('.knowledge-sources > .resource-feedback')).toContainText(locale === 'en' ? 'Rebuilt: 3' : '重建成功：3');
      await page.getByRole('tab', { name: l.searchTab, exact: true }).click();
      await page.getByLabel(l.query, { exact: true }).fill('alpha');
      await page.getByRole('button', { name: l.search, exact: true }).click();
      await expect(page.locator('.knowledge-result')).toHaveCount(3);
      await noOverflow(page); await page.screenshot({ path: info.outputPath('knowledge-search.png') });
      const session = await (await request.post('/api/sessions', { data: {} })).json();
      expect((await request.patch(`/api/sessions/${session.session_id}/knowledge-bases`, { data: { knowledge_base_ids: [base.id] } })).ok()).toBeTruthy();
      const bindings = await (await request.get(`/api/sessions/${session.session_id}/knowledge-bases`)).json();
      expect(bindings.effective_knowledge_base_ids).toContain(base.id);
      await page.getByRole('tab', { name: locale === 'en' ? 'Sources' : '来源', exact: true }).click();
      const row = page.locator('.knowledge-sources-table tbody tr').filter({ hasText: 'first.txt' });
      page.once('dialog', (dialog) => dialog.accept());
      await row.getByRole('button', { name: locale === 'en' ? 'Delete' : '删除', exact: true }).click();
      await expect(page.locator('.knowledge-sources-table tbody tr')).toHaveCount(2);
    });
  });
}

test('stale source previews do not replace a new selection, and rejected uploads are cleaned', async ({ page, request }) => {
  const base = await (await request.post('/api/knowledge/bases', { data: { name: 'Race fixture', embedding_model_profile_id: await modelId(request) } })).json();
  const ids: string[] = [];
  for (const name of ['First', 'Second']) ids.push((await (await request.post(`/api/knowledge/bases/${base.id}/sources`, { data: { title: name, text: name + ' content' } })).json()).source_id);
  await page.addInitScript(() => localStorage.setItem('agent-workbench.locale', 'en'));
  await page.goto('/settings?tab=knowledge');
  await page.getByRole('button', { name: 'Manage Race fixture', exact: true }).click();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route(`**/api/knowledge/sources/${ids[0]}/preview`, async (route) => { await gate; await route.fulfill({ json: { source_id: ids[0], title: 'First', uri: '', content: 'Stale response', truncated: false } }); });
  const held = page.waitForRequest((request) => request.url().endsWith(`${ids[0]}/preview`));
  await page.getByRole('button', { name: 'First', exact: true }).click(); await held;
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: 'Second', exact: true }).click();
  await expect(page.locator('.knowledge-source-preview')).toContainText('Second content');
  const completed = page.waitForResponse((response) => response.url().endsWith(`${ids[0]}/preview`)); release(); await completed;
  await expect(page.locator('.knowledge-source-preview')).toHaveText('Second content');
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: 'Upload files', exact: true }).click();
  await page.getByRole('dialog').locator('input[type=file]').setInputFiles({ name: 'bad.txt', mimeType: 'text/plain', buffer: Buffer.from([255, 254]) });
  const uploaded = page.waitForResponse((response) => response.url().endsWith('/api/attachments') && response.request().method() === 'POST');
  await page.getByRole('dialog').getByRole('button', { name: 'Add and index', exact: true }).click();
  const attachment = await (await uploaded).json();
  await expect(page.getByRole('dialog')).toContainText('KNOWLEDGE_SOURCE_NOT_READABLE');
  const attachmentId = attachment.uri.split('/').at(-1);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await expect.poll(async () => (await request.get(`/api/attachments/${attachmentId}`)).status()).toBe(404);
});

test('advanced settings retain nullable fields and invalid drafts block departure', async ({ page, request }) => {
  await page.addInitScript(() => localStorage.setItem('agent-workbench.locale', 'en'));
  await page.goto('/settings?tab=knowledge');
  await page.getByRole('tab', { name: 'Global settings', exact: true }).click();
  const advanced = page.locator('.resource-advanced'); await advanced.locator(':scope > summary').click();
  await page.getByLabel('Score threshold', { exact: true }).fill('0.25');
  await page.getByLabel('Default score threshold', { exact: true }).fill('0.1');
  await page.getByLabel('Results per source', { exact: true }).fill('');
  await page.getByRole('switch', { name: 'Enable optional reranker', exact: true }).click();
  await advanced.locator(':scope > summary').click();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
  const settings = await (await request.get('/api/knowledge/settings')).json();
  expect(settings.min_score_threshold).toBe(0.25); expect(settings.default_min_score).toBe(0.1); expect(settings.retrieval_max_chunks_per_source).toBeNull();
  await page.getByLabel('Chunk size', { exact: true }).fill('');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('navigation').getByRole('button', { name: 'General', exact: true }).click();
  await expect(page.getByLabel('Chunk size', { exact: true })).toHaveValue('');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  expect((await (await request.get('/api/knowledge/settings')).json()).default_chunk_size).toBe(settings.default_chunk_size);
  await page.getByLabel('Chunk size', { exact: true }).fill(String(settings.default_chunk_size));
  await request.patch('/api/knowledge/settings', { data: { reranker_enabled: false, min_score_threshold: null, default_min_score: null } });
});

test('managed resources bind through Persona and session editors and enter chat context', async ({ page, request }) => {
  const book = await (await request.post('/api/worldbooks', { data: { name: 'Binding worldbook' } })).json();
  await request.post(`/api/worldbooks/${book.id}/entries`, { data: { name: 'Alpha', keywords_text: 'alpha', content: 'Worldbook alpha context' } });
  const bases = [];
  for (const name of ['Binding facts', 'Session extra facts']) {
    const base = await (await request.post('/api/knowledge/bases', { data: { name, embedding_model_profile_id: await modelId(request) } })).json();
    await request.post(`/api/knowledge/bases/${base.id}/sources`, { data: { title: name, text: name + ' alpha context' } });
    bases.push(base);
  }
  await page.addInitScript(() => localStorage.setItem('agent-workbench.locale', 'en'));
  await page.goto('/settings?tab=personas');
  await page.getByRole('button', { name: 'Add persona', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name', { exact: true }).fill('Resource binding persona');
  await dialog.getByRole('tab', { name: 'Knowledge', exact: true }).click();
  await dialog.getByRole('checkbox', { name: 'Binding facts', exact: true }).check();
  await dialog.getByRole('tab', { name: 'Worldbook', exact: true }).click();
  await dialog.getByRole('checkbox', { name: 'Binding worldbook', exact: true }).check();
  const created = page.waitForResponse((response) => response.url().endsWith('/api/personas') && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  const persona = await (await created).json();
  await expect(dialog).toHaveCount(0);
  const session = await (await request.post('/api/sessions', { data: { title: 'Resource binding workflow', current_persona_id: persona.id, personas: [{ persona_id: persona.id, enabled: true }] } })).json();
  await page.goto('/');
  await page.locator('.session-select').filter({ hasText: 'Resource binding workflow' }).click();
  await page.getByRole('button', { name: 'Session settings', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByRole('tab', { name: 'Knowledge', exact: true }).click();
  await expect(dialog.getByRole('checkbox', { name: 'Binding facts', exact: true })).toBeChecked();
  await expect(dialog.getByRole('checkbox', { name: 'Binding facts', exact: true })).toBeDisabled();
  await dialog.getByRole('checkbox', { name: 'Session extra facts', exact: true }).check();
  await dialog.getByRole('tab', { name: 'Worldbook', exact: true }).click();
  await expect(dialog.getByRole('checkbox', { name: 'Binding worldbook', exact: true })).toBeChecked();
  await expect(dialog.getByRole('checkbox', { name: 'Binding worldbook', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const bindings = await (await request.get(`/api/sessions/${session.session_id}/knowledge-bases`)).json();
  expect(bindings.knowledge_base_ids).toEqual([bases[1].id]);
  expect(bindings.effective_knowledge_base_ids).toEqual(bases.map((base) => base.id));
  await page.locator('.composer textarea').fill('alpha');
  const sent = page.waitForResponse((response) => response.url().endsWith('/messages') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  const result = await (await sent).json();
  const steps = await (await request.get(`/api/runs/${result.run.run_id}/steps`)).json();
  const context = steps.find((step: { kind: string }) => step.kind === 'context').metadata;
  expect(context.knowledge.injected).toBe(true); expect(context.knowledge.knowledge_base_ids).toEqual(bases.map((base) => base.id));
  expect(context.worldbook.injected).toBe(true); expect(context.worldbook.worldbook_ids).toEqual([book.id]);
});
