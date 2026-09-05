# Model status and inventory contract

Status and inventory reads never load weights, import heavy runtimes or
download models. All paths belong to `/api/models`.

| Operation | Endpoint | Effect |
| --- | --- | --- |
| Cached status | GET `/profiles/{id}/status` | No provider call |
| Health | POST `/profiles/{id}/health` | Explicit provider/model check |
| Load | POST `/profiles/{id}/load` | Manager load operation |
| Unload | POST `/profiles/{id}/unload` | Manager release operation |
| Connection models | GET `/providers/{id}/models` | Queued upstream GET models |
| Local files | GET `/inventory?kind=...` | Read-only relative refs |

Status contains `state` (unknown, ready, unavailable, failed, unloaded),
`residency` (unknown, loaded, unloaded), `unload_supported`,
`active`, `queued`, and optional `error_code`. Unchecked connections are
unknown. A disabled model/connection or absent connection is unavailable.
A reachable provider must advertise the exact model_ref to pass health/load.

OpenAI-compatible connections do not expose process residency or unload.
Successful health therefore means ready with unknown residency; unload
returns `UNLOAD_UNSUPPORTED`. The UI disables unavailable controls and gives
the reason. Backend/kind failures return structured errors rather than
pretending weights are loaded.

The manager broadcasts `model_status` with an empty session_id and
`{model_profile_id, status}` to every session WebSocket. All aliases of the
same connection/model receive matching occupancy snapshots as requests queue,
start and finish. Status events do not create business rows.

`GET /api/runtime/resources` retains the cached CPU/RAM/GPU snapshot.
Runtime-wide free-memory endpoints and old per-kind diagnostics are deleted.
Managed process installation and status actions belong to Phase 2b.
