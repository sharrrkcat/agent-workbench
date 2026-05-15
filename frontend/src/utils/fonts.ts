import { joinApiUrl, API_BASE_URL } from '../api/client';
import type { FontAsset, FontFamilyAsset, FontFamilyFace, GeneralSettings } from '../types';

export const DEFAULT_UI_FONT = 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
export const DEFAULT_MESSAGE_FONT = DEFAULT_UI_FONT;
export const DEFAULT_CODE_FONT = 'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace';
export const DEFAULT_UI_FONT_NAME = 'Inter';
export const DEFAULT_MESSAGE_FONT_NAME = 'Inter';
export const DEFAULT_CODE_FONT_NAME = 'ui-monospace';

const STYLE_ID = 'aw-local-font-faces';

export function applyAppearanceFonts(settings?: GeneralSettings | null, fonts: FontAsset[] = [], families: FontFamilyAsset[] = []): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const selected = {
    ui: fontFamilyFor('ui', settings, fonts, families),
    message: fontFamilyFor('message', settings, fonts, families),
    code: fontFamilyFor('code', settings, fonts, families),
  };
  root.style.setProperty('--aw-font-ui-fallback', fallbackStackFor(settings?.appearance_font_ui_family || DEFAULT_UI_FONT, 'ui'));
  root.style.setProperty('--aw-font-message-fallback', fallbackStackFor(settings?.appearance_font_message_family || DEFAULT_MESSAGE_FONT, 'message'));
  root.style.setProperty('--aw-font-code-fallback', fallbackStackFor(settings?.appearance_font_code_family || DEFAULT_CODE_FONT, 'code'));
  root.style.setProperty('--aw-font-ui', selected.ui);
  root.style.setProperty('--aw-font-message', selected.message);
  root.style.setProperty('--aw-font-code', selected.code);
  updateFontFaceStyle(
    [
      settings?.appearance_font_ui_custom_id || null,
      settings?.appearance_font_message_custom_id || null,
      settings?.appearance_font_code_custom_id || null,
    ],
    [
      settings?.appearance_font_ui_custom_family_id || null,
      settings?.appearance_font_message_custom_family_id || null,
      settings?.appearance_font_code_custom_family_id || null,
    ],
    fonts,
    families,
  );
}

export function fontFamilyFor(kind: 'ui' | 'message' | 'code', settings: GeneralSettings | null | undefined, fonts: FontAsset[], families: FontFamilyAsset[]): string {
  const fallback = `var(--aw-font-${kind}-fallback)`;
  if (!settings) {
    const defaultName = kind === 'code' ? DEFAULT_CODE_FONT_NAME : DEFAULT_UI_FONT_NAME;
    return `${quoteFontFamily(defaultName)}, ${fallback}`;
  }
  const source = settings[`appearance_font_${kind}_source`];
  if (source === 'custom_file') {
    const custom = fonts.find((font) => font.id === settings[`appearance_font_${kind}_custom_id`]);
    return custom ? `${quoteFontFamily(custom.css_family)}, ${fallback}` : `${quoteFontFamily(settings[`appearance_font_${kind}_system_name`])}, ${fallback}`;
  }
  if (source === 'custom_family') {
    const customFamily = families.find((family) => family.id === settings[`appearance_font_${kind}_custom_family_id`]);
    return customFamily ? `${quoteFontFamily(customFamily.css_family)}, ${fallback}` : `${quoteFontFamily(settings[`appearance_font_${kind}_system_name`])}, ${fallback}`;
  }
  const systemName = settings[`appearance_font_${kind}_system_name`] || firstFamily(settings[`appearance_font_${kind}_family`]);
  return `${quoteFontFamily(systemName)}, ${fallback}`;
}

export function shortFontName(family: string, fallback: string): string {
  const first = firstFamily(family);
  return first || fallback;
}

function updateFontFaceStyle(customIds: (string | null)[], customFamilyIds: (string | null)[], fonts: FontAsset[], families: FontFamilyAsset[]): void {
  const selected = fonts.filter((font) => customIds.includes(font.id));
  const selectedFamilies = families.filter((family) => customFamilyIds.includes(family.id));
  let style = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
  if (!selected.length && !selectedFamilies.length) {
    style?.remove();
    return;
  }
  if (!style) {
    style = document.createElement('style');
    style.id = STYLE_ID;
    document.head.appendChild(style);
  }
  style.textContent = [
    ...selected.map((font) => `@font-face { font-family: ${quoteFontFamily(font.css_family)}; src: url("${joinApiUrl(API_BASE_URL, font.url)}"); font-display: swap; }`),
    ...selectedFamilies.flatMap((family) => family.faces.map((face) => fontFaceRule(family, face))),
  ]
    .join('\n');
}

function fontFaceRule(family: FontFamilyAsset, face: FontFamilyFace): string {
  return `@font-face { font-family: ${quoteFontFamily(family.css_family)}; src: url("${joinApiUrl(API_BASE_URL, face.url)}"); font-weight: ${face.registered_weight || face.weight}; font-style: ${face.style}; font-display: swap; }`;
}

export function quoteFontFamily(value: string): string {
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

function firstFamily(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  const [first] = trimmed.match(/"([^"\\]|\\.)*"|'([^'\\]|\\.)*'|[^,]+/) || [''];
  return first.trim().replace(/^["']|["']$/g, '');
}

function fallbackStackFor(value: string, kind: 'ui' | 'message' | 'code'): string {
  const match = value.match(/"([^"\\]|\\.)*"|'([^'\\]|\\.)*'|[^,]+/);
  const tail = match ? value.slice(match[0].length).replace(/^,\s*/, '').trim() : '';
  if (tail) return tail;
  if (kind === 'code') return 'SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace';
  return 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
}
