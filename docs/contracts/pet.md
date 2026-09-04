# Pet contract

Pet is an optional presentation service. It is independent from chat routing
and model execution; no command or model call is required to operate it.

## Settings

`AppSettings.pet` has exactly these groups:

- `pet_enabled`, `default_pet_id`, `pet_scale` (0.5–2),
  `show_status_bubble`, `bubble_offset_x/y`, `jump_on_hover`, and
  `running_prefix`;
- `position`: `mode` (`default` or `custom`) with optional `x`/`y`;
- `bubble_texts`: idle, waiting, done, failed, cancelled, interrupted, wake,
  tuck, status, select, reload, no_pet, import_success/import_failed, and
  delete_success/delete_failed.

`command_texts` and other top-level Pet fields are invalid. `PATCH
/api/pets/settings` accepts `{ "values": Partial[PetSettings] }`, validates
strictly, deep-merges the two nested objects, and persists through
`AppSettingsStore`. `GET` returns `{ "settings": PetSettings }`.

## Pet lifecycle API

`/api/pets` lists installed packages; `/scan` refreshes discovery; `/import`
accepts exactly `pet.json` and `spritesheet.webp`; `DELETE /{pet_id}` removes a
package; `GET /{pet_id}/spritesheet.webp` serves its asset. Errors use ordinary
HTTP 4xx responses with structured codes.

## Overlay behavior

The overlay loads settings and pet list at initialization and refreshes after a
change event. It derives sprite and bubble states from run status and the
active `RunStep.kind`: `approval` or `WAITING_FOR_USER` means waiting for user
confirmation; pending/running uses the configured running prefix; terminal
states map to done, failed, cancelled, or interrupted text. It does not match
implementation-specific progress strings.
