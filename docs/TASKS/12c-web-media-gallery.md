# Task 12c — Web UI: device media gallery

🟢 **Status: Implemented (2026-02-21)**

## Objective

Add a production-grade **media gallery** to the device detail view:

- show latest capture per camera
- open full-res assets
- show capture time + reason

This task assumes Task 12b shipped the API/storage lane.

## Scope

### In-scope

- Add a “Media” tab to device detail:
  - camera filter (`cam1..cam4`)
  - grid of latest items
  - empty states when no media exists

- Media objects should load efficiently:
  - one list call per device
  - signed URLs should not be cached forever

- UX polish:
  - skeleton loading
  - error toasts
  - “Copied link” for sharing within operator perimeter

### Out-of-scope

- Video playback (can be added after photo lane is stable).

## Acceptance criteria

- When media exists, gallery shows items with:
  - thumbnail/preview
  - timestamp
  - reason
- Clicking opens a modal or a new tab with the asset.
- Works in:
  - local dev (filesystem storage)
  - Cloud Run demo/prod (GCS storage)

## Deliverables

- `web/src/pages/DeviceDetail/*` updates
- `web/src/api.ts` endpoints added
- `docs/WEB_UI.md` updated

## Validation

```bash
pnpm -r --if-present build
pnpm -C web typecheck
make test
```
