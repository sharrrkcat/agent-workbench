import { expect, type Locator, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import type { ModelView } from '../src/components/settings/navigation';

export async function openSidebar(page: Page) {
  const trigger = page.locator('[data-sidebar="trigger"]');
  await expect(trigger).toBeVisible();
  if ((await trigger.getAttribute('aria-expanded')) === 'false') await trigger.click();
  await expect(page.locator('.session-sidebar, .settings-sidebar')).toBeInViewport();
}

export async function navigateSettings(page: Page, section: string, name = section, group?: string) {
  await openSidebar(page);
  const menu = page.locator('.settings-sidebar nav').getByRole('list', { name: group ? `${section} / ${group}` : section, exact: true });
  const toggle = menu.locator('[data-settings-menu]');
  if ((await toggle.count()) && (await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
  await menu.getByRole('button', { name, exact: true }).click();
}

export async function navigateModelSettings(page: Page, view: ModelView) {
  const locale = await page.evaluate(() => localStorage.getItem('cogita.locale') || 'en');
  const read = (namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
  const settings = read('settings'), llm = read('llm');
  const infrastructure = view === 'providers' || view === 'localRuntime';
  await navigateSettings(page, infrastructure ? settings.providersRuntime : settings.models,
    view === 'dashboard' || infrastructure ? llm[view] : llm.kinds[view]);
}

export async function backToChat(page: Page) {
  await openSidebar(page);
  await page.locator('.settings-sidebar [data-slot="sidebar-footer"] button').click();
}

export async function chooseOption(trigger: Locator, name: string) {
  await trigger.click();
  await trigger.page().getByRole('option', { name, exact: true }).click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
}

export async function fillCombobox(input: Locator, value: string) {
  await input.fill(value);
  await input.press('Tab');
  await expect(input).toHaveAttribute('aria-expanded', 'false');
  await expect(input).toHaveValue(value);
}

export async function answerConfirmation(page: Page, accept: boolean, locale = 'en') {
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toBeVisible();
  const name = accept ? (locale === 'en' ? 'Confirm' : '确认') : locale === 'en' ? 'Cancel' : '取消';
  await dialog.getByRole('button', { name, exact: true }).click();
  await expect(dialog).toBeHidden();
}
