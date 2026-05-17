# Frontend UI Components

Use the lightweight primitives in `frontend/src/components/ui` before adding one-off UI for common workbench surfaces.

- `AppModal`: centered modal panels rendered through a body portal. Use for app-level centered dialogs, especially chat and settings modals that must not be clipped by parent layout.
- `SettingsDetailHeader`: settings object detail headers with icon, title, subtitle, and right-aligned actions.
- `StatusDot`: small status indicators for compact buttons and rows. It should not be stretched by flex layouts.
- `ToggleSwitch` and `MiniToggle`: standard toggles. Use `MiniToggle` in dense row headers such as Worldbook entries.
- `EmptyStateRow`: empty state text with an optional right-aligned action button.
- `Chip` / `StatusChip`: lightweight state labels for activation modes, dirty state, warnings, and similar metadata.
- `DragHandle`: consistent drag affordance for reorderable cards and rows.
- `InlineStatus`: short inline save/error/warning feedback near the object it describes.

Current expected reuse points:

- Chat Context Sources uses `AppModal`, `StatusDot`, and `EmptyStateRow`.
- Settings object pages should use `SettingsDetailHeader`.
- Worldbook entry cards should use `DragHandle`, `MiniToggle`, `Chip` / `StatusChip`, and `InlineStatus`.
- Chat message output renders `message.parts` first through
  `frontend/src/components/messages/MessagePartsRenderer.tsx`. There is no
  legacy visible message fallback; copy, renderability, forms, and command
  buttons all read `Message.parts[]`.
- Audio message parts render through
  `frontend/src/components/messages/parts/AudioPartRenderer.tsx` with a custom
  project-styled player backed by a hidden `<audio>` element without native
  controls. It accepts local attachment-backed URLs for `source: attachment`
  and HTTP/HTTPS direct audio URLs for `source: url`; it does not autoplay,
  expose download controls, execute HTML/JS, proxy media, or repair remote
  server playback restrictions.
- Video message parts render through
  `frontend/src/components/messages/parts/VideoPartRenderer.tsx` with native
  `<video controls preload="metadata">`. It accepts local attachment-backed
  URLs for `source: attachment` and HTTP/HTTPS direct video URLs for
  `source: url`, does not autoplay, does not proxy/cache/download remote media,
  and does not implement custom playback controls.
