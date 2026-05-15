import { joinApiUrl, API_BASE_URL } from '../api/client';
import type { FontAsset, GeneralSettings } from '../types';

export const DEFAULT_UI_FONT = 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
export const DEFAULT_MESSAGE_FONT = DEFAULT_UI_FONT;
export const DEFAULT_CODE_FONT = 'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace';

const STYLE_ID = 'aw-local-font-faces';

export function applyAppearanceFonts(settings?: GeneralSettings | null, fonts: FontAsset[] = []): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const selected = {
    ui: fontFamilyFor(settings?.appearance_font_ui_family || DEFAULT_UI_FONT, settings?.appearance_font_ui_custom_id || null, fonts),
    message: fontFamilyFor(settings?.appearance_font_message_family || DEFAULT_MESSAGE_FONT, settings?.appearance_font_message_custom_id || null, fonts),
    code: fontFamilyFor(settings?.appearance_font_code_family || DEFAULT_CODE_FONT, settings?.appearance_font_code_custom_id || null, fonts),
  };
  root.style.setProperty('--aw-font-ui', selected.ui);
  root.style.setProperty('--aw-font-message', selected.message);
  root.style.setProperty('--aw-font-code', selected.code);
  updateFontFaceStyle(
    [
      settings?.appearance_font_ui_custom_id || null,
      settings?.appearance_font_message_custom_id || null,
      settings?.appearance_font_code_custom_id || null,
    ],
    fonts,
  );
}

export function fontFamilyFor(systemFamily: string, customId: string | null, fonts: FontAsset[]): string {
  const custom = customId ? fonts.find((font) => font.id === customId) : undefined;
  return custom ? quoteFontFamily(custom.css_family) : systemFamily;
}

function updateFontFaceStyle(customIds: (string | null)[], fonts: FontAsset[]): void {
  const selected = fonts.filter((font) => customIds.includes(font.id));
  let style = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
  if (!selected.length) {
    style?.remove();
    return;
  }
  if (!style) {
    style = document.createElement('style');
    style.id = STYLE_ID;
    document.head.appendChild(style);
  }
  style.textContent = selected
    .map((font) => `@font-face { font-family: ${quoteFontFamily(font.css_family)}; src: url("${joinApiUrl(API_BASE_URL, font.url)}"); font-display: swap; }`)
    .join('\n');
}

function quoteFontFamily(value: string): string {
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}
