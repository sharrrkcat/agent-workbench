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
  `frontend/src/components/messages/MessagePartsRenderer.tsx`. Legacy
  `content` / `output_type` / `rich_content.blocks` rendering is deprecated
  no-parts fallback only.
