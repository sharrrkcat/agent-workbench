import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createModuleLoader } from '../scripts/module-loader.mjs';

const { Button } = (await createModuleLoader()('@/components/ui/button')).exports;
const template = readFileSync(new URL('../dist/index.html', import.meta.url), 'utf8')
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '');

function fixtureDocument(locale: string) {
  const common = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/common.json`, import.meta.url), 'utf8'));
  const content = renderToStaticMarkup(
    React.createElement('main', { style: { padding: 24 } },
      React.createElement('h1', null, common.appName),
      React.createElement('p', { id: 'latin' }, 'Inter: ABC abc 0123456789'),
      React.createElement('p', { id: 'cjk' }, '中文字体：设置、保存、返回'),
      React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 16 } },
        React.createElement(Button, { id: 'default' }, common.save),
        React.createElement(Button, { id: 'disabled', disabled: true }, common.cancel),
        React.createElement(Button, {
          id: 'override', className: 'h-8 px-2.5 bg-secondary text-secondary-foreground',
        }, common.back),
      ),
    ),
  );
  return template.replace('lang="en"', `lang="${locale}"`).replace('<div id="root"></div>', content);
}

for (const locale of ['en', 'zh-CN']) {
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`${locale} ${viewport.width}x${viewport.height}`, () => {
      test.use({ viewport, colorScheme: 'light' });

      test('Mira Button, fixed dark theme and bundled fonts', async ({ page, baseURL }, info) => {
        const requests: string[] = [];
        const fonts: Array<{ url: string; status: number }> = [];
        page.on('request', (request) => requests.push(request.url()));
        page.on('response', (response) => {
          if (response.request().resourceType() === 'font') fonts.push({ url: response.url(), status: response.status() });
        });
        // Intercept only this test document; production CSS/fonts use the existing fixture server.
        await page.route('**/__test__/style-foundation', (route) =>
          route.fulfill({ contentType: 'text/html; charset=utf-8', body: fixtureDocument(locale) }));
        await page.goto('/__test__/style-foundation');
        await page.evaluate(() => document.fonts.ready);

        await expect(page.locator('html')).toHaveAttribute('class', 'dark');
        await expect(page.locator('html')).toHaveAttribute('lang', locale);
        await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark');
        await expect(page.locator('body')).toHaveCSS('background-color', 'oklch(0.145 0 0)');
        await expect(page.locator('body')).toHaveCSS('color', 'oklch(0.985 0 0)');
        const button = page.locator('#default');
        await expect(button).toHaveAttribute('data-slot', 'button');
        await expect(button).toHaveCSS('height', '28px');
        await expect(button).toHaveCSS('font-size', '12px');
        await expect(button).toHaveCSS('background-color', 'oklch(0.922 0 0)');
        await expect(button).toHaveCSS('color', 'oklch(0.205 0 0)');
        await expect(page.locator('#disabled')).toBeDisabled();
        await expect(page.locator('#disabled')).toHaveCSS('opacity', '0.5');
        await expect(page.locator('#disabled')).toHaveCSS('pointer-events', 'none');
        await expect(page.locator('#override')).toHaveCSS('height', '32px');
        await expect(page.locator('#override')).toHaveCSS('padding-left', '10px');
        await expect(page.locator('#override')).toHaveCSS('background-color', 'oklch(0.269 0 0)');
        await expect(page.locator('#override')).toHaveCSS('color', 'oklch(0.985 0 0)');

        await page.keyboard.press('Tab');
        await expect(button).toBeFocused();
        await expect(button).toHaveCSS('border-top-color', 'oklch(0.556 0 0)');
        await expect(button).not.toHaveCSS('box-shadow', 'none');
        await page.keyboard.press('Tab');
        await expect(page.locator('#override')).toBeFocused();

        const family = await page.locator('body').evaluate((element) => getComputedStyle(element).fontFamily);
        expect(family).toContain('Inter Variable');
        await expect(page.locator('h1')).toHaveCSS('font-family', family);
        await expect(button).toHaveCSS('font-family', family);
        expect(fonts.length).toBeGreaterThan(0);
        for (const font of fonts) {
          expect(new URL(font.url).origin).toBe(new URL(baseURL!).origin);
          expect(new URL(font.url).pathname).toMatch(/^\/assets\/inter-.*\.woff2$/);
          expect(font.status).toBe(200);
        }
        expect(requests.every((url) => new URL(url).origin === new URL(baseURL!).origin)).toBe(true);

        const cdp = await page.context().newCDPSession(page);
        await cdp.send('DOM.enable');
        await cdp.send('CSS.enable');
        const { root } = await cdp.send('DOM.getDocument');
        const latin = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: '#latin' });
        const cjk = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: '#cjk' });
        const latinFonts = (await cdp.send('CSS.getPlatformFontsForNode', { nodeId: latin.nodeId })).fonts;
        const cjkFonts = (await cdp.send('CSS.getPlatformFontsForNode', { nodeId: cjk.nodeId })).fonts;
        expect(latinFonts.some((font) => font.isCustomFont && /Inter/.test(font.familyName) && font.glyphCount > 0)).toBe(true);
        expect(cjkFonts.some((font) => !font.isCustomFont && font.glyphCount > 0)).toBe(true);
        await cdp.detach();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await info.attach('fonts', { body: JSON.stringify({ fonts, latinFonts, cjkFonts }), contentType: 'application/json' });
        await page.screenshot({ path: info.outputPath('foundation.png') });
      });
    });
  }
}
