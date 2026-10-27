import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { createModuleLoader } from '../scripts/module-loader.mjs';

const load = createModuleLoader();
const { FarkleHud } = (await load('@/components/playground/farkle/FarkleHud')).exports;
const { initialGame } = (await load('@/components/playground/farkle/state')).exports;
const template = readFileSync(new URL('../dist/index.html', import.meta.url), 'utf8')
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '');

for (const locale of ['en', 'zh-CN']) for (const viewport of [
  { width: 1366, height: 900 }, { width: 768, height: 900 },
  { width: 390, height: 844 }, { width: 320, height: 740 }, { width: 844, height: 390 },
]) {
  const touch = viewport.width < 768 || viewport.height < 440;
  test.describe(`Farkle HUD ${locale} ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport, hasTouch: touch });
    test('scores and Round/Selected labels fit their columns; longer scores can wrap', async ({ page }, testInfo) => {
      const common = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/common.json`, import.meta.url), 'utf8'));
      const i18n = createInstance();
      await i18n.init({ lng: locale, resources: { [locale]: { common } } });
      // Render the real HUD with production CSS, covering both banked totals and
      // accumulated rounds without playing hundreds of artificial turns.
      await page.route('**/__test__/farkle-hud?*', (route) => {
        const value = Number(new URL(route.request().url()).searchParams.get('score'));
        const state = { ...initialGame, target: value, totals: { A: value, B: value }, rounds: { A: value, B: value },
          dice: ['A', 'B'].flatMap((player) => Array.from({ length: 6 }, (_, index) => ({
            id: `${player}${index}`, player, index, type: 'normal', value: 1, status: 'selected',
          }))) };
        const hud = React.createElement(FarkleHud, { state, disabled: false, onHold() {}, onStore() {}, onPass() {} });
        const content = renderToStaticMarkup(React.createElement(I18nextProvider, { i18n },
          React.createElement('main', { className: 'farkle-table', style: {
            position: 'relative', marginLeft: touch ? 0 : 256, height: '100dvh', background: '#173327',
          } }, hud)));
        return route.fulfill({ contentType: 'text/html; charset=utf-8', body: template.replace('<div id="root"></div>', content) });
      });
      for (const value of [1500, 9999, 10000, 99999, 100000, 999999, 1000000, Number.MAX_SAFE_INTEGER - 1]) {
        await page.goto(`/__test__/farkle-hud?score=${value}`);
        await page.evaluate(() => document.fonts.ready);
        const actual = await page.locator('.farkle-score').evaluate((score) => {
          const cells = [...score.querySelectorAll('[data-wrap], .farkle-score-goal > div:nth-child(n+3)')];
          return {
            numbers: cells.map((cell) => {
              const range = document.createRange(); range.selectNodeContents(cell);
              return { text: cell.textContent, lines: range.getClientRects().length,
                selected: cell.getAttribute('data-score')?.endsWith('-selected'), label: cell.classList.contains('farkle-score-label'),
                left: range.getBoundingClientRect().left, boxLeft: cell.getBoundingClientRect().left,
                right: range.getBoundingClientRect().right, boxRight: cell.getBoundingClientRect().right,
                wrap: getComputedStyle(cell).whiteSpace };
            }),
            right: Math.max(...[...score.querySelectorAll('div')].map((node) => node.getBoundingClientRect().right)),
            actionsLeft: document.querySelector('.farkle-actions')!.getBoundingClientRect().left,
            overflow: document.documentElement.scrollWidth > innerWidth,
          };
        });
        expect(actual.numbers).toHaveLength(9);
        for (const cell of actual.numbers) {
          if (cell.label) expect([common.farkle.round, common.farkle.selected]).toContain(cell.text);
          else expect(cell.text).toBe(cell.selected ? '8000' : String(value));
          expect(cell.left).toBeGreaterThanOrEqual(cell.boxLeft - 1);
          expect(cell.right).toBeLessThanOrEqual(cell.boxRight + 1);
          if (cell.label || cell.selected || value < 1_000_000) expect(cell.lines).toBe(1);
          else expect(cell.wrap).not.toBe('nowrap');
        }
        expect(actual.right).toBeLessThanOrEqual(actual.actionsLeft);
        expect(actual.overflow).toBe(false);
        if (value === 1500) await page.screenshot({ path: testInfo.outputPath('four-digit-selected-hud.png') });
        if (value === 999999) await page.screenshot({ path: testInfo.outputPath('six-digit-hud.png') });
      }
    });
  });
}
