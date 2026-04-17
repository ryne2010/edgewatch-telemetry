# Change Summary

## OTA governance operator UX (2026-04-17)

### What changed

- Added direct per-device OTA governance controls to the device detail page:
  - rollout channel
  - updates enabled / disabled
  - busy reason
  - development-device posture
  - manifest lock selection from known release manifests
- Added fleet-level OTA governance controls to the fleets page:
  - edit a fleet default OTA channel
  - apply the fleet channel to all current fleet members
- Fixed the admin device patch route so explicitly-sent `null` values can clear:
  - `ota_busy_reason`
  - `ota_locked_manifest_id`
- Added regression coverage for clearing those OTA governance fields through the admin route.

### Why it changed

- The earlier backend/platform work exposed OTA governance and channel concepts, but operators still had to use raw admin forms or APIs to act on them.
- Particle-style parity requires these controls to be directly operable from the day-to-day device and fleet workflows, not just technically present.
- Clearing busy/lock fields is part of real rollback and recovery work; treating `null` as “field absent” made the UI incomplete.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Fleet “apply channel to fleet devices” currently performs per-device admin updates from the UI; it is operationally useful now, but a dedicated bulk backend endpoint would scale better for very large fleets.
- Fleet default-channel edits change the governance default immediately, but channel application to existing devices remains an explicit operator step by design.

## Cellular cost-cap operator workflow (2026-04-17)

### What changed

- Expanded the cellular operator page with a writable cost-cap policy section.
- Added live display of the current shared edge-policy cost caps for:
  - daily bytes
  - daily media uploads
  - daily snapshots
- Added operator controls on the cellular page for:
  - conservative / balanced / aggressive presets
  - direct editing of the three cap values
  - saving those values through the existing edge-policy YAML contract path
- Kept the existing fleet-health cellular table and focus filters intact while making the page actionable.

### Why it changed

- The approved Particle-parity plan still had a gap around broader cellular quota and cost workflows.
- Operators diagnosing cap-triggered throttling should be able to inspect and change the shared cellular budget posture from the same page, not bounce between diagnosis and a separate settings editor.
- Reusing the existing edge-policy contract update path keeps cellular policy edits on the canonical configuration surface instead of introducing a second backend contract.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Cellular cost-cap edits still operate on the shared global edge policy, not per-fleet or per-device policy overlays.
- The page now makes quota editing easier, but it does not yet add historical cost analytics, per-SIM billing data, or carrier-specific control integrations.

## Release rollout discovery UX (2026-04-17)

### What changed

- Added an admin deployment listing route:
  - `GET /api/v1/admin/deployments`
  - supports filtering by `status`, `manifest_id`, and `selector_channel`
- Added backend support for listing deployments with manifest preload and current target counts.
- Added Admin UI support for:
  - manifest status filtering
  - recent deployment filtering by status and channel
  - clicking a recent deployment row to load the existing detailed deployment inspector
- Added regression coverage for channel-filtered deployment listing.
- Updated the OTA runbook to include the new deployment discovery path.

### Why it changed

- Operators previously needed a deployment UUID ahead of time to inspect rollout state, which made release operations too dependent on external copy/paste and admin-event spelunking.
- Particle-style parity expects rollout operations to be discoverable and inspectable from the console itself, not only through direct object lookup.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Deployment listing currently computes per-row target counts on read, which is acceptable now but could need optimization for very large rollout histories.
- Release promotion is still represented through manifest status and channel-targeted deployments rather than a richer first-class promotion workflow.

## Manifest promotion controls (2026-04-17)

### What changed

- Added a narrow release-manifest update route:
  - `PATCH /api/v1/admin/releases/manifests/{manifest_id}`
  - currently supports status transitions through the admin API
- Added regression coverage for manifest status updates.
- Added Admin UI manifest actions for:
  - `Draft`
  - `Promote`
  - `Retire`
- Updated the OTA runbook to document first-class manifest promotion / retirement.

### Why it changed

- Release promotion was still too implicit and form-driven even after the deployment discovery work.
- Operators needed a direct way to move manifests between lifecycle states without recreating them or treating status as an informal convention.
- This is a concrete step toward richer release-channel operations while keeping the API additive and narrow.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Manifest lifecycle is still status-based rather than a fuller release-promotion model with approvals, provenance chains, or environment promotion history.
- The current UI exposes the most common status transitions only; it does not yet provide a dedicated release-management page or promotion audit timeline.

## Operator CLI release coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` release operations to cover newer admin surfaces:
  - `releases manifests-list --status ...`
  - `releases manifests-update-status --manifest-id ... --status ...`
  - `releases deployments-list --status ... --manifest-id ... --selector-channel ...`
- Added regression tests for:
  - manifest status update request shaping
  - deployment list request shaping with filters

### Why it changed

- The approved parity plan still had a CLI/operator tooling gap.
- The UI now exposes richer release operations, but operators also need scriptable access for local workflows, smoke runs, and automation without dropping to raw HTTP requests.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- CLI coverage is materially better now, but it still is not exhaustive across every new platform surface.
- The CLI remains a thin HTTP wrapper and does not yet add higher-level rollout helpers, wait/poll flows, or bulk operational scripting primitives.

## Operator CLI rollout control coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` rollout lifecycle support with:
  - `releases deployment-pause`
  - `releases deployment-resume`
  - `releases deployment-abort --reason ...`
- Added regression tests for pause and abort request shaping in `tests/test_operator_cli.py`.

### Why it changed

- The CLI could inspect and create deployments, but it still could not fully operate them.
- Closing that gap makes the CLI a more realistic operator surface for scripted rollout control, not just read/create flows.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- CLI rollout control is still intentionally thin; it does not yet provide guided safety prompts, waiter loops, or rollout summary/diff views.

## Deployment target inspector UX (2026-04-17)

### What changed

- Expanded the Admin deployment detail view with a filtered deployment-target table.
- Added operator filters for:
  - target status
  - device/failure search
- Surfaced deployment target details directly in the rollout inspector:
  - device ID
  - assigned stage
  - status
  - last report timestamp
  - failure reason

### Why it changed

- Rollout discovery and control had improved, but diagnosis still depended too heavily on raw event JSON.
- Particle-style parity requires per-target rollout inspection to be directly operable from the console, especially for failed, deferred, or partially healthy deployments.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The target table is driven from the existing deployment detail payload, so very large deployments still rely on the current full-detail response shape rather than a paginated target API.

## Paginated deployment target API (2026-04-17)

### What changed

- Added a paginated admin route for deployment targets:
  - `GET /api/v1/admin/deployments/{deployment_id}/targets`
  - supports `status`, `q`, `limit`, and `offset`
- Added backend filtering and total-count support for deployment targets.
- Switched the Admin deployment target table to use the new paginated endpoint instead of reading all targets from the full deployment detail payload.
- Added regression coverage for filtered/paginated deployment-target reads.

### Why it changed

- The earlier deployment inspector improvement still depended on the full deployment detail response carrying every target row.
- This slice reduces that coupling and moves the rollout inspector toward a more scalable read path for larger deployments.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The UI currently uses the paginated endpoint with a fixed first page (`limit=200`, `offset=0`) and filters, so true multi-page navigation is still a follow-up.
- Deployment detail still includes the legacy embedded `targets` array for compatibility; fully slimming that payload would be a separate compatibility decision.

## Deployment target paging UX (2026-04-17)

### What changed

- Added target-page controls to the Admin deployment inspector:
  - page size selector (`50`, `100`, `200`)
  - previous / next page controls
  - visible range display (`start-end of total`)
- Wired the target table to page through the new paginated target API instead of remaining fixed at the first page.

### Why it changed

- The paginated backend route reduced payload coupling, but the UI still behaved like a fixed first-page view.
- This closes the loop so larger deployments can actually be inspected across multiple pages from the operator console.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Pagination is still offset-based and local to the current filter set; there is not yet a deep-linkable or cursor-based target inspector.

## Server-side live stream filtering (2026-04-17)

### What changed

- Extended the SSE event stream route to support server-side:
  - `source_kind`
  - `event_name`
- Preserved backward compatibility with the older `event_type` source-category aliases.
- Updated the Live page to subscribe using the new server-side filters instead of only filtering in the browser after subscribing to everything.
- Fixed stream cursor timestamp normalization so SQLite-backed naive timestamps do not break the SSE loop.
- Added regression coverage for source-kind and event-name stream filtering.

### Why it changed

- The Live page previously narrowed events mostly on the client, which is wasteful and does not move the platform toward higher-scale streaming behavior.
- This slice reduces unnecessary event fan-in and makes the live stream UI a better fit for larger event volumes while keeping the current SSE surface.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Streaming is still poll-based SSE under the hood rather than a more scalable push/broker architecture.
- The current filter surface improves selectivity, but it does not yet add resumable cursors or historical replay windows to the live stream endpoint.

## Dedicated releases workspace (2026-04-17)

### What changed

- Added a dedicated Releases page at `/releases`.
- Wired the page into routing and primary navigation.
- The page provides a focused operator workspace for:
  - manifest filtering and lifecycle actions
  - deployment filtering and selection
  - deployment pause/resume/abort controls
  - paged target inspection
  - recent deployment event review

### Why it changed

- Release operations were still concentrated inside the generic Admin page, which kept rollout work overly admin-centric.
- This dedicated workspace moves the product closer to a first-class release-management surface without requiring a separate backend contract.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Release creation still lives in the Admin page; the new Releases page currently focuses on lifecycle management and rollout inspection rather than the initial publish form.

## End-to-end releases workspace (2026-04-17)

### What changed

- Expanded the dedicated `/releases` workspace so it now supports:
  - release manifest creation
  - deployment creation
  - manifest lifecycle actions
  - deployment lifecycle actions
  - paged target inspection
  - recent deployment event review
- This closes the earlier gap where the Releases page still depended on Admin for initial publish/deploy actions.

### Why it changed

- Release management was still split awkwardly between the new Releases page and the older Admin form.
- An operator-facing release workspace should cover the full release lifecycle, not just post-creation inspection and intervention.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Admin still contains overlapping release forms; this is now duplication rather than a missing capability, and consolidation is a future cleanup choice.

## Operator CLI target paging + live stream reads (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `releases deployment-targets-list`
  - `live-stream`
- `deployment-targets-list` supports paged target inspection with:
  - `--status`
  - `--query`
  - `--limit`
  - `--offset`
- `live-stream` supports filtered SSE reads with:
  - `--device-id`
  - `--source-kinds`
  - `--event-name`
  - `--max-events`
  - `--timeout-s`
- Added regression tests for both request shapes in `tests/test_operator_cli.py`.

### Why it changed

- The CLI still lagged behind the newer paginated rollout-inspection and server-filtered live-stream surfaces.
- This closes another part of the operator-tooling gap without inventing a separate CLI-only backend.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The live-stream CLI is still a thin SSE reader, not a durable tail/follow workflow with cursors or reconnection state.

## Concrete system-image updater wrappers (2026-04-17)

### What changed

- Added repo-owned helper scripts:
  - [scripts/ota/system_image_updater.py](/Users/ryneschroder/Developer/git/edgewatch-telemetry/scripts/ota/system_image_updater.py)
  - [scripts/ota/system_image_rollback.py](/Users/ryneschroder/Developer/git/edgewatch-telemetry/scripts/ota/system_image_rollback.py)
- The apply wrapper now:
  - validates the agent-provided artifact path and SHA-256
  - stages the artifact under `EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR`
  - writes per-manifest `metadata.json`
  - updates `latest.json`
  - optionally invokes a stage hook
- The rollback wrapper now:
  - reads the staged `latest.json`
  - records a rollback request marker
  - optionally invokes a rollback hook
- Added regression coverage in [tests/test_system_image_updater_scripts.py](/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_system_image_updater_scripts.py).
- Updated [docs/RUNBOOKS/OTA_UPDATES.md](/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/OTA_UPDATES.md) to document the repo-default wrapper commands.

### Why it changed

- The `system_image` OTA path previously depended on a completely unspecified external command contract.
- This does not replace real updater/hardware validation, but it makes the integration surface concrete, documented, and testable inside the repo.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These wrappers stage and annotate artifacts; they do not by themselves implement a production-grade partition switch, bootloader integration, or proven rollback on Raspberry Pi hardware.
- Real hardware validation is still required before claiming production-ready `system_image` OTA parity.

## Default system-image wrapper fallback (2026-04-17)

### What changed

- Updated the agent so `system_image` apply now falls back to the repo-owned wrapper automatically when `EDGEWATCH_SYSTEM_IMAGE_APPLY_CMD` is unset and the wrapper script is present.
- Updated boot-health timeout rollback so it similarly falls back to the repo-owned rollback wrapper when `EDGEWATCH_SYSTEM_IMAGE_ROLLBACK_CMD` is unset and the wrapper script is present.
- Added agent-side regression coverage for both fallback paths in [tests/test_agent_update_delivery.py](/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_update_delivery.py).
- Updated the OTA runbook to document that these wrappers are now the default fallback contract, not just optional examples.

### Why it changed

- The prior wrapper scripts made the integration contract concrete, but the agent still required explicit env wiring to use them.
- This makes the repo-owned path the practical default and reduces the amount of undocumented glue required to exercise `system_image` OTA in development and controlled validation lanes.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- This improves default wiring, but it does not change the fundamental truth that real bootloader/partition/hardware validation is still required before claiming production-ready `system_image` OTA support.

## Admin/Releases consolidation (2026-04-17)

### What changed

- Removed the duplicate release-management surface from [web/src/pages/Admin.tsx](/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx).
- Admin now links operators to the dedicated Releases workspace instead of carrying a second copy of:
  - manifest publish
  - manifest lifecycle controls
  - deployment creation
  - deployment lifecycle controls
  - rollout target inspection

### Why it changed

- Once the dedicated Releases page became end-to-end, the Admin copy turned into fragmentation rather than redundancy with value.
- Consolidating onto one operator path reduces UI sprawl and makes the release workflow easier to reason about.

### Validation

- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- This is a UX consolidation only; no release-management API capability was removed.
- Admin still retains broad operational controls, but Releases is now the intended operator surface for OTA lifecycle work.

## Server-side search entity filters (2026-04-17)

### What changed

- Added server-side `entity_type` filtering to `/api/v1/search`.
- Updated the System page search UI to send explicit entity-type filters instead of always searching across every entity class.
- Expanded the operator CLI `search` command with `--entity-types`.
- Added regression coverage for both the route and CLI request shapes.

### Why it changed

- Search was still an all-entities mixed result set with no server-side narrowing.
- This improves selectivity and moves the search surface a step closer to a more scalable/operator-friendly query model.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Search remains a simple filtered query API rather than a ranked/full-text search service with deeper query semantics.

## Paged unified search (2026-04-17)

### What changed

- Added `offset` support to `/api/v1/search` while preserving the current list-shaped response.
- Updated the System page search UI to support previous/next page navigation.
- Expanded the CLI `search` command with `--offset`.
- Added regression coverage for both route-side and CLI-side pagination request behavior.

### Why it changed

- Even with entity-type filters, search was still a single capped result page.
- This is a pragmatic step toward more scalable operator search without forcing an immediate response-shape break.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Search pagination is still offset-based over a mixed-entity result set and does not provide total counts, cursors, or strong ranking guarantees.

## Deployment deep-linking into Releases (2026-04-17)

### What changed

- Added route-search support on `/releases` for selected deployment and manifest IDs.
- Updated the Releases page to hydrate its selected deployment/manifest from route search state.
- Updated search-result navigation so deployment hits open directly into the Releases workspace instead of falling back to unrelated pages.
- Updated the Admin handoff link to the Releases workspace to use the explicit route-search contract.

### Why it changed

- Search and navigation should drop operators into the relevant rollout context, not force them to re-find the same deployment after navigating.
- This improves operator flow without adding another backend surface.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Deep linking is still limited to deployment/manifest selection; it does not yet preserve richer UI filter/paging state for the full Releases workspace.

## Live stream replay window (2026-04-17)

### What changed

- Added `since_seconds` support to `/api/v1/event-stream`.
- Updated the Live page to expose a replay window input and pass it server-side.
- Expanded the CLI `live-stream` command with `--since-seconds`.
- Added regression coverage for recent-event replay behavior and CLI request shaping.

### Why it changed

- The live stream previously behaved only as “tail from now,” which is weak for operator workflows and incident review.
- A small replay window makes the existing SSE surface more useful without introducing a separate historical-stream API.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Replay is still bounded by a simple relative window and uses the same poll-based SSE implementation; it is not a durable cursor/replay protocol.

## Release-manifest search results (2026-04-17)

### What changed

- Added `release_manifest` as a first-class unified-search entity.
- The backend search route now returns matching release manifests for admin users.
- The System page search UI now includes release manifests in its default entity-type set.
- Search results for release manifests now deep-link into the Releases workspace with the selected manifest.
- The CLI `search --entity-types` path now supports `release_manifest`.
- Added regression coverage for both route and CLI search behavior.

### Why it changed

- Release discovery in search was still deployment-only, which made manifest lookup incomplete for operator workflows.
- This closes another part of the release-management discoverability gap without introducing a separate manifest-search endpoint.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Manifest search is still part of the same mixed-entity search surface, so it inherits the current ranking and pagination limitations of unified search.

## Total-aware search page API (2026-04-17)

### What changed

- Added a new paged search response endpoint:
  - `GET /api/v1/search-page`
  - returns `items`, `total`, `limit`, and `offset`
- Updated the System page to use this response so pagination can show real totals instead of inferring from page size.
- Added route-side regression coverage for the new page response contract.

### Why it changed

- Offset pagination on the old list-only search API forced the UI to guess whether more results existed.
- This keeps the original `/api/v1/search` response shape intact while providing a clearer path for richer search UX.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- `search-page` still computes over the same mixed-entity search model and is not yet a true full-text or cursor-based search system.

## Paged operator-events feed (2026-04-17)

### What changed

- Added a new unified event-history endpoint:
  - `GET /api/v1/operator-events`
  - supports mixed alert/device_event/procedure_invocation history
  - supports `device_id`, `source_kind`, `event_name`, `limit`, and `offset`
- Added shared client types and fetch support in [web/src/api.ts](/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts).
- Updated the Live page to show a paged recent-history view alongside the SSE tail.
- Expanded the CLI with `operator-events`.
- Added route-side and CLI regression coverage.

### Why it changed

- The platform had a live stream, but no unified paged event-history surface to complement it.
- This is a meaningful step toward a more capable operator event architecture without jumping straight to a larger streaming system redesign.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- `operator-events` still uses an offset-based mixed-source aggregation model and is not yet backed by a purpose-built event index or durable cursor system.

## Deployment events in operator feeds (2026-04-17)

### What changed

- Added `deployment_event` support to both:
  - `/api/v1/operator-events`
  - `/api/v1/event-stream`
- Updated shared client types to include deployment events.
- Updated the Live page to:
  - subscribe to deployment events by default
  - show deployment events in recent history
  - deep-link deployment-event history rows into the Releases workspace
- Updated CLI defaults so both `live-stream` and `operator-events` include deployment events.
- Added route-side and CLI regression coverage for the expanded event surface.

### Why it changed

- Release operations were still second-class in the operator event surfaces.
- This closes an important gap between rollout control and event visibility by making deployment events first-class alongside alerts, device events, and procedure invocations.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Deployment-event history still shares the same mixed-source offset model as the rest of `operator-events`; it is not yet a dedicated rollout event timeline API with cursors or richer drill-down state.

## Release-manifest lifecycle events in operator feeds (2026-04-17)

### What changed

- Added `release_manifest_event` support to both:
  - `/api/v1/operator-events`
  - `/api/v1/event-stream`
- Release-manifest create/update admin audit entries are now visible through the operator event surfaces for admin users.
- Updated shared client types and Live-page defaults to include release-manifest events.
- Added deep links from release-manifest event history rows into the Releases workspace with the selected manifest.
- Updated CLI defaults so `live-stream` and `operator-events` include `release_manifest_event`.
- Added route-side and CLI regression coverage.

### Why it changed

- Release manifest lifecycle changes were still invisible in the main operator event surfaces even after deployment events became first-class.
- This closes another release-ops visibility gap and makes the release lifecycle more observable without inventing a separate manifest event API.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Release-manifest events are currently sourced from admin audit rows and therefore remain admin-only in operator event surfaces.

## Generic admin events in operator feeds (2026-04-17)

### What changed

- Added `admin_event` support to both:
  - `/api/v1/operator-events`
  - `/api/v1/event-stream`
- Non-release admin audit rows now flow into the unified operator event surfaces for admin users.
- Updated shared client types and Live-page defaults to include `admin_event`.
- Added contextual Live-page linking for generic admin events back into Admin.
- Updated CLI defaults so both `live-stream` and `operator-events` include `admin_event`.
- Added route-side and CLI regression coverage.

### Why it changed

- Important admin-side policy and configuration changes were still outside the main operator event surfaces.
- This closes another observability gap by making non-release admin mutations visible in the same live/history tools.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- `admin_event` is still sourced from audit rows and remains admin-only; it is not yet a broader multi-role operator timeline.

## Deep-linkable Live filters (2026-04-17)

### What changed

- Added route-search support on `/live` for:
  - `deviceId`
  - `sourceKinds`
  - `eventName`
  - `sinceSeconds`
- Updated the Live page to hydrate its filter state from route search.
- Updated System-page search result navigation so event/procedure hits can open into a prefiltered Live view instead of a blank stream.

### Why it changed

- Operator search should land users in the relevant filtered stream context, not force them to re-enter the same filter state after navigation.
- This improves operator flow without changing the underlying event APIs.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Live deep links currently preserve only core stream filters; they do not yet preserve paged history state or more advanced workspace context.

## Admin audit/history CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `admin events`
  - `admin notifications`
  - `admin exports`
- These commands now expose admin mutation audit, notification delivery audit, and analytics export history from the CLI.
- Added regression coverage for all three request shapes in `tests/test_operator_cli.py`.

### Why it changed

- Important audit/history surfaces still existed only in the web UI even after broader operator CLI expansion.
- This closes another practical gap for scripted/admin-console workflows.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These remain thin list/read wrappers and do not yet add richer summarization or follow/wait workflows on top of the underlying audit endpoints.

## Filtered admin audit lane (2026-04-17)

### What changed

- Added server-side filters to `GET /api/v1/admin/events`:
  - `action`
  - `target_type`
  - `device_id`
- Updated the Admin UI events tab to expose those filters.
- Updated the CLI `admin events` command to pass the same filters.
- Added regression coverage for both the route and CLI request behavior.

### Why it changed

- The admin audit stream had become too blunt as the platform surface expanded.
- This makes the audit lane more usable for focused investigations without changing the underlying audit model.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The admin audit lane is still a simple list endpoint and does not yet support richer paging or full-text filtering.

## Total-aware admin audit lane (2026-04-17)

### What changed

- Added `GET /api/v1/admin/events-page` with:
  - `items`
  - `total`
  - `limit`
  - `offset`
- Updated the Admin UI events tab to use the paged response and show real totals with previous/next page controls.
- Expanded the CLI with `admin events-page`.
- Added regression coverage for the paged route and CLI request shape.

### Why it changed

- Even with filters, the admin audit lane was still a simple capped list with no total-aware pagination.
- This is a meaningful step toward a more scalable/admin-friendly audit workflow without breaking the original list endpoint.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The admin audit lane is still offset-based and not yet backed by a more advanced search/index model.

## Admin events in unified search (2026-04-17)

### What changed

- Added `admin_event` as a first-class unified-search entity for admin users.
- Updated the System page search defaults and result routing so admin-event hits deep-link into the Admin events tab with relevant filters.
- Added `/admin` route-search support for event-tab filter context and updated Admin to hydrate from that state.
- Added route-side and CLI regression coverage for the new search entity and deep-link contract.

### Why it changed

- Important admin-side changes were filterable in the audit lane but still not searchable alongside the rest of the operator surface.
- This closes another discoverability gap and makes admin audit changes navigable from unified search.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- `admin_event` search is still based on the current mixed-entity query model and inherits its ranking/pagination limitations.

## Notification/export search entities (2026-04-17)

### What changed

- Added `notification_event` and `export_batch` as first-class unified-search entities for admin users.
- Updated the System page search defaults and result routing so:
  - notification audit hits deep-link into the Admin notifications tab
  - export batch hits deep-link into the Admin exports tab
- Added route-side regression coverage for the broader mixed search results.

### Why it changed

- Important admin-only audit/history surfaces were still absent from unified search.
- This closes another search/discovery gap without adding new backend endpoints.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These new search entities still inherit the mixed-entity ranking and pagination limits of the unified search model.

## Device admin CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `devices create`
  - `devices update`
  - `devices shutdown`
- These commands now expose device registration, metadata/config updates, and admin shutdown intent from the CLI.
- Added regression coverage for all three request shapes in `tests/test_operator_cli.py`.

### Why it changed

- Important device-admin capabilities still existed only in the backend/UI even after broader operator CLI expansion.
- This closes another practical operator-tooling breadth gap for scripted fleet administration.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These commands remain thin wrappers over the admin API and do not yet add interactive confirmation or higher-level safety rails.

## Contextual event-history links (2026-04-17)

### What changed

- Updated the Live page so event-history rows and SSE rows now deep-link into the most relevant workspace for each event kind:
  - alerts -> Alerts
  - device events -> filtered Live
  - procedure invocations -> filtered Live
  - deployment events -> Releases
  - release-manifest events -> Releases

### Why it changed

- Operator event surfaces should not be dead-end logs.
- This improves navigation flow by turning the event feeds into actionable jump-off points rather than forcing manual re-filtering after every click.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py typecheck`

### Risks / rollout notes

- Event-history links preserve core context, but they still do not capture every possible local UI state or pagination detail in the destination workspace.

## Ingestion/drift audit CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `admin ingestions`
  - `admin drift-events`
- These commands expose ingestion lineage and drift audit history from the CLI with optional device filtering.
- Added regression coverage for both request shapes in `tests/test_operator_cli.py`.

### Why it changed

- The admin/history CLI surface was still missing two important audit lanes that were already available in the web UI.
- This further narrows the operator-tooling breadth gap without adding any new backend contract.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These remain thin list/read wrappers and do not yet provide higher-level summaries or diffing across ingestion/drift history.

## Explicit parity signoff docs (2026-04-17)

### What changed

- Added [docs/PARTICLE_PARITY_MATRIX.md](/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/PARTICLE_PARITY_MATRIX.md) to explicitly map repo/platform status versus the Particle-style target surface.
- Added [docs/RUNBOOKS/SYSTEM_IMAGE_HARDWARE_VALIDATION.md](/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SYSTEM_IMAGE_HARDWARE_VALIDATION.md) as the final real-hardware signoff gate for `system_image` OTA.
- Linked both from [docs/START_HERE.md](/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/START_HERE.md).

### Why it changed

- The remaining blocker is now mostly operational proof on real hardware, not missing repo plumbing.
- Making that explicit in-repo prevents the project from oscillating between “almost done” and “not clearly defined.”

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These docs do not replace the required real Pi validation itself; they only make the final acceptance gate explicit and auditable.

## Hardware validation evidence helper (2026-04-17)

### What changed

- Added [scripts/ota/collect_system_image_validation_evidence.py](/Users/ryneschroder/Developer/git/edgewatch-telemetry/scripts/ota/collect_system_image_validation_evidence.py) to collect:
  - agent update-state data
  - staged system-image `latest.json`
  - per-manifest metadata when present
- Added regression coverage in [tests/test_system_image_validation_evidence_script.py](/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_system_image_validation_evidence_script.py).
- Updated [docs/RUNBOOKS/SYSTEM_IMAGE_HARDWARE_VALIDATION.md](/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SYSTEM_IMAGE_HARDWARE_VALIDATION.md) and [docs/START_HERE.md](/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/START_HERE.md) to reference the helper.

### Why it changed

- The remaining blocker is real Pi validation, so the repo should make evidence capture as concrete and repeatable as possible.
- This reduces the remaining ambiguity around what operators should collect during hardware signoff.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- This helper collects evidence; it does not perform the hardware validation itself or prove reboot/rollback behavior.

## Hardware validation evidence evaluator (2026-04-17)

### What changed

- Added [scripts/ota/evaluate_system_image_validation.py](/Users/ryneschroder/Developer/git/edgewatch-telemetry/scripts/ota/evaluate_system_image_validation.py) to evaluate collected `system_image` validation evidence for:
  - `good_release`
  - `rollback_drill`
- Added regression coverage in [tests/test_system_image_validation_evaluator.py](/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_system_image_validation_evaluator.py).
- Updated [docs/RUNBOOKS/SYSTEM_IMAGE_HARDWARE_VALIDATION.md](/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SYSTEM_IMAGE_HARDWARE_VALIDATION.md) and [docs/START_HERE.md](/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/START_HERE.md) to reference the evaluator.

### Why it changed

- The repo now has a clear evidence collection helper, but operators still needed a consistent way to judge whether the captured evidence is complete enough for review.
- This makes the final non-hardware acceptance workflow more concrete and repeatable.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The evaluator only checks evidence completeness heuristically; it does not prove real reboot/apply/rollback behavior on its own.

## Hardware validation CLI workflow (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `ota-validation collect`
  - `ota-validation evaluate`
  - `ota-validation run`
- These commands wrap the repo-owned evidence collector/evaluator so the final `system_image` validation workflow is reachable from the same operator CLI surface as the rest of the platform.
- Added regression coverage for the chained `run` workflow in `tests/test_operator_cli.py`.

### Why it changed

- The remaining blocker is real Pi validation, so the repo should make that last-mile workflow as operationally crisp as possible.
- This reduces the remaining “glue work” around the final acceptance gate.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- This still does not replace actual hardware execution; it only consolidates the evidence workflow into one operator-facing command surface.

## Access-management CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `fleets remove-device`
  - `fleets access-list`
  - `fleets revoke`
  - `devices access-list`
  - `devices access-grant`
  - `devices access-revoke`
- These commands now expose the remaining per-device and fleet access-management primitives from the CLI.
- Added regression coverage for all new request shapes in `tests/test_operator_cli.py`.

### Why it changed

- Access management was still incomplete in the CLI even though the backend and admin UI already supported it.
- This closes another practical operator-tooling breadth gap for scripted fleet administration.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Access-management commands remain low-level wrappers and do not yet provide diff/preview flows or higher-level policy summaries.

## Procedure-definition update CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with `procedures update`.
- The CLI can now patch existing procedure definitions for:
  - description
  - timeout
  - request schema
  - response schema
  - enabled/disabled state
- Added regression coverage for the update request shape in `tests/test_operator_cli.py`.

### Why it changed

- Procedure definitions were still create/list-only in the CLI even though the backend already supported updates.
- This closes another operator-tooling gap for scripted device-cloud administration.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Procedure updates remain low-level patch operations; the CLI does not yet provide higher-level schema diff or validation helpers beyond basic JSON parsing.

## Remaining fleet/device CLI breadth (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `fleets devices`
  - `notification-destinations delete`
  - `devices list`
  - `fleets access-list`
  - `fleets revoke`
  - `fleets remove-device`
  - `devices access-list`
  - `devices access-grant`
  - `devices access-revoke`
- Added regression coverage for the new request shapes in `tests/test_operator_cli.py`.

### Why it changed

- Several routine operator/admin actions were still missing from the CLI even though the backend supported them.
- This materially reduces the remaining operator-tooling breadth gap without changing backend contracts.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These commands remain thin wrappers over the API and still do not provide richer guardrails, previews, or bulk workflow helpers.

## Owner/operator controls CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `devices controls-get`
  - `devices operation-set`
  - `devices alerts-set`
- These commands now expose the owner/operator device control flows from the CLI:
  - read current control state
  - set operation/runtime power mode
  - set or clear alert mute windows
- Added regression coverage for all three request shapes in `tests/test_operator_cli.py`.

### Why it changed

- Important operator controls still existed only in the API/UI even after broader admin CLI expansion.
- This closes another practical operator-tooling gap for scripted device operations.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These commands remain thin wrappers and do not yet add richer validation or safety flows for operator mistakes.

## Edge-policy CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `admin edge-policy-source`
  - `admin edge-policy-update`
- These commands now expose the active edge-policy YAML source read/update workflow from the CLI.
- Added regression coverage for both request shapes in `tests/test_operator_cli.py`.

### Why it changed

- Edge policy management was still a backend/UI-only surface even after broader admin CLI expansion.
- This closes another practical operator-tooling gap for policy-driven fleet operations.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The CLI currently replaces the YAML source text directly and does not yet offer structured field-level editing or schema-aware assistance.

## Media CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `media list`
  - `media download`
- These commands now expose device-auth media listing and payload download from the CLI.
- Added regression coverage for both request shapes in `tests/test_operator_cli.py`.

### Why it changed

- Media operations were still only practically available in the web UI despite being part of the platform surface.
- This closes another operator-tooling breadth gap for field/media workflows.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Media download is currently a direct file write helper and does not yet add richer file naming or preview workflows.

## Alerts + telemetry CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `alerts`
  - `telemetry`
  - `timeseries`
- These commands now expose the core read-side operator workflows for alerts, raw telemetry, and bucketed telemetry from the CLI.
- Added regression coverage for all three request shapes in `tests/test_operator_cli.py`.

### Why it changed

- Alerts and telemetry are core operator flows and still were not directly exposed in the CLI.
- This closes another major operator-tooling breadth gap without changing any backend contracts.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These remain low-level read wrappers and do not yet add richer summaries, charting, or cursor/pagination helpers for large telemetry datasets.

## Device/fleet read CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `devices get`
  - `devices summary`
  - `fleets devices`
- These commands now expose direct device detail, fleet-friendly device summaries, and accessible fleet membership reads from the CLI.
- Added regression coverage for all new request shapes in `tests/test_operator_cli.py`.

### Why it changed

- Even with alerts and telemetry added, the CLI still lacked a few foundational read-side operator workflows.
- This closes another chunk of operator-tooling breadth without requiring any backend changes.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These remain direct API wrappers and do not yet provide richer fleet/device summaries beyond what the API already returns.

## Public health/contracts CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `health`
  - `contracts telemetry`
  - `contracts edge-policy`
- These commands now expose the core public platform diagnostics/contracts from the CLI.
- Added regression coverage for all three request shapes in `tests/test_operator_cli.py`.

### Why it changed

- The CLI still lacked the platform’s most basic public diagnostic/configuration reads.
- This closes another operator-tooling breadth gap without any backend changes.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- These are still direct read wrappers and do not yet provide richer human-oriented summaries on top of the raw contract data.

## Total-aware search CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with `search-page`.
- This exposes the newer total-aware `/api/v1/search-page` surface directly in the CLI instead of leaving it UI-only.
- Added regression coverage for the request shape in `tests/test_operator_cli.py`.

### Why it changed

- The CLI still only exposed the older list-shaped search result, even after the paged search API existed.
- This closes another operator-tooling gap and aligns the CLI with the richer search surface.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- `search-page` still inherits the current mixed-entity ranking and offset-based pagination model from the backend.

## Fleet/device OTA governance CLI coverage (2026-04-17)

### What changed

- Expanded `scripts/operator_cli.py` with:
  - `fleets update`
  - `devices update-ota`
- `fleets update` now supports fleet metadata/default-channel edits from the CLI.
- `devices update-ota` now exposes per-device OTA governance fields from the CLI:
  - channel
  - updates enabled/disabled
  - busy reason / clear busy reason
  - development / not-development
  - locked manifest / clear locked manifest
- Added regression coverage for both request shapes in `tests/test_operator_cli.py`.

### Why it changed

- OTA governance was still split between backend/UI support and incomplete CLI coverage.
- This closes another practical operator-tooling gap for scripted fleet/device rollout posture changes.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The CLI now covers more governance operations, but it still remains a thin HTTP wrapper rather than a higher-level operational assistant with guardrails or diff previews.

## Device cloud core: procedures, state, and events (2026-04-17)

### What changed

- Added device-cloud persistence models and migration support for:
  - typed procedure definitions
  - durable procedure invocations
  - reported device state snapshots
  - append-only device events
- Added new API surfaces for:
  - admin-managed procedure definitions
  - operator procedure invocation and history
  - device-auth procedure result reporting
  - device-auth state reporting
  - device-auth event publishing
  - operator read access to state and device events
- Extended device policy delivery so devices can receive a pending procedure invocation through the existing cached policy loop.
- Added a generic device-local procedure runner hook in the agent using `EDGEWATCH_PROCEDURE_RUNNER_CMD`.
- Added regression coverage for:
  - route surface toggles
  - SQLite migrations
  - procedure definition/invocation/result flow
  - reported state round-trip
  - device event publish/list
  - agent-side procedure execution/reporting

### Why it changed

- Particle-style software-platform parity requires more than telemetry and OTA; it also needs first-class device-cloud primitives.
- EdgeWatch already had a durable command/policy model, so procedures, state, and events were added as explicit, typed constructs instead of inventing an arbitrary remote-exec path.
- Separating telemetry, reported state, device events, and procedures keeps the platform legible and safer to evolve.

### Validation

- `uv run --locked pyright api/app agent tests`
- `uv run --locked pytest tests/test_device_cloud_routes.py tests/test_agent_procedure_delivery.py tests/test_route_surface_toggles.py tests/test_migrations_sqlite.py`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Procedure execution currently depends on a device-local runner hook (`EDGEWATCH_PROCEDURE_RUNNER_CMD`); without it, pending procedure invocations will fail closed.
- This slice adds backend/platform primitives only; there is not yet a dedicated UI workflow for procedures, state, and events beyond the APIs.
- Procedure definitions are global and single-tenant at this stage; fleet-scoped governance is a follow-up slice.

## Fleet governance + fleet-scoped access (2026-04-17)

### What changed

- Added first-class fleet persistence and migrations:
  - `fleets`
  - `fleet_device_memberships`
  - `fleet_access_grants`
- Added fleet admin APIs for:
  - create/list/update fleets
  - add/remove device memberships
  - list/put/delete fleet access grants
- Added read APIs for:
  - list accessible fleets
  - list accessible devices in a fleet
- Extended device access resolution so non-admin users can reach devices through:
  - existing per-device grants
  - new fleet-scoped grants via fleet membership
- Preserved per-device grants as valid narrow-scope / break-glass access.

### Why it changed

- The approved Particle-parity plan requires fleets to be first-class governance and release scope, not just selectors.
- EdgeWatch already had per-device ownership, but nothing equivalent to a fleet boundary for operator grouping and rollout scope.
- Reusing the existing grant model at fleet scope adds governance without replacing the current least-privilege design.

### Validation

- `uv run --locked pyright api/app tests`
- `uv run --locked pytest tests/test_fleet_routes.py tests/test_device_access.py tests/test_route_surface_toggles.py tests/test_migrations_sqlite.py`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Fleet membership and fleet grants are backend-only in this slice; dedicated UI workflows are still follow-up work.
- Devices can still be targeted by labels/cohorts and explicit IDs; fleets add a governance path rather than deprecating existing selectors yet.

## Operator search + live event stream (2026-04-17)

### What changed

- Added a unified operator search API covering:
  - devices
  - fleets
  - alerts
  - device events
  - procedure invocations
  - deployments (admin-visible)
- Added a server-sent event stream endpoint that emits:
  - alerts
  - device events
  - procedure invocation events
- Scoped both surfaces through the existing viewer/device access model.
- Added route-surface and backend search tests.

### Why it changed

- The approved parity plan calls for operator-visible search and live event streaming as core platform capabilities, not just UI backlog items.
- EdgeWatch already had the underlying entities; adding a unified read surface makes them usable without inventing a second control model.

### Validation

- `uv run --locked pyright api/app tests`
- `uv run --locked pytest tests/test_operator_tools_routes.py tests/test_route_surface_toggles.py`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The SSE endpoint currently uses simple polling over the database-backed event sources; it is operationally fine for small/medium fleets but not yet an optimized high-fanout streaming architecture.
- Search is backend-only in this slice; dedicated UI search workflows are still follow-up work.

## Generalized event delivery (2026-04-17)

### What changed

- Extended notification destinations so they can filter by:
  - source kind
  - event type
- Extended notification delivery history so it now records:
  - alert deliveries
  - device event deliveries
  - procedure invocation deliveries
  - deployment event deliveries
- Generalized the webhook delivery pipeline so non-alert platform events use the same destination, filtering, and audit model as alerts.
- Hooked event delivery into:
  - device event publication
  - procedure invocation result completion
  - deployment lifecycle event creation
- Preserved backward-compatible alert behavior by defaulting destinations to alert-only unless configured otherwise.

### Why it changed

- The parity plan requires integrations to be event-driven across the platform, not just alert-driven.
- Reusing the existing destination/audit model keeps one delivery pipeline instead of fragmenting alerts and platform events into separate mechanisms.

### Validation

- `uv run --locked pyright api/app tests`
- `uv run --locked pytest tests/test_notifications_service.py tests/test_operator_tools_routes.py tests/test_device_cloud_routes.py tests/test_admin_deployments.py tests/test_device_updates_service.py`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Existing destinations remain alert-only by default; operators must explicitly opt a destination into non-alert event sources.
- Deployment events without a concrete device still flow through the generic delivery model, but per-fleet targeting and richer destination policy are still follow-up work.

## Operator CLI baseline (2026-04-17)

### What changed

- Added `scripts/operator_cli.py` as a thin operator workflow surface for:
  - search
  - fleets
  - procedures
  - device state and device events
  - notification destinations
  - release/deployment inspection
- The CLI reuses the current HTTP API and auth posture:
  - `--admin-key` for admin routes
  - dev principal headers for local authz testing
  - optional extra headers for perimeter/IAP-oriented setups
- Added focused tests covering search and fleet-create request shaping.

### Why it changed

- The parity plan calls for operator/developer tooling, and the backend/platform surface is now broad enough that a CLI materially improves usability before more UI work lands.
- A thin CLI over the existing API avoids inventing a second control model.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The CLI is intentionally thin and does not yet cover every backend surface.
- It assumes the same auth/perimeter posture as the HTTP API; production workflows may still prefer IAP/private-admin entrypoints.

## OTA artifact manifests + hybrid updater path (2026-04-16)

### What changed

- Extended the OTA data model and API contracts so release manifests now carry:
  - `update_type`
  - artifact URI/size/hash
  - artifact signature metadata
  - compatibility metadata
- Extended device OTA policy/reporting so devices now receive:
  - artifact-aware `pending_update_command`
  - OTA readiness fields (`updates_enabled`, `updates_pending`, `busy_reason`)
  - richer device update states (`downloaded`, `staged`, `switching`) in addition to the previous lifecycle
- Added OTA governance/device fields on devices:
  - `ota_channel`
  - `ota_updates_enabled`
  - `ota_busy_reason`
  - `ota_is_development`
  - `ota_locked_manifest_id`
- Updated the agent OTA apply path to:
  - download artifacts into a persistent cache
  - verify artifact hash
  - optionally verify artifact signatures via `openssl`
  - apply `application_bundle` natively
  - apply `asset_bundle` via extract or optional hook
  - invoke an external updater command for `system_image`
  - persist pending boot-health state for post-reboot confirmation
- Extended deployment health logic to include defer-rate halts and timeout-based halts.
- Added/updated OTA tests covering:
  - artifact-aware manifest creation
  - pending update policy delivery
  - richer agent update flow
  - deployment service/route behavior
- Updated OTA design/contracts/runbook docs for the artifact-based hybrid updater path.

### Why it changed

- The previous OTA implementation had a strong rollout control plane but still treated on-device git tags as the actual update payload.
- Particle-grade OTA requires real artifact delivery, on-device verification, richer lifecycle state, and a safer system-image apply path than a repo/tag swap can provide.
- A hybrid updater model lets EdgeWatch keep ownership of rollout/orchestration while using a safer external system updater for image installs and rollback.

### Validation

- `uv run --locked pyright api/app agent tests`
- `uv run --locked pytest tests/test_agent_update_delivery.py tests/test_device_updates_service.py tests/test_device_policy.py tests/test_admin_deployments.py tests/test_agent_device_policy.py tests/test_device_updates_routes.py`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- `system_image` apply now assumes an external updater command is supplied; without it, system-image deployments will fail intentionally instead of pretending to succeed.
- Artifact signature verification currently supports `openssl_rsa_sha256`; broader signature schemes or trust distribution workflows remain follow-up work if needed.
- Boot-health confirmation for system-image updates is process-restart based; a production updater/bootloader integration still needs real-device validation before fleet rollout.

## Alerts search completion + Tailscale operator overlay (2026-04-16)

### What changed

- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/alerts.py` so `GET /api/v1/alerts` now accepts `q` plus legacy `search` and applies case-insensitive partial matching across `device_id`, `alert_type`, and `message`.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts` and `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx` so the alerts page sends its canonical URL search text to the server and includes that search term in the query cache key.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/DataTable.tsx` so bounded vertical scrolling is restored only for callers that pass an explicit `height`; pages without `height` keep viewport-owned scrolling.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx` so `health=open_alerts` no longer collapses to a false empty fleet while alert state is still loading or unavailable.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md` and `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_RPI.md` to document the new alerts search contract and a Tailscale operator overlay for MacBook-to-device private access.
- Added `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/TAILSCALE_OPERATOR.md` with a concrete grants template, edge-device bootstrap commands, and verification/failure-mode guidance for the operator overlay.

### Why it changed

- Alerts URL search was claiming reload-safe behavior without actually searching the full backend dataset.
- The shared table refactor changed scroll semantics for existing fixed-height admin/detail tables that still expect internal scroll regions.
- The Devices page could deep-link into `health=open_alerts` before alert state loaded and incorrectly report that no devices matched.
- Edge-device operator access needed explicit Tailscale guidance without changing the repo's default posture of public ingest plus private operator surfaces.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Server-side alerts search currently matches only `device_id`, `alert_type`, and `message`; if the UI later promises broader fields, the route contract must be expanded in lockstep.
- Devices with `health=open_alerts` selected now stay visible while alert state is unavailable, which is safer than false-empty results but still depends on the alert feed to narrow correctly.

## Canonical filter URL sync + dashboard handoff (2026-04-14)

### What changed

- Added `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/utils/filterUrlState.ts` to centralize canonical filter/query parsing and URL building for:
  - Devices
  - Alerts
  - Dashboard timeline controls
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx` so:
  - device filters now sync back to the URL
  - legacy query keys are still read
  - a new `health` filter supports dashboard-driven fleet views such as low water pressure, weak signal, low battery, and no telemetry
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx` so resolution, severity, type, device, search text, and page size all sync into canonical URL params while still accepting older aliases.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx` so:
  - dashboard timeline controls sync into URL params
  - “Open in Alerts” uses the canonical alerts URL contract
  - fleet health tiles now navigate to `/devices` with the correct filter params already applied

### Why it changed

- Clicking summary/detail tiles should carry the user into the next page with the relevant filters already active instead of dropping them onto an unfiltered list.
- Filter state needs to be copy/pasteable and reload-safe, which requires writing current UI state back into the URL instead of only reading from it on first load.
- Backward compatibility still matters because older links already use prior query-key names such as `openOnly`, `resolvedOnly`, `deviceStatus`, and `search`.

### Validation

- `pnpm --dir web typecheck`
- `pnpm --dir web build`
- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Devices now supports additional URL-driven health filters that are UI-only fleet views; if those labels or threshold rules change later, the URL contract should be kept in sync.
- Alerts URL updates use replace-navigation for filter changes, which avoids noisy history but means per-keystroke search changes do not create separate back-stack entries.

## Full-width main scroll hit area (2026-04-13)

### What changed

- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/components/FleetMap.tsx` so the dashboard Leaflet map no longer captures mouse-wheel scrolling for zoom.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx` so the app no longer traps vertical scrolling inside a fixed-height inner pane. The viewport/body now owns scrolling, while the sidebar and header remain sticky.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx` so `main` stays a plain full-width scroll surface with no content-width wrapper.
- Added the centered inner `max-w-7xl` content box to `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/Page.tsx`, so page content remains visually bounded while the surrounding `main` area still belongs to the full pane.
- Applied `box-border` to the shared `max-w-7xl` wrappers in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/Page.tsx` and `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx` so the horizontal padding stays inside the 7xl cap instead of making the rendered box wider than intended.
- Extended `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/Page.tsx` with an optional inner content wrapper override.
- Narrowed the Dashboard page in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx` from the shared 7xl default to `max-w-6xl`, which reduces the dashboard content width without affecting the full-width scroll surface.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/styles.css` so the document scrollbar is hidden globally while scroll behavior remains active.
- Added a full document-edge reset in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/styles.css` (`body { margin: 0 }` plus full-width root wrappers) so the app shell is flush with the viewport instead of inheriting browser default page insets.
- Removed the last shared inner content wrapper from `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx`; `main` now renders route content directly.
- Moved standard page padding into `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/Page.tsx` so spacing is applied by pages rather than by a nested shell container.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/DataTable.tsx` so shared tables no longer create their own vertical scroll regions by default; they now grow with page content and only keep horizontal overflow handling.
- Simplified `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx` to remove the special full-height/overflow-hidden table layout that forced the fleet table into an inner scroll container.

### Why it changed

- The dashboard map was intercepting wheel events, which caused the page scroll to pause on the map and zoom the map instead.
- The app shell was still using a fixed-height application frame, which meant scroll behavior stayed inside a nested region even after widening `main`.
- Moving scrolling back to the viewport is what places scroll interaction on the full visible page area and aligns the effective scrollbar with the browser edge instead of an internal container.
- The right structure is a full-width `main` with page-owned constrained content. That keeps the scrollbar behavior associated with the full pane while preserving centered content margins.
- Tailwind `max-w-7xl` only caps the content box by default, so shared padding on the same element can make the rendered box wider than 7xl unless the wrapper uses border-box sizing.
- After fixing the layout structure, the remaining issue on Dashboard was simply that `7xl` still looked too wide for that page, so Dashboard now opts into a slightly narrower bound.
- Browser default body margins can still leave the entire app inset from the viewport edge even after the shell is full width, so the root page chrome now explicitly resets that default.
- Even with the shell widened, a nested content wrapper inside `main` still made the rendered page tree look like an inset column in devtools, so that wrapper has been removed.
- Shared tables were still using fixed heights plus `overflow-y-auto`, so on data-heavy pages the effective scroll target remained the centered table area rather than the page itself.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- This changes the shared shell from pane-scrolling to viewport-scrolling, so any page that relied on the old fixed-height inner scroll region could need a follow-up adjustment.
- Long tables now contribute to page height instead of staying inside fixed-height cards, so some admin/detail pages will scroll more as a whole page than before.

## Summary metric cap + local env drift fixes (2026-04-04)

### What changed

- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py` so `/api/v1/devices/summary` applies `limit_metrics` after metric de-dupe and key validation instead of counting raw query params first.
- Extended `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts` to support an explicit `limitMetrics` option for summary requests.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx` to keep its combined vitals + location metric list in one constant and pass the matching summary cap to the API.
- Added `/Users/ryneschroder/Developer/git/edgewatch-telemetry/scripts/check_demo_env_sync.py` and wired it into `make up`, `make dev`, and `make simulate` in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile` so preserved `.env` files now emit a note when their tracked demo defaults differ from the current examples.
- Added regression coverage in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_summary_routes.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_demo_env_sync.py`

### Why it changed

- The dashboard had started requesting 26 summary metrics while the route default cap remained 20, which could fail a fresh summary fetch.
- The route also counted duplicate and invalid metric keys against the cap, so callers could hit the limit unnecessarily.
- Local Make targets were silently preserving stale demo `.env` values, which is how the old `demo-well-001` simulator mismatch slipped through.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Existing local `.env` overrides are still preserved intentionally; the new behavior is visibility, not forced replacement.
- Any future page that requests more than the default 20 summary metrics still needs to pass an explicit `limitMetrics` value.

## Devices page vitals request the displayed metrics (2026-04-03)

### What changed

- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx` so the Devices page summary query requests the same telemetry keys that the Vitals column renders:
  - water pressure
  - oil pressure
  - oil level
  - drip oil level
  - oil life
  - temperature
  - humidity
  - battery
  - RSSI
- Tightened the Vitals pill formatting so truly missing values render as `—` without a dangling unit suffix.

### Why it changed

- The page was only requesting microphone and power metrics, so the Vitals pills had labels but no values.
- Matching the requested summary metrics to the rendered pills makes the fleet table show the expected latest values from each device.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The Devices page now requests more summary keys per device, but it remains within the backend request cap and only fetches the latest telemetry point per device.

## Devices page fleet card fills available height (2026-04-03)

### What changed

- Updated the app shell main content region in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx` to be a vertical flex container with bounded overflow sizing.
- Updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx` so the page, fleet card, and card content all participate in a full-height flex layout.
- Extended `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/DataTable.tsx` to accept CSS string heights, then switched the Devices fleet table from a fixed `560px` height to `100%`.
- Followed up with an explicit viewport-based minimum height and table height on `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx` so the Fleet card grows visibly on tall screens instead of depending only on inherited flex height.

### Why it changed

- The fleet card on the Devices page was vertically compressed because the table height was hardcoded and the page/card containers did not stretch to the available viewport height.
- The final layout uses a viewport-based height target so the Fleet card grows predictably while keeping the table itself scrollable.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- The height API for the shared `DataTable` component is now slightly broader (`number | string`), but existing callers still use the same numeric behavior.

## Named sample fleet defaults for local/demo data (2026-04-03)

### What changed

- Replaced the default `demo-well-*` sample fleet seed with a shared named device list:
  - `baxter-1`
  - `sprinklers-west`
  - `sprinklers-middle`
  - `sprinklers-tw`
  - `sprinklers-south`
  - `lms-1` through `lms-4`
  - `deen-1`
  - `deen-2`
- Increased the default local/demo fleet size from `3` to `11` so the entire named sample fleet is bootstrapped and simulated without extra env overrides.
- Updated the shared demo-fleet helper in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/demo_fleet.py` so API bootstrap, Cloud simulation, and local Makefile simulation all resolve the same device IDs.
- Updated local/demo defaults and examples in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/variables.tf`
  - agent defaults in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/simulator.py`, `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`, `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/replay.py`, and `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/tools/camera.py`
- Added regression coverage for named fleet derivation in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_demo_fleet_derivation.py`.

### Why it changed

- The previous sample IDs read like placeholder fixtures rather than a plausible field fleet.
- The local/demo experience now starts with the full realistic sample fleet without changing the existing fallback derivation behavior for custom numeric templates.

### Validation

- `python scripts/harness.py lint`
- `python scripts/harness.py typecheck`
- `python scripts/harness.py test`

### Risks / rollout notes

- Existing local databases may still contain older `demo-well-*` rows; the new defaults affect new bootstrap/simulation runs, not historical cleanup.
- Custom demo seeds that rely on `...001` suffix derivation continue to work unchanged.

## Low-power runtime modes: eco + optional deep sleep (2026-03-17)

### What changed

- Extended per-device controls, policy payloads, and device outputs with:
  - `runtime_power_mode` (`continuous|eco|deep_sleep`)
  - `deep_sleep_backend` (`auto|pi5_rtc|external_supervisor|none`)
- Added additive device schema support and migration:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0015_device_low_power_runtime.py`
- Extended edge policy defaults:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/edge_policy/v1.yaml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/edge_policy.py`
- Extended telemetry/runtime surfaces with:
  - `power_runtime_mode`
  - `power_sleep_backend`
  - `wake_reason`
  - `network_duty_cycled`
  - in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
- Implemented agent low-power behavior in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`:
  - `continuous`: unchanged always-on behavior
  - `eco`: software-only duty cycling of network syncs, local buffering of routine telemetry, platform radio/display reductions when cellular is used
  - `deep_sleep`: optional halt path using Pi 5 RTC wakealarm or Pi 4 external supervisor, with automatic fallback to `eco` when unsupported
- Updated UI control surfaces and visibility:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
- Updated deployment, hardware, BOM, and tutorial docs to describe:
  - Raspberry Pi OS Lite as the standard OS
  - Ubuntu as best-effort only
  - standard always-on, `eco`, and hardware-assisted `deep_sleep` deployment tiers

### Why it changed

- The previous runtime only idled in-process between samples. That saved little board power because Linux and the modem stayed fully on.
- The product needed a software-first low-power mode that works on existing Pi 4 hardware, plus an optional true deep-sleep path without making extra hardware mandatory.

### Validation

- `uv run pytest tests/test_agent_command_delivery.py tests/test_agent_runtime_power_saver.py tests/test_agent_device_policy.py tests/test_device_policy.py tests/test_migrations_sqlite.py` ✅

### Risks / rollout notes

- `eco` only saves meaningful energy if heartbeat cadence is longer than sample cadence or if alert transitions are infrequent.
- `deep_sleep` changes command/OTA immediacy: durable commands are applied on wake windows, not continuously.
- Pi 4 true `deep_sleep` still depends on external supervisor hardware and must be field-tested before broad rollout.

### Lessons learned

- The main architectural boundary is not “sampling” vs “not sampling”; it is “record locally” vs “turn the network on.”
- Low-power claims on Linux need to be explicit about what remains powered. `time.sleep()` is not a hardware sleep strategy.

## Locked v1 cellular hardware standard + checkout list (2026-03-15)

### What changed

- Locked the recommended v1 field hardware stack in docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/BOM.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`
- Standardized recommendation:
  - existing `Raspberry Pi 4B`
  - `Sixfab 4G/LTE Modem Kit`
  - `Telit LE910C4-NF (North America)`
  - `Hologram` physical SIM
  - `USB microphone`
  - `INA260`
  - fused `12V -> 5V` buck converter
  - weatherproof enclosure
- Added a concrete `Qty 1` pilot checkout list and updated cost band guidance.
- Locked the low-cost solar add-on choice for standalone nodes:
  - `Newpowa 50W` panel
  - `Newpowa 10A PWM` controller

### Why it changed

- The repo needed one explicit production-standard cellular stack rather than a menu of plausible modem options.
- The user is preparing to purchase hardware and needs a concrete pilot bill of materials.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Lessons learned

- For this codebase, hardware choice should follow the runtime assumptions first:
  Linux modem tooling, Python agent behavior, and OTA lifecycle matter more than radio cost alone.
- A GPIO/HAT modem stack pairs more cleanly with a USB microphone than with another Pi HAT audio path.

## Launch readiness + field BOM addition (2026-02-27)

### What changed

- Added dedicated bill-of-materials doc for the active v1 hardware profile:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/BOM.md`
  - covers incremental per-node hardware, cost bands, data-plan sizing, and BYO carrier prerequisites
- Linked BOM from startup and hardware docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/START_HERE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`

### Why it changed

- Field setup required a single purchase-and-assembly reference for SD flash to first telemetry,
  scoped to the current microphone+power runtime profile.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`188 passed`)
- `pre-commit run --all-files` ✅

### Lessons learned

- A focused BOM file reduces ambiguity compared to a broad hardware catalog when preparing first field installs.
- Separating "incremental spend" from "already-owned hardware" makes planning faster and avoids overbuying.

## OTA admin UI + launch checklist polish (2026-02-27)

### What changed

- Added OTA admin UI client/types/endpoints in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
- New UI capability:
  - create/list release manifests
  - create deployments with selector/stage config
  - lookup deployment detail with pause/resume/abort controls
  - show deployment counters and recent events
- Added field launch tutorial:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TUTORIALS/RPI_FLASH_ASSEMBLE_LAUNCH_CHECKLIST.md`
- Updated start docs link:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/START_HERE.md`

### Why it changed

- Closed the operator gap between backend OTA APIs and day-to-day fleet operations.
- Added a single practical checklist for flash/assemble/first launch readiness.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅
- `pre-commit run --all-files` ✅

### Lessons learned

- OTA rollout ergonomics improve materially when manifest/deployment controls are exposed directly in admin UI.
- A single end-to-end launch checklist reduces missed env/power/guard settings during first hardware deployments.

## EdgeWatch OTA fleet platform: signed manifests + staged deployments (2026-02-27)

### What changed

- Added OTA persistence + rollout state schema:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0014_release_deployments_ota.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
  - new tables:
    - `release_manifests`
    - `deployments`
    - `deployment_targets`
    - `device_release_state`
    - `deployment_events`
  - extended `devices` with rollout targeting metadata:
    - `cohort`
    - `labels`
- Added OTA domain service and APIs:
  - service:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/device_updates.py`
  - device report route:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_updates.py`
    - `POST /api/v1/device-updates/{deployment_id}/report`
  - admin endpoints:
    - `POST /api/v1/admin/releases/manifests`
    - `GET /api/v1/admin/releases/manifests`
    - `POST /api/v1/admin/deployments`
    - `GET /api/v1/admin/deployments/{deployment_id}`
    - `POST /api/v1/admin/deployments/{deployment_id}/pause`
    - `POST /api/v1/admin/deployments/{deployment_id}/resume`
    - `POST /api/v1/admin/deployments/{deployment_id}/abort`
  - dark-launch gate:
    - `ENABLE_OTA_UPDATES` in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
    - ingest route registration in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`
- Extended device policy contract shape delivered to agents:
  - `pending_update_command` added in:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_policy.py`
  - policy ETag now includes pending update command fragment.
- Extended agent policy/runtime for OTA:
  - parser + cache support:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/device_policy.py`
  - runtime flow:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - behaviors:
    - update state reporting pipeline
    - power-guard defer reporting
    - dry-run apply default (`EDGEWATCH_ENABLE_OTA_APPLY=0`)
    - optional git-tag apply/rollback path when explicitly enabled
  - env docs:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
- Added OTA tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_updates_service.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_updates_routes.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_admin_deployments.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_update_delivery.py`
  - plus updates to migration/policy/route-surface suites.
- Added OTA docs/tutorial/ADR:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/OTA_UPDATES.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TUTORIALS/FLEET_DEPLOYMENTS_AND_ROLLBACK.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DECISIONS/ADR-20260227-rpi-fleet-ota-signed-manifests.md`
  - updated domain/design/contracts/start/deploy docs.

### Why it changed

- Required Particle-inspired fleet capability for RPi-first deployments:
  - durable staged OTA command delivery
  - auditability
  - safe rollout progression with halt-on-failure behavior
  - device-side power guard enforcement before apply

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`188 passed`)
- `pre-commit run --all-files` ✅

### Risks / rollout notes

- OTA admin routes are gated by `ENABLE_OTA_UPDATES`; keep disabled until pilot readiness.
- Agent apply path is dry-run by default; real filesystem switching requires explicit `EDGEWATCH_ENABLE_OTA_APPLY=1`.
- Apply/rollback path assumes valid repository/tag layout on the device; pilot with rollback drills before broad rollout.

### Lessons learned

- A dark-launch flag at route registration time plus runtime checks keeps additive features safe for existing deployments.
- Including pending-command state in policy ETag is critical for eventual-consistency delivery under long cache lifetimes.
- Power guard defer reporting should be throttled to avoid noise while still giving operators clear rollout health signals.

## EdgeWatch mainline finalization: hybrid disable safeguards (2026-02-27)

### What changed

- Closed remaining hybrid-disable gap in API/device policy/agent/web:
  - admin-only shutdown enqueue route: `/api/v1/admin/devices/{device_id}/controls/shutdown`
  - pending command schema includes:
    - `shutdown_requested`
    - `shutdown_grace_s`
  - edge policy operation defaults include:
    - `admin_remote_shutdown_enabled`
    - `shutdown_grace_s_default`
- Added agent-side shutdown execution guard:
  - local env `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN` (default off)
  - guard-off behavior: command still applies logical disable and acks
  - guard-on behavior: ack + grace window + one-shot shutdown command execution
- Updated admin/device UI controls:
  - owner/operator keep logical disable flow
  - admin can queue disable + shutdown intent
  - controls surfaces now show pending shutdown markers
- Documented hybrid semantics + BYO cellular hardening in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DESIGN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_RPI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/START_HERE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/POWER.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CELLULAR.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TUTORIALS/RPI_ZERO_TOUCH_BOOTSTRAP.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TUTORIALS/OWNER_CONTROLS_AND_COMMAND_DELIVERY.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TUTORIALS/BYO_CELLULAR_PROVIDER_CHECKLIST.md`
  - ADR update: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DECISIONS/ADR-20260227-durable-control-command-delivery.md`

### Why it changed

- Product requirement was hybrid disable:
  - owner/operator logical disable remains safe default
  - admin gets optional one-shot shutdown path for hard stops
- Safety requirement was explicit: no remote OS shutdown unless the device is locally opted in.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`175 passed`)
- `make tf-check` ✅ (tooling passed; baseline checkov findings remain soft-fail in this lane)

### Risks / rollout notes

- Misconfigured guard (`EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1` where not intended) can enable remote power-off.
- Keep policy gate `admin_remote_shutdown_enabled=true/false` controlled per environment during rollout.
- Pilot hardware should verify shutdown grace behavior before broad fleet rollout.

### Lessons learned

- Hybrid-control features need both server-side RBAC and device-side execution guard to be safe in intermittent links.
- Pending-command UX must surface shutdown intent explicitly, otherwise operators cannot distinguish logical disable from true power-off intent.

## EdgeWatch mainline: durable command queue + mic sustain + RPi minimal profile (2026-02-27)

### What changed

- Verified checkpoint branch state and continued on `main`:
  - `codex/full` exists locally and on `origin`.
- Added durable remote control command delivery (6-month TTL):
  - migration `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0013_device_control_commands.py`
  - ORM + relationships in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
  - queue lifecycle service in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/device_commands.py`
  - controls enqueue/supersede wiring in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_controls.py`
  - pending command delivery + ETag fragmenting in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_policy.py`
  - device ack endpoint in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_commands.py`
- Extended policy/contracts for locked defaults:
  - `control_command_ttl_s=15552000` in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/edge_policy/v1.yaml`
  - microphone sustain defaults:
    - `microphone_offline_open_consecutive_samples=2`
    - `microphone_offline_resolve_consecutive_samples=1`
  - simulator/UI profile metadata in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`:
    - `profiles.rpi_microphone_power_v1`
- Updated API schemas/routes for pending command visibility:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/contracts.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
  - controls output now includes `pending_command_count` and `latest_pending_command_expires_at`.
- Updated agent apply-once + ack-retry behavior:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/device_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - durable local state tracks `last_applied_command_id` and pending ack intent.
- Updated microphone offline lifecycle logic to sustain windows:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/monitor.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/ingestion_runtime.py`
- Set simulator/UI default profile to microphone + power:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/jobs/simulate_telemetry.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`
  - legacy metrics remain available via simulator profile opt-in.
- Added/updated docs, tutorials, and ADRs:
  - ADR: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DECISIONS/ADR-20260227-durable-control-command-delivery.md`
  - core docs:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DESIGN.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - runbooks:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_RPI.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/POWER.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SIMULATION.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CELLULAR.md`
  - tutorials:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TUTORIALS/RPI_ZERO_TOUCH_BOOTSTRAP.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TUTORIALS/OWNER_CONTROLS_AND_COMMAND_DELIVERY.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TUTORIALS/BYO_CELLULAR_PROVIDER_CHECKLIST.md`

### Why it changed

- Devices can be offline for long periods (sleep/offseason/cellular gaps), so remote controls need durable, eventual delivery with explicit acknowledgement.
- The field-first profile should prioritize microphone + power while keeping existing metrics additive for future expansion.
- Offline alert semantics now match sustained low sound behavior (2 consecutive low polls before open).

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`171 passed`)
- `make tf-check` ✅ (static checks run; checkov baseline findings still soft-fail in this lane)

### Risks / rollout notes

- Additive API/contract change: older agents continue to function but only newer agents apply/ack durable pending commands.
- Disabled mode remains logical latch; service restart on-device is still required to resume.
- Operators should monitor pending command age during rollout to catch devices that remain disconnected past expected windows.

### Lessons learned

- SQLite file-size enforcement is page-granular; quota tests need a one-page tolerance to avoid platform-specific flakiness.
- Pending command state must be part of policy ETag inputs; otherwise devices can miss control changes while payload cache appears unchanged.
- A local durable ack-intent state file on agent is necessary to make command application resilient across power cycles and network outages.

## EdgeWatch v1: ownership + controls + prod simulation opt-in (2026-02-27)

### What changed

- Git checkpoint workflow:
  - created and pushed `codex/full` from current `main` (checkpoint branch)
- Added strict per-device ownership model with additive schema:
  - migration `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0012_device_controls_and_access_grants.py`
  - model/table updates in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
  - access service in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/device_access.py`
- Added owner/operator control APIs:
  - `/api/v1/devices/{device_id}/controls`
  - `/api/v1/devices/{device_id}/controls/operation`
  - `/api/v1/devices/{device_id}/controls/alerts`
  - implementation: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_controls.py`
- Added admin ownership grant APIs:
  - `/api/v1/admin/devices/{device_id}/access`
  - `/api/v1/admin/devices/{device_id}/access/{principal_email}` (PUT/DELETE)
  - implementation: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
- Enforced ownership on read surfaces when `AUTHZ_ENABLED=1`:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/alerts.py`
- Extended device state/output and policy:
  - status now supports `sleep` and `disabled`
  - new device fields: `operation_mode`, `sleep_poll_interval_s`, `alerts_muted_until`, `alerts_muted_reason`
  - policy fields: `operation_mode`, `sleep_poll_interval_s`, `disable_requires_manual_restart`
  - key files:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_policy.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/edge_policy.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/device_policy.py`
- Implemented sleep/disable runtime behavior in agent:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - `sleep`: long-cadence telemetry polling, media disabled
  - `disabled`: local latch; telemetry/media paused until local restart
- Added alert mute routing behavior (notifications-only suppression):
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/routing.py`
- Added simulator prod opt-in and richer RPi-first payloads:
  - runtime guard in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/jobs/simulate_telemetry.py`
  - new env/config: `SIMULATION_ALLOW_IN_PROD`
  - generated metrics now include microphone + power keys
- Terraform simulation opt-in controls:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/variables.tf`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/jobs.tf`
  - prod profiles updated under `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles`
- UI updates:
  - device owner controls in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - admin ownership management in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
  - updated client contracts in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
  - status handling (`sleep|disabled`) across fleet views
- Documentation + decisions:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DESIGN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_RPI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/POWER.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SIMULATION.md`
  - ADRs:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DECISIONS/ADR-20260227-device-ownership-and-control-model.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DECISIONS/ADR-20260227-prod-simulation-opt-in.md`

### Why it changed

- Implemented strict ownership for non-admin users.
- Added operational controls for offseason/intermission behavior (mute/sleep/disable).
- Kept simulator usable across environments while making production simulation an explicit opt-in.
- Maintained additive compatibility for existing device payloads and policy consumers.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`160 passed`)
- `make tf-check` ✅ (known baseline policy findings remain soft-fail in local checkov lane)

### Risks / rollout notes

- Ownership enforcement is active only when `AUTHZ_ENABLED=1`; deployments with `AUTHZ_ENABLED=0` retain legacy permissive behavior.
- Disabled mode intentionally requires local restart; ensure runbooks for field technicians are in place.
- Production simulation remains off by default; enabling it requires both Terraform and runtime acknowledgement.

### Follow-ups / tech debt

- Add end-to-end API integration tests for control endpoints with real auth headers and grant matrices.
- Add UI tests for ownership management and device control flows.
- Seed/migrate ownership grants for existing fleets before enabling strict authz in stage/prod.

## Microphone-first RPi profile + checkpoint branch (2026-02-27)

### What changed

- Created a checkpoint branch from `main` and pushed it:
  - `full` -> `origin/full`
- Implemented an additive microphone telemetry path while preserving legacy sensors for future use:
  - Added `microphone_level_db` to `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
  - Added `microphone_offline_db` to `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/edge_policy/v1.yaml`
  - Set default polling cadence to 10 minutes in edge policy (`reporting.*_interval_s` defaults now `600`)
- Added Raspberry Pi microphone backend + config:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/rpi_microphone.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/config/rpi.microphone.sensors.yaml`
  - Wired backend parsing/building in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/config.py`
- Propagated policy/schema updates through API + agent policy contracts:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/edge_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/contracts.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/device_policy.py`
- Added microphone offline alert behavior at ingest time:
  - `MICROPHONE_OFFLINE` open when `microphone_level_db < microphone_offline_db`
  - `MICROPHONE_ONLINE` emitted on recovery
  - Implemented in:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/monitor.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/ingestion_runtime.py`
- Updated agent behavior to include microphone-aware heartbeat/delta handling and fallback defaults:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
- Extended mock telemetry and default summary metrics to surface microphone values:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/mock_sensors.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
- Added/updated tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_rpi_microphone.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_ingestion_runtime.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_device_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_policy.py`
- Updated docs for microphone-first RPi operation:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_RPI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SENSORS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/OFFLINE_CHECKS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RPI_AGENT.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/START_HERE.md`

### Why it changed

- Requested direction: minimal Raspberry Pi input schema centered on microphone telemetry.
- Required behavior: poll on a 10-minute default cadence and raise an offline signal when microphone level is not sustained above threshold (default 60).
- Constraint: keep existing sensor stack available for future use without removing contracts or code paths.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`133 passed`)

### Risks / rollout notes

- `rpi_microphone` backend depends on `arecord` (`alsa-utils`) being installed on Raspberry Pi nodes.
- `microphone_level_db` is an uncalibrated relative dB value from PCM amplitude; threshold tuning may vary by microphone hardware and gain settings.
- Edge policy default intervals now use 10-minute cadence globally (`600s`), which may be too slow for legacy pressure-first profiles unless adjusted.

### Follow-ups / tech debt

- Consider per-device profile overrides for sampling cadence (microphone-first vs pressure-first) to avoid one global default.
- Add a calibration helper/runbook for site-specific microphone threshold tuning.
- Optionally add sustained-window logic (consecutive low readings) if stricter “sustain” semantics are needed.

## Solar/12V dual-mode power management (2026-02-27)

### What changed

- Extended telemetry contract with additive power fields in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`:
  - `power_input_v`, `power_input_a`, `power_input_w`
  - `power_source`
  - `power_input_out_of_range`, `power_unsustainable`, `power_saver_active`
- Extended edge policy contract with `power_management` defaults in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/edge_policy/v1.yaml`.
- Added policy/schema plumbing (API + agent):
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/edge_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/contracts.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/device_policy.py`
- Added hardware power backend for INA219/INA260:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/rpi_power_i2c.py`
  - wired in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/config.py`
- Added dual-mode decision engine with durable rolling-window state:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/power_management.py`
  - integrated into `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - saver mode now degrades cadence and can suppress media while keeping microphone/offline path active
- Added ingest-driven power alert lifecycle:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/monitor.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/ingestion_runtime.py`
  - alert pairs: `POWER_INPUT_OUT_OF_RANGE`/`POWER_INPUT_OK`, `POWER_UNSUSTAINABLE`/`POWER_SUSTAINABLE`
- Added tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_rpi_power_i2c.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_power_management.py`
  - extended `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_ingestion_runtime.py`
  - extended `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_device_policy.py`
  - extended `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_policy.py`
- Updated docs + runbooks:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DESIGN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_RPI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/POWER.md`

### Why it changed

- Added explicit support for field deployments powered by solar or 12V well battery inputs.
- Required an additive v1 path that warns on out-of-range input and sustained unsustainable consumption.
- Kept response posture in v1 as `warn + degrade` (no automatic shutdown), preserving backward compatibility.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`151 passed`)

### Risks / rollout notes

- Hardware path depends on INA219/INA260 wiring and `smbus2`; failed reads degrade to `None` metrics with throttled warnings.
- Thresholds are conservative defaults for 12V lead-acid and may require site tuning.
- Power saver mode intentionally reduces send cadence and media activity; operators should expect lower telemetry granularity while active.

## Auto-deploy on main (2026-02-24)

### What changed

- Enabled automatic dev deploys on `main` pushes in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/.github/workflows/deploy-gcp.yml`
- `Deploy to GCP (Cloud Run)` now triggers on:
  - `push` to `main`
  - `workflow_dispatch` (manual)
- Added env fallback logic so one workflow supports both trigger modes:
  - `github.event.inputs.env || 'dev'` used for:
    - workflow concurrency group
    - job environment
    - deploy step `ENV`

### Why it changed

- Users expected hosted dev to update when merges land on `main`.
- Previously deploy was manual-only (`workflow_dispatch`), so CI could pass while hosted dev remained on an older revision.

### Validation

- `python scripts/harness.py all --strict` ✅

## CSP-safe theme bootstrap (2026-02-24)

### What changed

- Replaced inline theme bootstrap script in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/index.html`
- Added same-origin external bootstrap script:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/public/theme-init.js`

### Why it changed

- Hosted dev enforces CSP with `script-src 'self'`.
- Inline script execution was blocked in browser console.
- Moving theme init to an external script preserves strict CSP and removes the violation.

### Validation

- `python scripts/harness.py all --strict` ✅

## Dashboard map/device-create/admin polish (2026-02-23)

### What changed

- Map now plots all devices, not only those with telemetry coordinates:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/components/FleetMap.tsx`
  - devices without telemetry lat/lon now use deterministic fallback coordinates.
  - source label updated to `fallback location` (instead of demo-only wording).
- Fixed admin device creation when `display_name` is omitted:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
  - `AdminDeviceCreate.display_name` is optional; server falls back to `device_id`.
- Added regression test for omitted `display_name` create payload:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_admin_device_create.py`
- Removed dashboard environment pill/text (`env:dev`) from the header:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`
- Admin UI now always sends a concrete `display_name` on create:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`

### Why it changed

- Users expected offline/unknown/no-telemetry devices to still be visible on the fleet map.
- Creating a device without `display_name` produced HTTP 422 due required schema validation.
- Dashboard environment badge was requested to be removed.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (128 passed)

## Hosted dev device-list hardening (2026-02-23)

### What changed

- Added `safe_display_name(device_id, display_name)` in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/device_identity.py`
- Updated device serialization paths to use fallback `display_name`:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
- Added regression tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_identity.py`

### Why it changed

- Hosted dev returned HTTP 500 on `GET /api/v1/devices` because legacy rows had `display_name = NULL`.
- `DeviceOut.display_name` is a required string; direct serialization raised Pydantic validation errors.
- Fallback to `device_id` prevents endpoint-wide failure from a single malformed historical row.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (127 passed)

### Risks / rollout notes

- This is a defensive read-path fix; existing malformed rows are still present until explicitly backfilled.
- UI/API behavior remains stable; fallback display label is deterministic (`device_id`).

## CI IAM hardening + apply image guard (2026-02-23)

### What changed

- Tightened IAM for deploy CI service account `sa-edgewatch-ci@job-search-486101.iam.gserviceaccount.com`:
  - removed project-level `roles/storage.admin`
  - removed project-level `roles/viewer`
  - removed bucket-level `roles/storage.admin` from:
    - `gs://job-search-486101-tfstate`
    - `gs://job-search-486101_cloudbuild`
  - retained bucket-level `roles/storage.objectAdmin` on state/cloudbuild/config buckets for object read/write only.
- Hardened GCP workflows to avoid privileged fallbacks:
  - `/.github/workflows/terraform-apply-gcp.yml`
  - `/.github/workflows/deploy-gcp.yml`
  - `/.github/workflows/terraform-drift.yml`
  - `/.github/workflows/gcp-terraform-plan.yml`
  - all now require `GCP_TF_CONFIG_GCS_PATH` and always fetch `backend.hcl` + `terraform.tfvars` from GCS.
  - all workflow dispatch `tfvars` inputs were removed (strict GCS-only config source in CI).
  - all four workflows now share one cross-workflow concurrency group per env (`gcp-infra-<env>`) to serialize Terraform operations and avoid state-lock failures when users dispatch plan/apply/deploy together.
  - all now pass `TF_BACKEND_HCL=backend.hcl` so CI does not run tfstate bucket bootstrap requiring bucket-admin privileges.
- Prevented non-existent image usage in apply:
  - `terraform-apply-gcp` now accepts optional `image_tag` input.
  - if omitted, it resolves the latest existing Artifact Registry tag.
  - it verifies `IMAGE:TAG` exists before invoking `make apply-gcp`; fails fast with a clear error if not found.
- Cloud Build log-read permission workaround remains in `Makefile`:
  - `gcloud builds submit --suppress-logs --tag "$(IMAGE)" .`

### Why it changed

- The previous apply path could try to deploy an image tag that was never built in Artifact Registry.
- CI had temporary broad storage/viewer roles to get unstuck; those are now reduced while preserving deploy capability.
- Enforcing GCS-backed Terraform config keeps workflow behavior deterministic across envs and avoids bucket-admin operations during routine applies.
- Removing workflow `tfvars` inputs prevents accidental profile/path drift between local runs and CI deploy lanes.

### Validation

- IAM verification:
  - project roles for CI SA no longer include `roles/storage.admin` or `roles/viewer`.
  - tfstate/cloudbuild buckets now show only `roles/storage.objectAdmin` for CI SA.
- Harness:
  - `python scripts/harness.py lint` (fails on existing unrelated notification tests)
  - `python scripts/harness.py typecheck` (pass)
  - `python scripts/harness.py test` (fails on same 3 notification tests)
- Workflow YAML validation:
  - `pre-commit run check-yaml --files .github/workflows/terraform-apply-gcp.yml .github/workflows/deploy-gcp.yml .github/workflows/terraform-drift.yml .github/workflows/gcp-terraform-plan.yml` (pass)
- Reproduced/confirmed old remote workflow failure cause:
  - old `Terraform apply (GCP)` run failed in `bootstrap-state-gcp` due missing `storage.buckets.update` after IAM tightening.
  - local workflow fixes remove that fallback path by requiring `GCP_TF_CONFIG_GCS_PATH` + `TF_BACKEND_HCL`.

## What changed?

- Completed remaining Codex task specs across alerts, contracts/lineage, replay/backfill, and optional pipeline/analytics lanes.
- Added alert routing + delivery auditing:
  - New services: `api/app/services/routing.py`, `api/app/services/notifications.py`
  - New persistence: `alert_policies`, `notification_events`
  - Wired notifications into all server-side alert creation paths in `api/app/services/monitor.py`.
- Extended contract-aware ingest and lineage:
  - New ingest prep/runtime services: `api/app/services/ingest_pipeline.py`, `api/app/services/ingestion_runtime.py`
  - Ingest now supports unknown-key mode (`allow|flag`) and type mismatch mode (`reject|quarantine`).
  - Added drift/quarantine persistence: `drift_events`, `quarantined_telemetry`.
  - Enriched `ingestion_batches` with drift summary, source/pipeline metadata, and processing state.
  - Added audit endpoints in `api/app/routes/admin.py` (`/admin/drift-events`, `/admin/notifications`, `/admin/exports`).
- Added optional Pub/Sub ingest lane:
  - `INGEST_PIPELINE_MODE=direct|pubsub` handling in `api/app/routes/ingest.py`.
  - New internal worker endpoint: `api/app/routes/pubsub_worker.py`.
  - New Pub/Sub helper service: `api/app/services/pubsub.py`.
- Added optional BigQuery export lane:
  - New export service/job: `api/app/services/analytics_export.py`, `api/app/jobs/analytics_export.py`.
  - New `export_batches` lineage/audit model.
- Added replay/backfill tooling:
  - New agent CLI: `agent/replay.py` (time-bounded replay, batching, rate limiting, stable `message_id`).
- Added Alembic migration:
  - `migrations/versions/0004_alerting_pipeline.py`.
  - Fixed revision id length (`0004_alerting_pipeline`) to remain compatible with Alembic/Postgres `alembic_version.version_num` width.
- Improved local Docker resilience on constrained networks:
  - `Dockerfile` now installs `uv` in-image with increased pip timeout/retry settings.
- Added deterministic tests for new behavior:
  - `tests/test_ingest_pipeline.py`
  - `tests/test_routing.py`
  - `tests/test_pubsub_service.py`
  - `tests/test_analytics_export.py`
  - `tests/test_replay.py`
- Updated docs/runbooks/tasks/changelog/version:
  - Task status updates in `docs/TASKS/*` + `docs/TASKS/README.md`
  - New runbooks: `docs/RUNBOOKS/REPLAY.md`, `docs/RUNBOOKS/PUBSUB.md`, `docs/RUNBOOKS/ANALYTICS_EXPORT.md`
  - Contract/design/deploy/readme updates for new lanes and audit endpoints.
  - Version bump to `0.5.0` in `pyproject.toml`, changelog entry in `CHANGELOG.md`.

## Why?

- Deliver the remaining planned roadmap items while preserving non-negotiables:
  - idempotent ingest,
  - secret-safe logging,
  - cost-min and optional-by-default GCP features,
  - edge/runtime efficiency with replay recoverability.
- Improve production readiness with auditable routing, drift visibility, and operational runbooks.

## How was it validated?

- Commands run:
  - `python scripts/harness.py doctor` (pass)
  - `UV_NO_SYNC=1 python scripts/harness.py all --strict` (pass)
  - `ruff check api/app agent tests` (pass)
  - `pyright` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q` (pass, 27 tests)
  - `pnpm install` (pass)
  - `pnpm -r --if-present typecheck && pnpm -r --if-present build` (pass)
  - `terraform -chdir=infra/gcp/cloud_run_demo fmt -check -recursive` (pass)
  - `python scripts/harness.py all --strict` (pass)
  - `timeout 300 make tf-check` (still timed out during `terraform init -upgrade` provider download in this environment)
  - `make db-up` + `uv run --locked alembic upgrade head` (pass after migration id fix)
  - `make EDGEWATCH_DEVICE_ID=demo-well-010 EDGEWATCH_DEVICE_TOKEN=dev-device-token-010 demo-device` (pass)
  - `timeout 45 make EDGEWATCH_DEVICE_ID=demo-well-010 EDGEWATCH_DEVICE_TOKEN=dev-device-token-010 SIMULATE_FLEET_SIZE=1 simulate` (ran bounded smoke; ingest confirmed via API logs with HTTP 200)
- Tests added/updated:
  - Added unit tests covering routing decisions, drift/quarantine prep, pubsub payload handling, analytics export cursor/client behavior, and replay range/cursor behavior.

## Risks / rollout notes

- DB migration `0004_alerting_pipeline` must be applied before deploying app changes.
- Pub/Sub and analytics lanes remain **off by default** and require explicit Terraform vars.
- Harness strict pass here used `UV_NO_SYNC=1` to avoid environment sync hangs; CI remains protected by explicit `uv sync --all-groups --locked` in workflow.
- `make tf-check` could not fully complete locally due Terraform provider download stall/timeouts; rerun in CI or a network-stable environment.

## Follow-ups

- [ ] Re-run `make tf-check` in CI/runner with stable Terraform registry/network access.
- [ ] Optional hardening: add integration tests around pubsub worker persistence path with DB fixture.
- [ ] Optional hardening: add end-to-end smoke script for analytics export job + admin export audit endpoint.

## Follow-up Stabilization (2026-02-20)

### Additional changes

- Hardened Terraform local gates in `Makefile`:
  - `grant-cloudbuild-gcp` now uses `--condition=None` for non-interactive IAM binding.
  - `tf-policy` now evaluates only `*.tf` files (excludes `.terraform/*`) and pins `conftest --rego-version v0`.
- Fixed Terraform output compatibility:
  - `infra/gcp/cloud_run_demo/outputs.tf` now uses dashboard `.id` instead of unsupported `.name`.
- Fixed log sink IAM failure:
  - Removed invalid direct writer-member binding from `infra/gcp/cloud_run_demo/log_views.tf`.
- Improved startup resilience:
  - `api/app/main.py` skips demo bootstrap when schema is not yet ready (logs warning, no crash).
- Added SQLite migration portability for Cloud Run job/dev lanes:
  - Updated `migrations/versions/0001_initial.py`, `migrations/versions/0003_ingestion_batches.py`, `migrations/versions/0004_alerting_pipeline.py` to use dialect-aware JSON/defaults.
  - Added SQLite-safe guard for FK alter in `0003` (SQLite cannot alter constraints post-create).
  - Added regression test `tests/test_migrations_sqlite.py`.
- Updated docs to clarify deploy prerequisites:
  - `docs/DEPLOY_GCP.md`
  - `infra/gcp/cloud_run_demo/README.md`
  - Explicitly documents that `deploy-gcp-safe` needs shared DB (Cloud SQL/shared Postgres), not local SQLite file URLs.

### Validation run (follow-up)

- `python scripts/harness.py all --strict` ✅
- `make tf-check` ✅
- Local smoke equivalent ✅
  - `make db-up`
  - host API on `:8082`
  - `make demo-device` with unique id/token
  - bounded `make simulate` run
  - verified telemetry rows inserted for smoke device
- `make deploy-gcp-safe ENV=dev` ⚠️ partial
  - Cloud Build: success
  - Terraform apply: success
  - `migrate-gcp`: success (execution `edgewatch-migrate-dev-dgjxx`)
  - `verify-gcp-ready`: fails with `HTTP 503`, response `{"detail":"not ready: OperationalError"}`
  - Root cause: current `edgewatch-database-url` secret points to SQLite (`sqlite+pysqlite`), which is not a shared backend for Cloud Run service + migration job.

### Remaining operational follow-up

- [ ] Set `edgewatch-database-url` to a shared Postgres backend (Cloud SQL or equivalent), then rerun:
  - `make deploy-gcp-safe ENV=dev`

## Cloud SQL Terraform Wiring (2026-02-20)

### What changed

- Added a new reusable module:
  - `infra/gcp/modules/cloud_sql_postgres/`
  - provisions Cloud SQL Postgres instance + app database + app user
  - includes cost-min defaults and PostgreSQL log flags for tfsec compliance
- Wired Cloud SQL into Cloud Run service and jobs:
  - `infra/gcp/modules/cloud_run_service/main.tf`
  - `infra/gcp/modules/cloud_run_job/main.tf`
  - adds optional `/cloudsql` volume mount + `cloud_sql_instances` input
- Added Cloud SQL config surface in root module:
  - `infra/gcp/cloud_run_demo/variables.tf`
  - `infra/gcp/cloud_run_demo/main.tf`
  - `infra/gcp/cloud_run_demo/jobs.tf`
  - auto-manages `edgewatch-database-url` secret version when `enable_cloud_sql=true`
  - grants runtime SA `roles/cloudsql.client`
- Enabled SQL Admin API by default:
  - `infra/gcp/modules/core_services/variables.tf`
- Added Cloud SQL outputs:
  - `infra/gcp/cloud_run_demo/outputs.tf`
- Updated docs + profiles:
  - `docs/DEPLOY_GCP.md`
  - `infra/gcp/cloud_run_demo/README.md`
  - `infra/gcp/cloud_run_demo/profiles/README.md`
  - `infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars`
  - `infra/gcp/cloud_run_demo/profiles/prod_private_iam.tfvars`
- Terraform check stability:
  - `Makefile` `tf-validate` now uses `terraform init -backend=false` (no `-upgrade`) to avoid network-flaky inner-loop stalls.

### Validation run

- `make tf-check` ✅
- `python scripts/harness.py all --strict` ✅
- `make deploy-gcp-safe ENV=dev` ✅
  - Cloud SQL instance created: `edgewatch-dev-pg`
  - migration execution: `edgewatch-migrate-dev-9mwq7` (success)
  - readiness: `OK: /readyz`

### Remaining follow-up

- [ ] For production, set an explicit strong DB password via `TF_VAR_cloudsql_user_password` instead of relying on the derived fallback.

## Task 11a — Agent Sensor Framework + Config (2026-02-21)

### What changed

- Added a pluggable sensor framework under `agent/sensors/`:
  - `agent/sensors/base.py` defines the backend protocol and a safe wrapper that prevents sensor exceptions from crashing the agent loop.
  - `agent/sensors/config.py` adds YAML/env config parsing + validation and backend construction.
  - `agent/sensors/backends/mock.py` wraps the existing mock behavior behind the new interface.
  - `agent/sensors/backends/composite.py` supports backend composition and per-child graceful fallback.
  - `agent/sensors/backends/placeholder.py` provides explicit `None`-emitting placeholders for `rpi_i2c`, `rpi_adc`, and `derived` until Tasks 11b/11c/11d land.
- Wired `agent/edgewatch_agent.py` to the framework:
  - reads `SENSOR_CONFIG_PATH` and optional `SENSOR_BACKEND` override
  - fails fast on invalid config with a clear startup error
  - uses backend reads in the telemetry loop
- Added sensor config example:
  - `agent/config/example.sensors.yaml`
- Updated docs:
  - `agent/README.md` sensors section
  - `agent/.env.example` sensor env vars
  - task status updates in `docs/TASKS/11a-agent-sensor-framework.md` and `docs/TASKS/README.md`
- Added deterministic tests:
  - `tests/test_sensor_framework.py`

### Why it changed

- Establishes the required foundation for real Raspberry Pi backends without coupling hardware-specific reads to buffering/ingest logic.
- Preserves local-first behavior (`mock` default) while introducing validated, portable configuration.

### How it was validated

- Baseline before task (required by process):
  - `make doctor-dev` (pass)
  - `make harness` (fails on pre-existing repo-wide issues unrelated to Task 11a; see risks)
- Task-focused validation:
  - `python scripts/harness.py lint --only python` (blocked by existing `uv.lock` drift when harness enforces `uv run --locked`)
  - `make test` (same `uv run --locked` lockfile block)
  - `ruff check agent/edgewatch_agent.py agent/sensors tests/test_sensor_framework.py` (pass)
  - `pyright agent/edgewatch_agent.py agent/sensors tests/test_sensor_framework.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_sensor_framework.py` (pass)
  - `make harness` (rerun after changes; still blocked by existing unrelated failures)

### Risks / rollout notes

- `rpi_i2c`, `rpi_adc`, and `derived` are intentionally placeholders in this task and emit `None` metrics until their dedicated tasks land.
- Full-repo `make harness` is currently red due pre-existing unrelated failures in API and tooling paths; Task 11a changes are isolated to agent sensor framework scope.

### Follow-ups / tech debt

- [ ] Task 11b: replace `rpi_i2c` placeholder with real BME280 implementation.
- [ ] Task 11c: replace `rpi_adc` placeholder and use channel/scaling config in real conversions.
- [ ] Task 11d: replace `derived` placeholder with durable oil-life model + reset CLI.

## Task 11b — Raspberry Pi I2C (BME280 temp + humidity) (2026-02-21)

### What changed

- Added `rpi_i2c` backend implementation:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/rpi_i2c.py`
  - lazy `smbus2` import (no import-time failure on laptops/CI)
  - BME280 calibration + compensation logic for:
    - `temperature_c`
    - `humidity_pct`
  - robust fallback behavior:
    - sensor read failures return `None` values
    - warning logs are rate-limited to avoid spam loops
- Wired backend selection:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/config.py`
  - `rpi_i2c` now constructs a real backend (not placeholder)
  - supports config fields:
    - `sensor` (currently `bme280`)
    - `bus`
    - `address` (int or hex string)
    - `warning_interval_s`
- Updated backend exports:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/__init__.py`
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_rpi_i2c.py`
  - covers BME280 decoding, rounding, failure fallback, warning rate limiting, and config wiring
- Updated operator/dev docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SENSORS.md` (wiring + setup + sanity checks)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md` (backend status + smbus2 install)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example` (I2C backend env example)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/config/example.sensors.yaml` (commented `rpi_i2c` config block)
- Updated task status docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/11b-rpi-i2c-temp-humidity.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 11b by providing production-ready Pi I2C reads for temperature/humidity without breaking local-first developer lanes.
- Keeps dependency imports isolated so CI and non-Pi environments run without hardware libraries.

### How it was validated

- Required full-gate run:
  - `make harness` (fails on pre-existing repo-wide issues unrelated to this task, including existing API lint/type/test failures and repo hygiene `.DS_Store`)
- Task-focused validation:
  - `ruff check agent/sensors/backends/rpi_i2c.py agent/sensors/config.py tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py agent/sensors/backends/__init__.py` (pass)
  - `pyright agent/sensors/backends/rpi_i2c.py agent/sensors/config.py tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py agent/sensors/backends/__init__.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py` (pass)

### Risks / rollout notes

- Runtime on Raspberry Pi still requires installing `smbus2` in the device environment.
- Backend currently targets BME280 only; additional I2C sensors remain future work.

### Follow-ups / tech debt

- [ ] Add an explicit optional dependency group for Pi sensor runtime packages (`smbus2`) once lockfile/tooling drift is resolved.
- [ ] Extend `rpi_i2c` to support additional sensor families (for example SHT31) behind the same backend contract.

## Task 11c — Raspberry Pi ADC (ADS1115 pressures + levels) (2026-02-21)

### What changed

- Added pure scaling helpers for analog conversions:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/scaling.py`
  - includes linear mapping, clamp, current/voltage conversion, and reusable scaling config
- Added `rpi_adc` backend implementation:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/rpi_adc.py`
  - ADS1115 single-ended channel reads over I2C
  - per-channel conversion modes:
    - `current_4_20ma` (with shunt resistor)
    - `voltage`
  - per-channel scale mapping (`from` -> `to`) with clamping
  - optional median smoothing via `median_samples`
  - graceful degradation: failed channels return `None` while other channels continue
  - warning logs are rate-limited to avoid spam
- Wired `rpi_adc` into backend construction:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/config.py`
  - supports config keys:
    - `adc.type`, `adc.bus`, `adc.address`, `adc.gain`, `adc.data_rate`, `adc.median_samples`, `adc.warning_interval_s`
    - `channels.<metric>.channel/kind/shunt_ohms/scale/median_samples`
  - added default canonical channel map when `channels` is omitted:
    - `water_pressure_psi`, `oil_pressure_psi`, `oil_level_pct`, `drip_oil_level_pct`
- Updated backend exports:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/__init__.py`
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_scaling.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_rpi_adc.py`
  - updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_framework.py` for real `rpi_adc` backend behavior
- Updated operator/dev docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SENSORS.md` (ADS1115 config and run commands)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md` (`rpi_adc` support note)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example` (`SENSOR_BACKEND=rpi_adc` usage)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/config/example.sensors.yaml` (full ADC channel mapping example)
- Updated task status docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/11c-rpi-adc-pressures-levels.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 11c by delivering testable, configuration-driven ADS1115 ingestion for pressure/level metrics while keeping local non-Pi environments safe.
- Keeps conversion logic pure and unit-tested so scaling math can be verified without hardware.

### How it was validated

- Required full-gate run:
  - `make harness` (fails on pre-existing repo-wide issues unrelated to this task, including existing API lint/type/test failures and repo hygiene `.DS_Store`)
- Task-focused validation:
  - `ruff check agent/sensors/config.py agent/sensors/scaling.py agent/sensors/backends/rpi_adc.py tests/test_sensor_rpi_adc.py tests/test_sensor_scaling.py tests/test_sensor_framework.py agent/sensors/backends/__init__.py` (pass)
  - `pyright agent/sensors/config.py agent/sensors/scaling.py agent/sensors/backends/rpi_adc.py tests/test_sensor_rpi_adc.py tests/test_sensor_scaling.py tests/test_sensor_framework.py agent/sensors/backends/__init__.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_sensor_scaling.py tests/test_sensor_rpi_adc.py tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py` (pass)

### Risks / rollout notes

- Runtime on Raspberry Pi requires `smbus2` to access ADS1115.
- The backend currently targets ADS1115 only; other ADC models remain future work.

### Follow-ups / tech debt

- [ ] Add a dedicated optional dependency group for hardware sensor packages once lockfile/tooling drift is resolved.
- [ ] Consider per-metric warning throttles if field deployments need finer-grained channel diagnostics.

## Task 11d — Derived Oil Life + Reset CLI (2026-02-21)

### What changed

- Added durable oil-life state primitives:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/derived/oil_life.py`
  - state fields:
    - `oil_life_runtime_s`
    - `oil_life_reset_at`
    - `oil_life_last_seen_running_at`
    - `is_running`
  - atomic persistence with temp file + fsync + rename
  - reset helper + running-state inference + linear oil-life function
- Added derived backend implementation:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/derived.py`
  - computes `oil_life_pct` from durable runtime state
  - running detection order:
    - `pump_on` boolean when present
    - fallback to `oil_pressure_psi` hysteresis (`run_on_threshold`, `run_off_threshold`)
  - warning logs are rate-limited
- Enabled context-aware composition for derived metrics:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/composite.py`
  - composite now passes accumulated upstream metrics to backends that implement `read_metrics_with_context(...)`
- Wired `derived` backend into config builder:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/config.py`
  - supports config keys:
    - `oil_life_max_run_hours`
    - `state_path`
    - `run_on_threshold`
    - `run_off_threshold`
    - `warning_interval_s`
- Added reset/show CLI tool:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/tools/oil_life.py`
  - runnable as:
    - `python -m agent.tools.oil_life reset --state ...`
    - `python -m agent.tools.oil_life show --state ...`
- Updated exports/docs/examples:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/__init__.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/derived/__init__.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/config/example.sensors.yaml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SENSORS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/11d-derived-oil-life-reset.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_derived.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_oil_life_tool.py`
  - updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_framework.py`

### Why it changed

- Completes Task 11d by implementing a local-first, reboot-safe, manual-reset oil-life model aligned to ADR-20260220.
- Keeps derived logic composable with existing mock/I2C/ADC pipelines without changing route/service boundaries.

### How it was validated

- Required full-gate run:
  - `make harness` (fails on pre-existing repo-wide issues unrelated to this task, including existing API lint/type/test failures and repo hygiene `.DS_Store`)
- Task-focused validation:
  - `ruff check agent/sensors/backends/composite.py agent/sensors/backends/derived.py agent/sensors/derived/oil_life.py agent/sensors/config.py agent/tools/oil_life.py tests/test_sensor_derived.py tests/test_oil_life_tool.py tests/test_sensor_framework.py` (pass)
  - `pyright agent/sensors/backends/composite.py agent/sensors/backends/derived.py agent/sensors/derived/oil_life.py agent/sensors/config.py agent/tools/oil_life.py tests/test_sensor_derived.py tests/test_oil_life_tool.py tests/test_sensor_framework.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_sensor_derived.py tests/test_oil_life_tool.py tests/test_sensor_scaling.py tests/test_sensor_rpi_adc.py tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py` (pass)

### Risks / rollout notes

- Oil-life state path must be writable by the agent process.
- Runtime accumulation between samples is interval-based; long sample intervals can smooth short run/stop cycles.

### Follow-ups / tech debt

- [ ] Consider emitting a local audit event when reset is invoked (for optional future upload).
- [ ] Evaluate whether oil-life runtime should be checkpointed less frequently for flash-wear-sensitive deployments.

## Task 12a — Agent Camera Capture + Ring Buffer (2026-02-21)

### What changed

- Added the new media subsystem under:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/storage.py`
    - filesystem ring buffer for captured assets
    - per-asset JSON sidecar metadata (`device_id`, `camera_id`, `captured_at`, `reason`, `sha256`, `bytes`, `mime_type`)
    - max-byte enforcement with FIFO eviction
    - atomic writes (`temp + fsync + rename`) for both media bytes and sidecars
    - orphan/temp-file cleanup during scans
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/capture.py`
    - capture backend interface
    - `libcamera-still` backend implementation for photo capture MVP
    - in-process capture lock for one-camera-at-a-time serialization
    - camera id parser (`cam1..camN`)
    - service that captures + persists into the ring buffer
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/runtime.py`
    - env-driven media config loader (`MEDIA_ENABLED`, `CAMERA_IDS`, intervals, ring settings)
    - scheduled snapshot runtime loop (round-robin across configured camera IDs)
    - graceful unsupported-platform handling when `libcamera-still` is missing
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/__init__.py`
- Wired media runtime into the agent loop:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - loads media runtime when enabled
  - executes scheduled captures in-loop
  - logs capture success/failure without crashing telemetry path
- Added a manual capture CLI:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/tools/camera.py`
- Updated operator/developer docs and env examples:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CAMERA.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/12a-agent-camera-capture-ring-buffer.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
- Added deterministic tests for media behavior:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_media_ring_buffer.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_media_runtime.py`

### Why it changed

- Completes Task 12a by shipping the device-side camera lane foundation:
  - snapshot capture
  - serialized camera access
  - durable local media ring buffer with bounded disk usage
  - stable module interfaces for upcoming 12b/12c integration

### How it was validated

- Required full-gate run:
  - `make harness` (fails on pre-existing repo-wide issues unrelated to Task 12a, including repo hygiene `.DS_Store` and existing API lint/type/test failures)
- Task-specific validation:
  - `ruff format agent/edgewatch_agent.py agent/media agent/tools/camera.py tests/test_media_ring_buffer.py tests/test_media_runtime.py` (pass)
  - `ruff check agent/edgewatch_agent.py agent/media agent/tools/camera.py tests/test_media_ring_buffer.py tests/test_media_runtime.py` (pass)
  - `pyright agent/edgewatch_agent.py agent/media agent/tools/camera.py tests/test_media_ring_buffer.py tests/test_media_runtime.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_media_ring_buffer.py tests/test_media_runtime.py` (pass)
- Spec validation command status:
  - `make fmt` (fails due existing repo-wide pre-commit/hygiene issues outside Task 12a scope; unrelated file edits were reverted before commit)

### Risks / rollout notes

- Media capture currently depends on `libcamera-still`; when missing, media setup is disabled with a clear log message while telemetry continues.
- Scheduled capture currently uses `reason=scheduled` only in-agent; alert-transition/manual trigger plumbing is intentionally deferred to later tasks.
- Ring buffer eviction is byte-bound and FIFO by `captured_at`; operators should size `MEDIA_RING_MAX_BYTES` to keep the desired local retention window.

### Follow-ups / tech debt

- [ ] Task 12b: wire this media lane into API metadata + upload flow.
- [ ] Add integration tests that exercise end-to-end capture on Raspberry Pi hardware in CI-adjacent smoke lanes.

## Task 12b — API Media Metadata + Storage (2026-02-21)

### What changed

- Added media persistence model + migration:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0007_media_objects.py`
  - new `media_objects` table with idempotency key `(device_id, message_id, camera_id)`, metadata fields, storage pointers, and upload timestamp.
- Added media storage config surface:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/.env.example`
  - supports `MEDIA_STORAGE_BACKEND=local|gcs`, local root path, GCS bucket/prefix, and max upload bytes.
- Added media service layer (business logic kept out of routes):
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/media.py`
  - deterministic object pathing (`<device>/<camera>/<YYYY-MM-DD>/<message>.<ext>`)
  - idempotent metadata create/get with conflict detection
  - payload integrity checks (declared bytes, SHA-256, content type)
  - local filesystem store and GCS store adapters.
- Added API route surface:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/media.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`
  - endpoints:
    - `POST /api/v1/media`
    - `PUT /api/v1/media/{media_id}/upload`
    - `GET /api/v1/devices/{device_id}/media`
    - `GET /api/v1/media/{media_id}`
    - `GET /api/v1/media/{media_id}/download`
  - device-auth scoped; device cannot access other device media.
- Added schemas/tests/docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_media_service.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_models.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_migrations_sqlite.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CAMERA.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docker-compose.yml` now mounts `/app/data/media` via `edgewatch_media` volume.
- Added runtime dependency for cloud storage:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pyproject.toml`
  - lock refresh in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/uv.lock`.
- Updated task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/12b-api-media-metadata-storage.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 12b by shipping the API-side media lane needed for camera capture workflows:
  - durable metadata,
  - idempotent create semantics,
  - configurable local/GCS storage backends,
  - authenticated listing and retrieval for downstream UI work (Task 12c).

### How it was validated

- Required full-gate run:
  - `make harness` (fails on existing repo-wide baseline issues unrelated to Task 12b; also auto-edits unrelated files, which were reverted before commit)
- Task-focused validation:
  - `ruff format api/app/config.py api/app/main.py api/app/models.py api/app/schemas.py api/app/routes/media.py api/app/services/media.py tests/test_media_service.py tests/test_models.py tests/test_migrations_sqlite.py migrations/versions/0007_media_objects.py` (pass)
  - `ruff check api/app/routes/media.py api/app/services/media.py api/app/models.py api/app/schemas.py tests/test_media_service.py tests/test_models.py tests/test_migrations_sqlite.py migrations/versions/0007_media_objects.py` (pass)
  - `pyright api/app/routes/media.py api/app/services/media.py api/app/models.py api/app/schemas.py tests/test_media_service.py tests/test_models.py tests/test_migrations_sqlite.py migrations/versions/0007_media_objects.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_media_service.py tests/test_models.py tests/test_migrations_sqlite.py` (pass)
  - `uv sync --all-groups --locked` (pass after lock refresh)

### Risks / rollout notes

- `make harness` currently remains red on pre-existing repo-wide failures outside this task scope (including existing API/infra files not modified by 12b).
- For Cloud Run deployments with `MEDIA_STORAGE_BACKEND=gcs`, runtime identity must have bucket write/read permissions for the configured `MEDIA_GCS_BUCKET`.
- Current download behavior proxies bytes through the API; signed URL optimization can be layered later if needed.

### Follow-ups / tech debt

- [ ] Task 12c: implement dashboard media gallery against the new `/api/v1/media` endpoints.
- [ ] Add route-level integration tests for media endpoints (auth matrix + response envelopes) once baseline main-route test lane is stabilized.

## Task 12b — CI Harness Stabilization Follow-up (2026-02-21)

### What changed

- Fixed repo-wide Python issues that blocked `harness` in CI:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`
    - added missing `os` import used for OTEL service name
    - tightened exception payload typing to satisfy pyright
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
    - fixed `status` unbound bug by avoiding local variable shadowing
    - corrected metric filtering typing issues
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/middleware/limits.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/rate_limit.py`
    - moved module docstrings ahead of imports to satisfy `ruff` E402
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/scripts/package_dist.py`
    - removed import-order violation by loading `api/app/version.py` via `importlib` instead of path mutation + late import
- Fixed CI environment gap for Terraform hook:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/.github/workflows/ci.yml`
  - added `hashicorp/setup-terraform@v3` (`1.14.5`) before running `python scripts/harness.py all --strict`
- Fixed Terraform hygiene Docker fallback pathing:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile`
  - `tf-lint` now mounts `infra/gcp` (parent) and runs in `cloud_run_demo` so `../modules/*` resolves correctly when `tflint` is run via Docker in CI.
  - Docker fallback now runs `tflint --init && tflint` in a single container invocation so plugin initialization is available to the lint step.
- Fixed Node typecheck blockers reached once Python/Terraform gates were green:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx` (severity type narrowing)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx` (missing `fmtAlertType` import)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/package.json` + `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pnpm-lock.yaml` (added `lucide-react`)
- Included repository-wide formatting drift fixes produced by pre-commit/terraform fmt (docs, infra tf/tfvars, and Python formatting-only files) so CI no longer auto-modifies files and fails.

### Why it changed

- Task 12b PR could not merge because required `harness` check was red from baseline repository issues unrelated to the media feature itself.
- This follow-up makes the PR mergeable and restores deterministic CI behavior for the repo gate.

### How it was validated

- `uv run --locked pre-commit run --all-files` ✅
- `make tf-lint` ✅
- `pnpm -r --if-present typecheck` ✅
- `make harness` ✅
  - includes:
    - pre-commit hooks
    - `ruff` format/check
    - `pyright`
    - `pytest` (77 passed)
    - `terraform fmt` under `infra/gcp`
    - web build/type lanes

### Risks / rollout notes

- This follow-up includes broad formatting-only churn in infra/docs files due existing drift; no functional Terraform behavior changes were introduced by `terraform fmt`.
- CI now depends on an explicit Terraform install step in the harness workflow, aligned with the other Terraform workflows in this repo.

### Follow-ups / tech debt

- [ ] Consider splitting harness into language/tool lanes if future failures in one ecosystem should not block unrelated task PRs.
- [ ] Consider pin-refresh for `pre-commit` hooks (`pre-commit-hooks` deprecation warning about legacy stages) in a dedicated maintenance PR.

## Task 12c — Web Media Gallery (2026-02-21)

### What changed

- Added media API client surface for the web app:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
  - new `MediaObjectOut` type
  - new media helpers:
    - `api.media.list(deviceId, { token, limit })`
    - `api.media.downloadPath(mediaId)`
    - `api.media.downloadBlob(mediaId, token)`
  - download requests use `cache: 'no-store'` to avoid stale signed/proxied URL behavior.
- Implemented a production-ready **Media** tab in device detail:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - replaced the old camera placeholder tab with:
    - per-device media token input (device-auth scoped API compatibility)
    - camera filter (`all`, `cam1..cam4`, plus discovered camera IDs)
    - latest-by-camera cards (`cam1..cam4`)
    - media grid with preview thumbnails
    - full-resolution open modal
    - “Copy link” action for operator sharing
    - skeleton loading states and error toasts
    - empty-state messaging when token/media is absent
- Updated web docs and task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/12c-web-media-gallery.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 12c by connecting the shipped 12b media API to the operator UI with practical gallery workflows:
  - latest capture visibility by camera,
  - full-res asset inspection,
  - operator-friendly filtering and sharing actions.

### How it was validated

- Task-specific validation from the spec:
  - `pnpm -r --if-present build` ✅
  - `pnpm -C web typecheck` ✅
  - `make test` ✅
- Required repo gate:
  - `make harness` ✅

### Risks / rollout notes

- Media endpoints currently require device bearer tokens; the UI stores per-device token locally in the browser for operator convenience.
- Thumbnail rendering currently uses downloaded blobs from the full media endpoint (no dedicated thumbnail service yet), so very large image sets can increase client bandwidth usage.

### Follow-ups / tech debt

- [ ] Add server-generated thumbnail derivatives for lower-bandwidth gallery rendering.
- [ ] Add IAM/IAP-aware operator media access path to avoid browser-side device token handling in hardened production deployments.

## Task 13a — Cellular Runbook (LTE modem + SIM bring-up) (2026-02-21)

### What changed

- Rewrote and expanded the cellular runbook into a field-ready technician procedure:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CELLULAR.md`
  - includes:
    - hardware option guidance (LTE HAT vs USB modem vs external router)
    - fresh Pi prerequisites (`ModemManager`, `NetworkManager`, tooling)
    - SIM/APN bring-up with concrete `mmcli`/`nmcli` commands
    - registration/signal/DNS/egress verification commands
    - EdgeWatch validation checks after link bring-up
    - common failure playbook with command sets and expected healthy/failure outputs
    - a field “before leaving site” checklist
    - escalation diagnostics bundle to collect for support.
- Updated hardware recommendations for LTE selection guidance:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`
  - clarified LTE deployment options and when to choose each.
- Updated task status tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13a-cellular-runbook.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 13a by delivering a documentation-first, operator-executable LTE bring-up runbook with concrete diagnostics for real field failures.

### How it was validated

- `uv run --locked pre-commit run --all-files` ✅
- `make harness` ✅

### Risks / rollout notes

- Commands in the runbook are intentionally carrier-agnostic; exact APN names and SIM provisioning rules remain carrier-specific.
- Modem output fields can vary slightly across modem firmware versions; the runbook focuses on state/registration semantics that remain consistent.

### Follow-ups / tech debt

- [ ] Task 13c: enforce policy-driven cellular cost caps for media + telemetry. (completed in next section)

## Task 13b — Agent Cellular Metrics + Link Watchdog (2026-02-21)

### What changed

- Added a new agent cellular observability module:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/cellular.py`
  - includes:
    - optional env-driven enablement (`CELLULAR_METRICS_ENABLED=true`)
    - best-effort ModemManager (`mmcli`) metric collection
    - parsed metrics:
      - `signal_rssi_dbm`
      - `cellular_rsrp_dbm`
      - `cellular_rsrq_db`
      - `cellular_sinr_db`
      - `cellular_registration_state`
    - lightweight connectivity watchdog (DNS + HTTP HEAD/GET fallback):
      - `link_ok`
      - `link_last_ok_at`
    - best-effort daily byte counters from Linux interface statistics:
      - `cellular_bytes_sent_today`
      - `cellular_bytes_received_today`
- Wired cellular monitor into the main edge loop:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - startup now validates cellular env config and reports `cellular=enabled|disabled`.
  - collected cellular metrics are merged into telemetry payloads when enabled.
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_cellular.py`
  - covers:
    - env parsing/validation
    - modem/watchdog parsing
    - daily usage counter behavior
    - non-Pi/mmcli-missing safety
- Updated contracts/docs/runbooks:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CELLULAR.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`
- Updated task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13b-agent-cellular-metrics-watchdog.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13-cellular-connectivity.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 13b by adding field-focused cellular link observability while keeping local development and CI environments runnable without modem tooling.

### How it was validated

- `make harness` ✅
- Focused test lane:
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_agent_cellular.py` ✅

### Risks / rollout notes

- Cellular metrics are best-effort and depend on modem/driver output shape; unavailable fields are omitted.
- Daily byte counters currently reset on agent restart (acceptable for best-effort telemetry; Task 13c introduces policy-enforced counters/audit).

### Follow-ups / tech debt

- [ ] Validate full end-to-end media upload counters once device-side upload lane is implemented.

## Task 13c — Cost Caps in Edge Policy (2026-02-21)

### What changed

- Extended edge policy contract with `cost_caps`:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/edge_policy/v1.yaml`
  - new fields:
    - `max_bytes_per_day`
    - `max_snapshots_per_day`
    - `max_media_uploads_per_day`
- Wired `cost_caps` through API policy loaders and response schemas:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/edge_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/contracts.py`
- Extended agent policy parsing/cache with cost caps:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/device_policy.py`
- Added durable cost-cap counter module:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/cost_caps.py`
  - persists UTC-day counters across restart:
    - bytes sent
    - snapshots captured
    - media upload units
- Integrated enforcement into agent runtime:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - behavior:
    - heartbeat-only telemetry mode once `max_bytes_per_day` is reached
    - skip scheduled media capture when snapshot/upload caps are reached
    - telemetry/log audit metrics:
      - `cost_cap_active`
      - `bytes_sent_today`
      - `media_uploads_today`
      - `snapshots_today`
  - fallback policy now includes cost-cap env defaults when policy fetch is unavailable.
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_cost_caps.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_device_policy.py`
  - updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_policy.py`
- Updated telemetry contract discoverability/docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/COST_HYGIENE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CELLULAR.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
- Updated task status tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13c-cost-caps-policy.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13-cellular-connectivity.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 13c by making cellular consumption predictable via policy-driven, durable daily caps with explicit audit visibility.

### How it was validated

- `make harness` ✅
- Focused test lanes:
  - `DATABASE_URL=sqlite+pysqlite:///:memory: uv run --locked pytest -q tests/test_agent_cost_caps.py tests/test_agent_device_policy.py tests/test_device_policy.py` ✅

### Risks / rollout notes

- Current media pipeline captures locally (Task 12a); to stay conservative, each scheduled capture currently increments the media upload unit counter.
- Byte counters are agent-accounted payload estimates (telemetry JSON body size), not carrier-billed octets.

### Follow-ups / tech debt

- [ ] When device-side media upload lane is enabled, wire upload-complete callbacks to increment media upload counters on actual upload success.

## Task 14 (Iteration) — Devices List UX Polish (2026-02-21)

### What changed

- Polished Devices page quick filtering and status clarity:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx`
  - added quick filter toggle for `open alerts only` (in addition to online/offline/unknown status filters)
  - added per-device health explanation labels/details for:
    - offline (stale telemetry threshold context)
    - stale heartbeat
    - weak signal
    - low battery
    - open alerts
    - awaiting telemetry / healthy
  - added open-alert indicators in the table status column and fleet summary counts
  - improved empty-state guidance with actionable next steps and clear-filter affordance.
- Updated web API contract typing to include edge-policy cost caps:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
- Updated UI/task docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/14-ui-ux-polish.md`

### Why it changed

- Advances Task 14’s remaining Devices-list goals: clearer status explanations, better empty states, and operator-friendly quick filters including open-alert focus.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -r --if-present build` ✅
- `make harness` ✅

### Risks / rollout notes

- The open-alert device filter currently derives from `GET /api/v1/alerts?open_only=true&limit=1000`; extremely large fleets may need a dedicated aggregate endpoint in a future iteration.

### Follow-ups / tech debt

- [ ] Complete remaining Task 14 work for IAP operator posture UX after Task 18 lands.

## Task 18 — IAP identity perimeter (2026-02-21)

### What changed

- Added app-level IAP defense-in-depth and admin attribution:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
    - new `IAP_AUTH_ENABLED` setting
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/security.py`
    - `require_admin` now accepts `X-Goog-Authenticated-User-Email`
    - when `IAP_AUTH_ENABLED=true`, admin requests without an IAP identity header return `401`
    - returns normalized acting principal for audit attribution
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
    - device create/update mutations now persist admin audit events with acting principal + request id
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/admin_audit.py`
    - centralized admin audit persistence + structured `admin_event` logs
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
    - added `admin_events` model/table mapping
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0008_admin_events.py`
    - Alembic migration for `admin_events`
- Added Terraform IAP perimeter support for split dashboard/admin Cloud Run services:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/iap.tf`
    - serverless NEGs + HTTPS LB resources + IAP backend config + allowlist IAM bindings
    - Cloud Run invoker binding for IAP service account
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/variables.tf`
    - new `enable_{dashboard,admin}_iap` controls
    - domain, OAuth client, and allowlist variables + validation guardrails
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/main.tf`
    - stable service-name locals
    - admin service sets `IAP_AUTH_ENABLED=true` when admin IAP is enabled
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/iam_bindings.tf`
    - avoids direct group `run.invoker` grants on services when IAP is enabled
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/outputs.tf`
    - new `dashboard_iap_url` and `admin_iap_url` outputs
  - profile examples updated with commented IAP variable blocks.
- Updated docs and task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_GCP.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/security.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/PRODUCTION_POSTURE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/18-iap-identity-perimeter.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`

### Why it changed

- Completes Task 18 acceptance criteria:
  - supports Google-login IAP perimeter for dashboard/admin services
  - supports principal/group allowlists
  - records acting principal on admin mutations with structured auditability
  - adds app-level checks so admin routes fail closed when IAP identity headers are absent

### How it was validated

- Focused validation:
  - `uv run --locked ruff check api/app/config.py api/app/security.py api/app/main.py api/app/models.py api/app/routes/admin.py api/app/services/admin_audit.py tests/test_security.py tests/test_migrations_sqlite.py tests/test_admin_audit.py migrations/versions/0008_admin_events.py` ✅
  - `DATABASE_URL=sqlite+pysqlite:///:memory: uv run --locked pytest -q tests/test_security.py tests/test_migrations_sqlite.py tests/test_admin_audit.py` ✅
  - `terraform -chdir=infra/gcp/cloud_run_demo fmt -recursive` ✅
- Full-repo validation:
  - `make harness` (see PR notes for result)
  - `make tf-fmt`
  - `make tf-validate`

### Risks / rollout notes

- IAP requires DNS and a valid OAuth client for each enabled service before users can log in successfully.
- Enabling IAP while leaving direct Cloud Run invoker grants in place can bypass the IAP layer; this change avoids that for dashboard/admin service group bindings.
- `IAP_AUTH_ENABLED` currently guards admin endpoints; dashboard/read endpoints remain perimeter-only (IAP + IAM) without additional app header enforcement, which is expected for Task 18.

### Follow-ups / tech debt

- [ ] Task 15: expand admin attribution from `actor_email` to richer RBAC subject/role model and surface audit events in UI.

## Task 15 — AuthN/AuthZ hardening (2026-02-21)

### What changed

- Added in-app auth/authz modules under `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/auth/`:
  - `principal.py`: principal extraction from IAP headers, admin-key mode, and local dev principal mode
  - `rbac.py`: role enforcement helpers (`viewer`, `operator`, `admin`)
  - `audit.py`: normalized audit actor attribution helper
- Added RBAC settings and defaults:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
  - new env vars: `AUTHZ_ENABLED`, `AUTHZ_IAP_DEFAULT_ROLE`, role allowlists, and local dev principal controls
- Enforced route-level ACLs:
  - read routes now require `viewer` when RBAC is enabled (mounted via dependency in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`)
  - admin routes now require `admin` role (`/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`)
- Extended admin audit attribution:
  - added `actor_subject` on `admin_events` model and migration
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0009_admin_events_actor_subject.py`
  - updated admin audit persistence to include `actor_subject`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/admin_audit.py`
- Added admin mutation audit visibility in UI:
  - new `GET /api/v1/admin/events` endpoint
  - new Admin UI Events tab showing actor email/subject/action/target/request id/details
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
- Hardened browser secret handling in production posture:
  - admin-key localStorage persistence is now limited to localhost/dev usage
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/app/settings.tsx`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Updated docs and task status:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/security.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_GCP.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/15-authn-authz.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`

### Why it changed

- Completes Task 15 acceptance:
  - admin actions are blocked without `admin` role (when RBAC is enabled)
  - acting principal attribution includes `actor_email` and optional `actor_subject`
  - attribution is visible in the admin audit UI
  - production posture avoids persisting admin secrets to browser localStorage
- Preserves local-first/dev convenience:
  - default dev key path still works
  - local dev principal mode supports RBAC testing without external identity infrastructure

### How it was validated

- `make fmt` ✅
- `make lint` ✅
- `make typecheck` ✅
- `make test` ✅
- `make harness` ✅
- Targeted checks during implementation:
  - `uv run --locked ruff check ...` ✅
  - `uv run --locked pyright` ✅
  - `DATABASE_URL=sqlite+pysqlite:///:memory: uv run --locked pytest -q tests/test_authz.py tests/test_security.py tests/test_admin_audit.py tests/test_migrations_sqlite.py` ✅

### Risks / rollout notes

- RBAC defaults:
  - `AUTHZ_ENABLED` defaults to `false` in `dev`, `true` in `stage/prod`.
  - In non-dev environments, ensure identity headers and role allowlists are configured before enabling broad operator access.
- Admin key mode remains supported for local/dev; production should prefer perimeter identity (`ADMIN_AUTH_MODE=none` + IAP/IAM).
- New migration `0009_admin_events_actor_subject` must be applied before deploying code that reads/writes `actor_subject`.

### Follow-ups / tech debt

- [ ] Expand RBAC usage to additional mutation surfaces as they are introduced (policy overrides/destructive endpoints).

## Task 16 — OpenTelemetry SQLAlchemy + Metrics (2026-02-21)

### What changed

- Expanded OTEL wiring with SQLAlchemy instrumentation and metric export:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/observability.py`
  - added SQLAlchemy span instrumentation (`opentelemetry-instrumentation-sqlalchemy`)
  - added request correlation attributes on HTTP + DB spans (`edgewatch.request_id`)
  - added OTEL metrics instruments for:
    - HTTP request count/latency by endpoint
    - ingest points accepted/rejected
    - alert open/close transitions
    - monitor loop duration
- Wired monitor loop metric emission:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`
- Wired ingest accepted/rejected point metrics:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/ingest.py`
- Wired alert lifecycle transition metrics:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/monitor.py`
- Added OTEL dependency for SQLAlchemy instrumentation:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pyproject.toml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/uv.lock`
- Updated observability/task docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/OBSERVABILITY.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/OBSERVABILITY_OTEL.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/16-opentelemetry.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 16 so OTEL-enabled deployments include both request and DB spans plus actionable service-level metrics for incident triage.

### How it was validated

- `make harness` ✅

### Risks / rollout notes

- OTEL remains opt-in (`ENABLE_OTEL=1`); when disabled, metric and instrumentation paths are no-ops.
- In non-dev environments, metrics/traces require OTLP endpoint configuration (`OTEL_EXPORTER_OTLP_*`) to leave the process.

### Follow-ups / tech debt

- [ ] Consider adding explicit OTEL collector Terraform module/task for a turnkey Cloud Run deployment path.

## Task 14 (Iteration) — Alerts Timeline + Routing Audit (2026-02-21)

### What changed

- Upgraded the Alerts page to include timeline grouping and expanded filtering:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - added filters for:
    - device id
    - alert type
    - severity
    - open/resolved
  - added timeline grouping by day with per-severity counts and recent-row previews.
- Added routing decision audit visibility on Alerts:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - consumes admin notifications when admin routes/auth are available
  - shows dedupe/throttle/quiet-hours decision badges and reasons per alert
  - added a routing audit summary card with decision counts for currently shown alerts.
- Updated docs/task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/14-ui-ux-polish.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`

### Why it changed

- Completes the remaining Alerts slice in Task 14 so operators can quickly scan incident windows and verify notification routing behavior without leaving the dashboard.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -r --if-present build` ✅
- `make harness` ✅

### Risks / rollout notes

- Routing audit visibility depends on admin notification endpoints; when admin routes are disabled (or key auth is required but not configured), the UI intentionally degrades to explanatory empty states.
- Alerts timeline is built from loaded pages in the current client view; broad historical analysis still requires loading additional pages.

### Follow-ups / tech debt

- [ ] Complete remaining Task 14 work for IAP operator posture UX after Task 18 lands.

## Task 14 (Iteration) — Device Detail Oil-Life Gauge (2026-02-21)

### What changed

- Added a dedicated oil-life service gauge to the Device Detail Overview:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - added a radial gauge component driven by latest `oil_life_pct`
  - added explicit health bands and service guidance:
    - `Healthy` (50%+)
    - `Watch` (20% to 49%)
    - `Service now` (below 20%)
  - handles missing-contract and missing-telemetry states with clear operator messaging.
- Updated docs/task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/14-ui-ux-polish.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`

### Why it changed

- Completes the remaining non-IAP Device Detail item in Task 14 so operators can quickly assess maintenance urgency from oil life without opening raw telemetry.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -r --if-present build` ✅
- `make harness` ✅

### Risks / rollout notes

- Gauge availability depends on `oil_life_pct` being present in both the active telemetry contract and recent telemetry payloads.
- Threshold bands are UI-side operator guidance; they are not yet policy-driven from server-side config.

### Follow-ups / tech debt

- [ ] Complete remaining Task 14 work for IAP operator posture UX after Task 18 lands.

## Task 17 — Telemetry Partitioning + Rollups (2026-02-21)

### What changed

- Added Postgres scale-path migration:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0010_telemetry_partition_rollups.py`
  - creates `telemetry_ingest_dedupe` and `telemetry_rollups_hourly`
  - converts Postgres `telemetry_points` to monthly range partitions on `ts`
  - keeps non-Postgres lanes portable (no partition conversion on SQLite)
- Updated ingest runtime to preserve idempotency independent of partitioned-table unique constraints:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/ingestion_runtime.py`
  - reserves `(device_id, message_id)` in `telemetry_ingest_dedupe` before inserting telemetry rows
- Added partition/rollup services + scheduled job:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/telemetry_partitions.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/telemetry_rollups.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/jobs/partition_manager.py`
- Enhanced retention to drop old partitions first (when enabled) and prune dedupe/rollup tables:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/jobs/retention.py`
- Added optional rollup-backed reads for hourly timeseries:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
- Terraform + ops wiring for partition manager Cloud Run Job + Scheduler:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/jobs.tf`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/variables.tf`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/prod_private_iam.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile` (`partition-manager-gcp`)
- Added/updated tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_ingestion_runtime.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_telemetry_scale_services.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_migrations_sqlite.py`
- Updated task/docs/changelog/version:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/17-telemetry-partitioning-rollups.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/RETENTION.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_GCP.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/PRODUCTION_POSTURE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/CHANGELOG.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pyproject.toml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/version.py`

### Why it changed

- Task 17 requires a production-ready Postgres scale path: partitioned telemetry storage, scheduled partition management, retention via partition drops, and optional hourly rollups for long-range chart workloads.
- Postgres partitioned tables cannot directly preserve the prior `(device_id, message_id)` unique enforcement pattern, so ingest idempotency was moved to a dedicated dedupe table while preserving the same external contract.

### How it was validated

- `make fmt` ✅
- `make harness` ✅
- `make db-up` ✅
- `make db-migrate` ✅
- `make tf-check` ✅ (with existing soft-fail checkov findings in baseline posture)

### Risks / rollout notes

- **Migration ordering is mandatory**: deploys must run Alembic `0010_telemetry_partition_rollups` before app code that depends on new tables/jobs.
- Rollup reads are only used when `TELEMETRY_ROLLUPS_ENABLED=true` and bucket is hourly; otherwise the API remains on raw telemetry aggregation.
- `make tf-check` still reports known policy findings in this repo’s current baseline (soft-fail enabled); no new hard failures were introduced by Task 17 wiring.

### Follow-ups / tech debt

- [ ] Add a Postgres migration integration test lane that asserts partitioned table plans directly (for example, `EXPLAIN` partition pruning checks in CI).

## Task 19 — Agent Buffer Hardening (2026-02-21)

### What changed

- Hardened SQLite buffering in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/buffer.py`:
  - configurable WAL pragmas (`journal_mode`, `synchronous`, `temp_store`)
  - DB byte quota enforcement (`max_db_bytes`) with oldest-first eviction
  - disk-full graceful handling (evict + retry, or drop with audit log)
  - corruption recovery (move malformed DB/WAL/SHM aside, recreate schema)
  - buffer metrics API:
    - `buffer_db_bytes`
    - `buffer_queue_depth`
    - `buffer_evictions_total`
- Wired env-driven buffer config + audit metrics into runtime loops:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/simulator.py`
- Added operator-facing config + runbook docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/OFFLINE_CHECKS.md`
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_buffer.py`
- Updated task queue status docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/19-agent-buffer-hardening.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`

### Why it changed

- Task 19 requires field-resilient buffering behavior under power loss, intermittent links, and constrained disk on edge nodes.
- The hardened buffer preserves local-first operation while making data loss events explicit and observable for operators.

### How it was validated

- `make fmt` ✅
- `make lint` ✅
- `make typecheck` ✅
- `make test` ✅
- `make harness` ✅

### Risks / rollout notes

- If `BUFFER_MAX_DB_BYTES` is configured below SQLite’s practical file floor for a device, the buffer now clamps the quota upward and logs a warning to avoid permanent eviction thrash.
- Evictions are intentional oldest-first data loss events; operators should monitor `buffer_evictions_total` and adjust disk quotas per node profile.

### Follow-ups / tech debt

- [ ] Consider exporting buffer metrics as dedicated local health endpoints in addition to telemetry payload embedding.

## Task 20 — Edge Protection for Public Ingest (2026-02-21)

### What changed

- Added optional Cloud Armor edge protection for public ingest in Terraform:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/edge_protection.tf`
  - provisions HTTPS LB + Cloud Armor security policy for the primary ingest service
  - includes edge throttling independent of app logic
  - supports optional trusted CIDR allowlist bypass and preview mode
- Added Terraform inputs/validations:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/variables.tf`
  - `enable_ingest_edge_protection`, `ingest_edge_domain`, rate-limit tuning vars, allowlist vars
- Added Terraform outputs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/outputs.tf`
  - `ingest_edge_url`, `ingest_edge_security_policy_name`
- Fixed Terraform profile var-file handling for `-chdir` workflows:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile`
  - `TFVARS_ARG` now normalizes `infra/gcp/cloud_run_demo/...` paths to chdir-relative paths.
- Updated profile/docs guidance:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_admin.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_dashboard_private_admin.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_admin.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_dashboard_private_admin.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_GCP.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/security.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/PRODUCTION_POSTURE.md`
- Added runbook:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/EDGE_PROTECTION.md`
- Updated task status/queue:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/20-edge-protection-cloud-armor.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`

### Why it changed

- Task 20 requires perimeter throttling for internet-exposed ingest so abuse/cost incidents are mitigated before requests hit app code.
- This preserves current least-privilege multi-service posture while adding an optional, Terraform-first edge control layer.

### How it was validated

- `make fmt` ✅
- `make lint` ✅
- `make typecheck` ✅
- `make test` ✅
- `make harness` ✅
- `make tf-check` ✅
- `terraform -chdir=infra/gcp/cloud_run_demo init -backend=false` ✅
- `terraform -chdir=infra/gcp/cloud_run_demo validate` ✅
- `make -n plan-gcp-stage-iot` ✅ confirms normalized profile var-file path (`profiles/...`) with `-chdir`
- `terraform -chdir=infra/gcp/cloud_run_demo plan -var-file=profiles/stage_public_ingest_private_admin.tfvars ...` ✅
  - plan includes new resources:
    - `google_compute_security_policy.ingest_edge`
    - `google_compute_backend_service.ingest_edge`
    - `google_compute_global_forwarding_rule.ingest_edge`
    - `ingest_edge_url` output

### Risks / rollout notes

- Enabling edge protection requires DNS for `ingest_edge_domain` and routing devices to `ingest_edge_url`.
- If a fleet is heavily NATed, per-IP throttling can over-limit; tune `ingest_edge_rate_limit_*` or use `XFF_IP` where appropriate.
- Manual edge-throttle smoke in a real GCP environment is still required before production enforcement.

### Follow-ups / tech debt

- [ ] Add a CI smoke target that exercises Cloud Armor preview-mode logs in a staging project.

## Task 14 — UI/UX Polish (IAP operator posture) (2026-02-22)

### What changed

- Added shared admin auth-error guidance utilities:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/utils/adminAuth.ts`
  - parses HTTP status from client errors and returns mode-aware operator guidance.
- Fixed app shell capability wiring:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/RootLayout.tsx`
  - now passes `adminEnabled` and `adminAuthMode` from `/api/v1/health` into `AppShell`, so Admin nav/badges correctly reflect backend posture.
- Improved IAP/key recovery UX on admin audit surfaces:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - each view now shows actionable guidance on 401/403 failures:
    - `ADMIN_AUTH_MODE=none`: sign-in/perimeter + role guidance
    - `ADMIN_AUTH_MODE=key`: admin-key recovery guidance
- Updated docs/task status:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/14-ui-ux-polish.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Task 14’s final remaining item was IAP operator login/access UX after Task 18.
- Operators previously saw raw 401/403 strings in some audit views, which is not enough for production troubleshooting.
- The shell capability wiring fix ensures role/posture indicators are trustworthy across environments.

### How it was validated

- `make harness` ✅
- `pnpm -r --if-present build` ✅
- `pnpm -C web typecheck` ✅
- `make lint` ✅
- `make test` ✅

### Risks / rollout notes

- Guidance is intentionally based on HTTP status categories (401/403), not brittle backend string matching.
- No backend auth behavior changed; this is UI/operator guidance and shell capability wiring only.

### Follow-ups / tech debt

- [ ] Consider adding dedicated frontend component tests when a web test harness is introduced (currently repo gates web typecheck/build).

## Task 11 (Epic) — Edge Sensor Suite closeout (2026-02-22)

### What changed

- Closed the Task 11 epic status and queue docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/11-edge-sensor-suite.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`
- Updated sensor runbook wording from planned posture to implemented posture:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SENSORS.md`
- Completed the remaining Task 11 UI acceptance gap by exposing oil-life reset timestamp end-to-end:
  - agent derived backend now emits `oil_life_reset_at` alongside `oil_life_pct`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/derived.py`
  - telemetry contract now includes `oil_life_reset_at` as a string metric
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
  - device detail oil-life gauge now renders “Last reset” when present
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - docs and tests updated:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_derived.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_contracts.py`

### Why it changed

- Task 11 remained in queue as an epic wrapper even though `11a..11d` were shipped.
- The epic acceptance criteria called for oil-life gauge visibility with last reset context; this change makes that operator context available in the UI via contract-backed telemetry.

### How it was validated

- `make harness` ✅
- `make lint` ✅
- `make test` ✅
- `pnpm -C web typecheck` ✅
- `pnpm -r --if-present build` ✅

### Risks / rollout notes

- `oil_life_reset_at` is additive and backward compatible; devices that do not emit it continue to work.
- No API route or auth behavior changed.
- No Terraform or migration changes.

### Follow-ups / tech debt

- [x] Camera epic (`docs/TASKS/12-camera-capture-upload.md`) closeout completed on 2026-02-22.

## Task 12 (Epic) — Camera capture + media upload closeout (2026-02-22)

### What changed

- Completed the remaining agent integration work for the Task 12 epic:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/runtime.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/storage.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/__init__.py`
- Added alert-transition photo capture support in the runtime loop (edge-triggered with cooldown).
- Added metadata-first media upload pipeline in the agent:
  - `POST /api/v1/media` then `PUT /api/v1/media/{id}/upload`
  - deterministic media message IDs for retry idempotency
  - oldest-first upload from ring buffer with per-asset retry backoff
  - successful uploads delete local assets from the ring buffer
- Added/updated operator docs and env knobs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CAMERA.md`
- Closed queue bookkeeping docs for Task 12:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/12-camera-capture-upload.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`
- Added deterministic tests for upload + alert-transition behavior:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_media_runtime.py`

### Why it changed

- Task 12 was still open at the epic level even though `12a/12b/12c` were shipped.
- The missing production slice was device-side upload orchestration from the local ring buffer to the existing API media endpoints.

### How it was validated

- `uv run --locked pytest -q tests/test_media_runtime.py` ✅
- `python scripts/harness.py lint --only python` ✅
- `python scripts/harness.py test --only python` ✅
- `python scripts/harness.py typecheck --only python` ✅
- `make harness` ✅

### Risks / rollout notes

- Upload retries are per-asset in-memory; after agent restart, pending ring-buffer assets are still retried, but backoff timing state resets.
- Video capture remains out of scope for this epic closeout and should be handled as a separate follow-on task.
- No Terraform/auth/public API contract changes in this PR.

### Follow-ups / tech debt

- [ ] Optional: add a small integration smoke test that exercises media upload loop against a live API fixture.

## Dashboard Fleet Map (2026-02-22)

### What changed

- Added an interactive fleet map to the dashboard:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/components/FleetMap.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`
- Map behavior:
  - reads device coordinates from latest telemetry metrics (`latitude/longitude`, `lat/lon`, `lat/lng`, `gps_latitude/gps_longitude`, `location_lat/location_lon`)
  - renders status-colored markers (online/offline/unknown)
  - supports click selection with device details and open-alert count
  - includes recenter control and map coverage badges
- Added local-demo compatibility so map is useful immediately:
  - mock sensor backend now emits deterministic coordinates per device:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/mock_sensors.py`
  - telemetry contract now includes:
    - `latitude`
    - `longitude`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
- Added Leaflet dependency for interactive mapping:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/package.json`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pnpm-lock.yaml`
- Updated UI docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`

### Why it changed

- Operators need spatial awareness in the dashboard to correlate device status/alerts by location instead of scanning only tables/cards.
- Local simulator and mock-sensor workflows should show useful map output out-of-the-box.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -C web build` ✅
- `uv run --locked pytest -q tests/test_sensor_scaling.py tests/test_contracts.py` ✅
- `make harness` ✅

### Risks / rollout notes

- Web bundle size increased due Leaflet (still within existing build warnings).
- Dashboard map relies on OpenStreetMap tile requests at runtime; operator environments with strict egress policies may require an internal tile source later.
- No API route/auth/Terraform changes.

### Follow-ups / tech debt

- [ ] Optional: add dashboard-side location filter controls (status + bounding-box).
- [ ] Optional: support configurable tile providers for private/air-gapped deployments.

## Web Tables — Overflow + Alignment Fix (2026-02-22)

### What changed

- Stabilized all app tables by updating the shared table component:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/DataTable.tsx`
- Removed absolute-position virtualization rows that caused header/body misalignment and row overlap with variable-height cell content.
- Switched to native `<tbody>/<tr>` rendering so column widths and row geometry stay consistent across all pages.
- Tightened cell styles to improve overflow behavior:
  - headers stay on one line (`whitespace-nowrap`)
  - cell content wraps safely (`overflow-wrap:anywhere`)
  - cell content container uses `min-w-0` to prevent spillover.

### Why it changed

- Multiple pages were showing text overflow and visibly misaligned columns because every table uses this shared component.
- The previous virtualization strategy assumed fixed-height rows (`44px`) while many cells contain variable-height content (`details`, JSON previews, badges), which broke layout.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -C web build` ✅
- `make harness` ✅

### Risks / rollout notes

- Rendering is now non-virtualized; this trades some performance headroom on very large tables for consistent, correct layout.
- No API, auth, migration, or Terraform behavior changed.

### Follow-ups / tech debt

- [ ] If any table grows to very large row counts, reintroduce virtualization with a width-safe row layout strategy and variable-height support.

## Map Rendering + Table Hardening (2026-02-22)

### What changed

- Updated CSP headers to allow OpenStreetMap tile image domains so Leaflet can render map tiles in the dashboard:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`
  - added `https://tile.openstreetmap.org` and `https://*.tile.openstreetmap.org` to `img-src` for docs and non-docs responses.
- Hardened shared table layout behavior to prevent content overflow and column drift:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/DataTable.tsx`
  - switched table layout to fixed-width columns (`table-fixed`, `w-full`)
  - added `max-w-0` + stronger word wrapping on headers and cells
  - split scroll behavior into explicit `overflow-x-auto overflow-y-auto`.

### Why it changed

- Dashboard map could appear blank when served by the API because strict CSP blocked external OSM tile images.
- Some data-heavy tables still exhibited overflow/misalignment with long values; stronger shared table constraints were needed to keep all pages stable.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Strict Admin Key Gating (2026-02-23)

### What changed

- Added shared admin-access validation hook:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/hooks/useAdminAccess.ts`
  - validates key-mode admin access against `/api/v1/admin/events?limit=1`.
- Wired validated admin state into app shell/nav:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/RootLayout.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx`
- Updated admin access gating in pages to rely on validated access (not just non-empty key):
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`

### Why it changed

- Prevented admin-only UI affordances (for example, Contracts nav/page visibility) from appearing when an incorrect key is present in browser state.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Settings Admin Key Validation UX (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Changed `Save (session)` and `Save + persist` behavior:
  - key is now validated against admin API before being stored
  - success toast is shown only when validation succeeds
  - invalid key now returns an error toast with access guidance
- Replaced raw inline JSON error blocks in Settings with user-facing guidance callouts for admin access/load/save failures.

### Why it changed

- Prevented misleading success toasts when an invalid admin key is entered and removed raw backend error payloads from visible UI content.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Devices Page Policy Blurb Removal (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx`
- Removed the right-side `Policy` info block containing:
  - `policy: v1 · <sha>`
  - implementation note about `/api/v1/devices/summary` + `/api/v1/alerts?open_only=true`
- Adjusted the filters grid from three columns to two columns to match remaining content.

### Why it changed

- Simplified the Devices page by removing low-value implementation-detail text from the UI.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Device Detail Cleanup (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
- Removed the `Telemetry contract` callout card from the device detail page (`/devices/:deviceId`) overview section.

### Why it changed

- Simplified the page and removed low-value duplicate contract context from the bottom of the device detail view.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Settings: Contract Policy Controls (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Added a new admin-only `Contract policy controls` card on Settings.
- Added a curated UI for high-signal edge policy values:
  - reporting cadence
  - key alert thresholds
  - selected cost caps
- Added a full `Edit edge policy contract (YAML)` editor section on Settings.
- Both save paths use existing admin contract endpoints and remain inactive when admin mode is not active.
- Kept `/contracts` page behavior intact.

### Why it changed

- Allows operators to manage important contract policy settings directly from Settings while preserving full YAML control for advanced edits.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- CSP now permits OSM tile images; if your environment disallows public egress, map tiles will still be blocked by network policy.
- `table-fixed` prioritizes layout stability; very dense tables may wrap more aggressively than before.

### Follow-ups / tech debt

- [ ] Optional: support a configurable internal tile source for private/air-gapped deployments.

## Springfield, CO Device Radius (2026-02-22)

### What changed

- Updated demo/mock telemetry location generation to place devices within 50 miles of Springfield, Colorado:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/mock_sensors.py`
  - switched from fixed degree offsets to deterministic geodesic placement with a 50-mile cap.
- Updated dashboard demo fallback location logic to the same Springfield, CO + 50-mile radius model:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/components/FleetMap.tsx`
  - uses deterministic distance/bearing math for fallback markers.

### Why it changed

- Aligns the fleet geography with your requested area while keeping deterministic placement behavior.
- Ensures both telemetry-based coordinates and map fallback coordinates use the same regional constraints.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- Existing telemetry points already stored in the database keep their old coordinates; new simulated points use Springfield-area coordinates.
- Map fallback applies only when location metrics are missing for demo devices.

### Follow-ups / tech debt

- [ ] Optional: expose demo center/radius as configuration instead of code constants.

## Dashboard Tile Navigation (2026-02-22)

### What changed

- Made dashboard metric tiles keyboard/click navigable:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`
  - top summary tiles now route on activation:
    - `Total devices`, `Online`, `Offline` -> `/devices`
    - `Open alerts` -> `/alerts`
  - vitals/threshold tiles now route on activation:
    - `Low water pressure`, `Low battery`, `Weak signal`, `Low oil pressure`, `Low oil level`, `Low drip oil`, `Oil life low`, `No telemetry yet` -> `/devices`
- Added accessibility/interaction behavior:
  - card tiles get `role="button"`, `tabIndex=0`, Enter/Space activation, and focus ring styling.
  - nested interactive controls (existing device links inside tiles) are preserved and do not trigger tile-level navigation.

### Why it changed

- Supports direct dashboard navigation workflow from tile summaries (including the requested alerts tile behavior).

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- Tiles route to page-level destinations, not pre-filtered deep links; users may still need to apply filters after navigation.

### Follow-ups / tech debt

- [ ] Optional: add route search params for status/threshold filters and wire each tile to a pre-filtered destination.

## Device Detail Timeseries 500 Fix (2026-02-22)

### What changed

- Fixed SQLAlchemy 2 JSON extraction breakage in timeseries routes:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
  - replaced deprecated `.astext` usage with dialect-aware JSON text extraction helper (`->>` for Postgres, `json_extract` for SQLite).
- Hardened metric key handling:
  - validates metric keys against `^[A-Za-z0-9_]{1,64}$` in `/timeseries` and `/timeseries_multi`.
- Kept numeric aggregation safe:
  - Postgres uses regex-guarded cast to avoid invalid numeric cast errors.
  - non-Postgres uses float casting on extracted JSON text.
- Added regression tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_timeseries_routes.py`
  - verifies SQL compilation path for Postgres/SQLite extraction and invalid metric-key rejection.

### Why it changed

- Device detail chart requests to `/api/v1/devices/{id}/timeseries_multi` were returning `500` due `AttributeError` (`.astext`) under SQLAlchemy 2.

### How it was validated

- Reproduced failing request locally against running API (`500`) before patch.
- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅
- Retested failing endpoint request locally after patch (`200`) ✅

### Risks / rollout notes

- Metric-key validation now returns `400` for invalid keys that were previously accepted implicitly.

### Follow-ups / tech debt

- [ ] Optional: add full integration tests for `/timeseries` and `/timeseries_multi` with a Postgres test fixture.

## Professional Copy Refresh (2026-02-22)

### What changed

- Updated `Meta` contracts description for clearer operational intent:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Meta.tsx`
  - now describes contracts as active telemetry/edge-policy artifacts used for validation, policy enforcement, and UI behavior.
- Refined `Settings` copy to a professional operations tone:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - removed the explicit “Theme is stored in localStorage.” wording
  - removed informal “Tip” style helper text (including demo-device references)
  - tightened security and admin-access descriptions for production posture
  - updated links card description to “Operational links.”

### Why it changed

- Improve clarity and professionalism of operator-facing language and remove tutorial/portfolio-style wording.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- Copy-only change; no API behavior, auth model, or data contract changes.

### Follow-ups / tech debt

- [ ] Optional: perform a broader UX copy pass for consistent enterprise tone across all pages.

## Admin Key UX Clarification (2026-02-22)

### What changed

- Clarified admin auth failure guidance:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/utils/adminAuth.ts`
  - 401 hint now explicitly states the key must exactly match server `ADMIN_API_KEY` and includes the local default (`dev-admin-key`).
- Clarified settings helper copy:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - admin key help text now explicitly states the key must match server `ADMIN_API_KEY`.

### Why it changed

- Reduce operator confusion when a saved key still fails with `401 Invalid admin key` by making the mismatch cause explicit in-product.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅
- Manual verification against local API:
  - `X-Admin-Key: dev-admin-key` returns `200` on `/api/v1/admin/events`
  - mismatched key returns `401 Invalid admin key`

### Risks / rollout notes

- Copy-only UX clarification; no auth logic or API contract changes.

### Follow-ups / tech debt

- [ ] Optional: add a “Validate admin key” action on Settings to test credentials before navigating to Admin pages.

## Admin Key 401 Persistence Fix (2026-02-22)

### What changed

- Forced admin-query refetch on credential posture changes:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - invalidates cached `['admin', ...]` queries when auth mode or admin key changes to prevent sticky 401 states from prior credentials.
- Normalized backend admin key input:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
  - reads `ADMIN_API_KEY` via trimmed optional-string helper to avoid hidden leading/trailing whitespace mismatches.
- Added regression coverage:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_route_surface_toggles.py`
  - verifies `load_settings()` trims `ADMIN_API_KEY`.

### Why it changed

- Resolve repeated `401 Invalid admin key` outcomes after key updates by ensuring the frontend does not keep stale auth-query state, and by hardening server-side key parsing against accidental whitespace.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`116 passed`)

### Risks / rollout notes

- Frontend now performs extra admin-query invalidation when key/mode changes; expected to be low-cost and bounded to admin query namespace.
- `ADMIN_API_KEY` trimming changes behavior only for accidental surrounding whitespace.

### Follow-ups / tech debt

- [ ] Optional: add a one-click “validate key” probe in Settings for immediate credential verification.

## Admin Key Normalization Hardening (2026-02-22)

### What changed

- Normalized admin key input client-side before storage and request headers:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/app/settings.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
  - accepts common paste formats (`ADMIN_API_KEY=...`, `export ADMIN_API_KEY=...`, quoted values).
- Normalized admin key server-side before HMAC compare:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/auth/principal.py`
  - prevents format/paste artifacts from causing false `401 Invalid admin key`.
- Added backend regression tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_security.py`
  - covers assignment-style and quoted admin-key headers.

### Why it changed

- Repeated operator reports of `401 Invalid admin key` despite saving keys indicated key-format mismatch risk (copied env syntax/quotes), not only value mismatch.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`118 passed`)
- Manual curl verification against local API:
  - `X-Admin-Key: "dev-admin-key"` -> `200`
  - `X-Admin-Key: ADMIN_API_KEY=dev-admin-key` -> `200`
  - `X-Admin-Key: export ADMIN_API_KEY=dev-admin-key` -> `200`

### Risks / rollout notes

- Admin key parser is now intentionally tolerant of common env/paste wrappers; auth still requires exact normalized key match.

### Follow-ups / tech debt

- [ ] Optional: add a dedicated Settings “Validate key” action that probes `/api/v1/admin/events?limit=1` and surfaces immediate pass/fail.

## UI-Managed Alert Webhook Destinations (2026-02-22)

### What changed

- Added persistent notification destination model and migration:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0011_notification_destinations.py`
  - new table: `notification_destinations` (name, channel, kind, webhook_url, enabled, timestamps).
- Added admin API for destination management:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
  - endpoints:
    - `GET /api/v1/admin/notification-destinations`
    - `POST /api/v1/admin/notification-destinations`
    - `PATCH /api/v1/admin/notification-destinations/{destination_id}`
    - `DELETE /api/v1/admin/notification-destinations/{destination_id}`
  - includes URL validation, masked URL responses, and admin audit events.
- Extended schemas for destination CRUD:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
- Updated notification delivery pipeline:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/notifications.py`
  - uses all enabled UI-configured destinations (supports multiple webhooks).
  - keeps backward compatibility fallback to `ALERT_WEBHOOK_URL` when no DB destinations are configured.
- Added Settings UI management for webhook destinations:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - users can add, list, enable/disable, and remove multiple webhook destinations.
- Added frontend API bindings/types:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
- Added notification service tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_notifications_service.py`
  - covers no-adapter behavior, multi-destination delivery, and env fallback.

### Why it changed

- Enable operators to configure alert webhook URLs directly in the UI and support multiple destinations without editing deployment environment variables.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`121 passed`)
- Runtime verification:
  - rebuilt and restarted compose services with migration (`docker compose up -d --build migrate api`)
  - verified `POST` + `GET` + `DELETE` on `/api/v1/admin/notification-destinations` with `X-Admin-Key`.

### Risks / rollout notes

- Webhook URLs are persisted in database storage for UI management; responses expose only masked URL + fingerprint.
- If at least one DB destination exists, delivery uses DB destinations; env `ALERT_WEBHOOK_URL` remains fallback only when no DB destination is configured.

### Follow-ups / tech debt

- [ ] Optional: add per-destination test-send action in Settings.
- [ ] Optional: add destination-level rate controls / channel-specific routing policy.

## Discord/Telegram Notification Kinds (2026-02-22)

### What changed

- Extended alert delivery kind support:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - allowed kinds now include `discord` and `telegram` (while keeping `generic` and `slack` for compatibility).
- Implemented Discord/Telegram payload behavior:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/notifications.py`
  - `discord`: sends `content` message payload.
  - `telegram`: requires `chat_id` in webhook URL query and sends Telegram-style payload.
- Updated Settings UI webhook kind options:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - primary options now `Discord`, `Telegram`, plus `Generic`.
  - added Telegram guidance for `chat_id` query requirement.
- Updated frontend API typing:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
- Added test coverage:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_notifications_service.py`
  - validates multi-destination delivery including Discord+Telegram and Telegram missing-`chat_id` failure behavior.

### Why it changed

- Align notification delivery with operator requirements to use Discord/Telegram instead of Slack.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`122 passed`)
- Runtime verification:
  - rebuilt API container (`docker compose up -d --build api`)
  - confirmed admin destination API accepts `discord` and `telegram` kinds.

### Risks / rollout notes

- Telegram delivery now requires `chat_id` on the configured URL query string; otherwise events are recorded as `delivery_failed` with explicit reason.

### Follow-ups / tech debt

- [ ] Optional: support Telegram `chat_id` as a dedicated field instead of URL query parsing.

## Admin-Only Contracts + Edge Policy Editing (2026-02-22)

### What changed

- Restricted Contracts navigation visibility to authenticated admin access:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/RootLayout.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx`
  - Contracts now require both admin routes enabled and active admin access.
- Added Contracts page admin gating + edit UX:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx`
  - non-admin users now see explicit access callouts.
  - admins can edit active edge-policy YAML inline and save/reset changes.
- Added admin contract source/update API bindings:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
- Added backend support for editable edge policy contract:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/edge_policy.py`
  - new helpers to read/write YAML source with full policy validation and cache invalidation.
- Added admin endpoints for edge policy contract management:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
  - `GET /api/v1/admin/contracts/edge-policy/source`
  - `PATCH /api/v1/admin/contracts/edge-policy`
  - update calls are audit-attributed via `admin_events`.
- Added schemas/docs/tests for the new contract edit surface:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_route_surface_toggles.py`

### Why it changed

- Ensure contract controls are limited to admin users.
- Enable direct admin management of the active edge policy contract without manual file edits outside the UI.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- Contract edits persist to the active YAML artifact on disk; in ephemeral/readonly runtimes this can fail with a server error.
- Validation prevents saving malformed policy content or version mismatches.

### Follow-ups / tech debt

- [ ] Optional: add optimistic concurrency (expected hash) for multi-admin edit collisions.

## Admin Page Input Lock + Key Callout Emphasis (2026-02-22)

### What changed

- Updated admin input behavior in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
- Added a shared `inputsDisabled` guard tied to admin access state.
- Applied disabled state to all Admin page text inputs (and related provisioning controls), so fields are inactive when admin is inactive.
- Updated `Callout` to support a warning tone and applied it to the `Admin key required` message for stronger visual emphasis.

### Why it changed

- Prevent accidental interaction with admin form controls when no active admin access is present.
- Make missing-admin-key state more obvious and actionable.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

### Risks / rollout notes

- None beyond presentation/state changes in the Admin UI.

### Follow-ups / tech debt

- [ ] Optional: apply warning callout variant to other access-blocked admin contexts for consistency.

## Sidebar Footer Reachability (2026-02-22)

### What changed

- Updated desktop shell layout in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx`
- Made the desktop sidebar viewport-pinned (`sticky top-0 h-screen`) instead of stretching with full page content height.
- Enabled internal scrolling for long nav lists (`overflow-y-auto`) so footer actions remain reachable.

### Why it changed

- Prevented a UX issue where users had to scroll to the bottom of long pages to access sidebar footer controls (Theme toggle / API Docs links).

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

### Risks / rollout notes

- Low risk CSS-only layout change scoped to desktop sidebar behavior.

## Idempotent Demo Device Bootstrap (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile`
- `make demo-device` is now idempotent:
  - first attempts `POST /api/v1/admin/devices`
  - on `409 Conflict`, automatically falls back to `PATCH /api/v1/admin/devices/{device_id}`
  - prints final response body in either path

### Why it changed

- Rerunning local setup was failing when the demo device already existed, causing noisy failures during normal iteration.

### How it was validated

- `make demo-device` ✅
  - returned `Demo device already existed; updated: demo-well-001`

### Risks / rollout notes

- Low risk; scoped to local developer tooling behavior.

## Settings Layout Cleanup (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Removed the `Links` card from the Settings page.
- Adjusted the Settings card grid to `items-start` so cards keep natural height and `Appearance` no longer stretches to the full row height.

### Why it changed

- Simplified the Settings page and corrected card sizing behavior for a cleaner professional layout.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Settings YAML-to-Controls Sync Hardening (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Hardened contract YAML numeric extraction used by `Contract policy controls`:
  - accepts `key : value` and `key: value` spacing variants
  - normalizes quoted numeric literals and numeric underscores (for example `"30"`, `50_000_000`)
- Updated contract control sync behavior so YAML edits re-sync controls even when the draft initializes later:
  - `policyYamlDraft` changes now sync against `importantDraft` with fallback to `importantInitial`
  - effect now depends on both `policyYamlDraft` and `importantInitial`
- Updated YAML key replacement regex used by `Save policy values` to also support `key : value` formatting.

### Why it changed

- Users editing `Edit edge policy contract (YAML)` could end up with stale values in `Contract policy controls` when YAML formatting varied or when YAML was edited before the controls draft state fully initialized.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- YAML-to-controls sync still intentionally targets the explicit high-signal key list shown in `Contract policy controls`; non-exposed contract keys remain YAML-only.

## Contracts UI Consolidation Into Settings (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/RootLayout.tsx`
- Moved contract details previously shown on `/contracts` into Settings (admin-active only):
  - telemetry contract table (metrics/types/units/descriptions)
  - edge policy contract summary (reporting + alert thresholds)
  - delta thresholds table
- Kept existing quick `Contract policy controls` and full `Edit edge policy contract (YAML)` sections in Settings.
- Contract sections on Settings now render only when admin mode is active.
- Removed `Contracts` from sidebar navigation.
- Simplified `/contracts` page to a handoff card linking users to Settings.

### Why it changed

- Consolidates all contract management and visibility into one admin-focused page and removes duplicate surfaces.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- Users with old `/contracts` bookmarks are not blocked (page remains), but editing/inspection now happens in Settings.

## One-Command Host Dev Lane (`make dev`) (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEV_FAST.md`
- Added `make dev` target to run the fast host dev loop in one command:
  - starts local DB container (`db-up` equivalent)
  - starts API with hot reload on `http://localhost:8080`
  - waits for API readiness (`/readyz`)
  - bootstraps demo device by default (`make demo-device` against `:8080`)
  - starts Vite dev server on `http://localhost:5173`
  - starts simulator fleet against host API by default
  - handles Ctrl-C cleanup for spawned host processes
- Added `make dev` tuning env vars:
  - `DEV_START_SIMULATE=0`
  - `DEV_BOOTSTRAP_DEMO_DEVICE=0`
  - `DEV_STOP_DB_ON_EXIT=1`

### Why it changed

- Simplifies local development into a single command while retaining hot reload for API and UI.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- `make dev` intentionally runs long-lived processes in one terminal; logs from API/UI/simulators are interleaved.
- Default behavior leaves the DB container running after exit (`DEV_STOP_DB_ON_EXIT=0`) for faster restarts.

## Dashboard Tile Filter Navigation Sync (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
- Dashboard stat tiles now navigate with filter-aware query params:
  - `Online` -> `/devices?status=online`
  - `Offline` -> `/devices?status=offline`
  - `Open alerts` -> `/alerts?openOnly=true`
- Devices page now initializes and syncs filter state from URL search params (`status`, `q`/`search`, `openAlertsOnly`).
- Alerts page now initializes and syncs the `openOnly` filter from URL search params (`openOnly`/`open_only`).

### Why it changed

- Tile clicks previously navigated to the correct page path but did not carry or apply the expected filter state, causing mismatch between dashboard intent and destination-page filters.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- URL filter sync currently targets the filters wired from dashboard tiles and common aliases; additional advanced filter state remains local unless explicitly encoded in search params.

## Alerts Page Routing Audit Card Removal (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
- Removed the `Routing audit` card section from the Alerts page.
- Removed card-only derived state and access-hint wiring that became unused after card removal.
- Updated Alerts page description copy to remove routing-audit wording.

### Why it changed

- Simplify the Alerts page by removing the routing-audit panel per product direction.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

## Alerts Summary Tiles: Interactive Feed Filters (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
- Made top summary tiles interactive (keyboard + click):
  - `Total` tile -> sets feed resolution filter to `all` and scrolls to Feed
  - `Open` tile -> sets feed resolution filter to `open` and scrolls to Feed
  - `Resolved` tile -> sets feed resolution filter to `resolved` and scrolls to Feed
  - `Page size` tile -> scrolls to Feed controls
- Added a tri-state feed resolution filter model (`all|open|resolved`) and corresponding Feed buttons.
- Extended alert search-param parsing to support resolution filter mapping:
  - `openOnly/open_only` -> `open`
  - `resolvedOnly/resolved_only` -> `resolved`
  - optional explicit `resolution=all|open|resolved`
- Kept dashboard deep-link behavior compatible (`/alerts?openOnly=true`).

### Why it changed

- Align tile interactions with operator expectations so summary cards act as quick pivots into the Feed with the correct filter state.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

## Dashboard Timeline Relocation + Expansion (2026-02-23)

### What changed

- Moved timeline functionality off Alerts and onto Dashboard:
  - Added a new, richer `Timeline` card to `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`.
  - Removed the old timeline card from `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`.
- Expanded timeline capability on Dashboard:
  - Added window controls (`24h`, `72h`, `7d`, `14d`).
  - Added status scope controls (`Open only`, `Open + resolved`).
  - Added severity scope controls (`All`, `Critical`, `Warning`, `Info`).
  - Added summary tiles: alerts in scope, distinct devices, peak hour, latest alert.
  - Added severity sparklines (`total`, `critical`, `warning`, `info`).
  - Added daily drill-down with per-day totals and sample alert rows.
  - Added top impacted devices and top alert types panels.
  - Added “Open in Alerts” deep-link preserving resolution/severity context.
- Improved Alerts page filter parsing to support `severity` query parameter initialization, so links from Dashboard apply expected feed filters.

### Why it changed

- You requested that Timeline live on Dashboard instead of Alerts.
- The prior Timeline card had limited utility; the new Dashboard version adds practical incident-triage functionality and faster drill-down paths.

### How it was validated

- `python scripts/harness.py lint` (pass)
- `python scripts/harness.py typecheck` (pass)
- `python scripts/harness.py test` (pass, 125 tests)

### Risks / rollout notes

- Timeline data is built from the most recent alert page query (`limit=500`), so very high-volume fleets may need pagination or server-side aggregated endpoints for full historical completeness.
- Existing dashboard sections remain unchanged outside timeline relocation/addition.

### Follow-ups

- [ ] If needed, add a backend timeline aggregation endpoint to avoid client-side grouping limits at larger fleet sizes.
- [ ] Optionally persist dashboard timeline filter selections in URL/search params for shareable triage views.

## Dashboard Open Alerts Clarity Fix (2026-02-23)

### What changed

- Updated Dashboard open-alert semantics to show only actionable unresolved incidents.
- Added resolution-event filtering in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`:
  - excludes `DEVICE_ONLINE` and `*_OK` events from Dashboard “Open alerts”.
- Applied the same filter consistently to:
  - top “Open alerts” tile count,
  - Fleet map open-alert context,
  - “Open alerts” table card rows/empty state.
- Updated card copy to explicitly say recovery events are excluded.
- Also aligned Dashboard Timeline “Open only” mode to exclude resolution events.

### Why it changed

- Recovery/info events were appearing as “open” because they are unresolved event records by design, which made the dashboard look like active issues still existed.
- Dashboard now reflects user intent: show actionable unresolved problems.

### How it was validated

- `python scripts/harness.py lint` (pass)
- `python scripts/harness.py typecheck` (pass)
- `python scripts/harness.py test` (pass, 125 tests)

## Pre-Push Review Fixes (2026-02-23)

### What changed

- Fixed contracts access control gap in web UI:
  - `/contracts` now validates admin mode/access and redirects to `/settings` when admin is not active.
  - File: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx`.
- Removed raw admin key value from React Query cache keys:
  - `useAdminAccess` now uses a non-sensitive fingerprint for `key-validation` query key.
  - File: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/hooks/useAdminAccess.ts`.
- Addressed pre-commit completeness risk:
  - Added required new source files to git tracking:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/hooks/useAdminAccess.ts`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0011_notification_destinations.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_notifications_service.py`
- Reduced local runtime artifact noise in working tree:
  - Added ignore rules for `edgewatch_buffer_*.sqlite-shm` and `edgewatch_buffer_*.sqlite-wal`.
  - File: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/.gitignore`.

### How it was validated

- `python scripts/harness.py lint` (pass)
- `python scripts/harness.py typecheck` (pass)
- `python scripts/harness.py test` (pass, 125 tests)

## Remove Legacy Contracts Page Route (2026-02-23)

### What changed

- Removed the legacy frontend `/contracts` route from the router.
- Deleted the obsolete contracts page component; contract management remains in Settings (admin-gated).

Files:
- `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/router.tsx`
- `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx` (deleted)

### How it was validated

- `python scripts/harness.py lint` (pass)
- `python scripts/harness.py typecheck` (pass)
- `python scripts/harness.py test` (pass, 125 tests)

## CI/CD Protocol Alignment (2026-02-23)

### What changed

- Added optional GCS-backed Terraform config workflow support (team protocol):
  - `Makefile` new vars/targets:
    - `TF_CONFIG_BUCKET`, `TF_CONFIG_PREFIX`, `TF_CONFIG_GCS_PATH`, `TF_BACKEND_HCL`
    - `tf-config-print-gcp`, `tf-config-pull-gcp`, `tf-config-push-gcp`, `tf-config-bucket-gcp`
  - `tf-init-gcp` now supports `TF_BACKEND_HCL` (file-based backend config) while preserving existing bucket/prefix mode.
- Added a manual Terraform plan workflow:
  - `.github/workflows/gcp-terraform-plan.yml`
- Updated deploy/apply/drift workflows to support optional config bundle pull from GCS when `GCP_TF_CONFIG_GCS_PATH` is set:
  - `.github/workflows/deploy-gcp.yml`
  - `.github/workflows/terraform-apply-gcp.yml`
  - `.github/workflows/terraform-drift.yml`
- Updated deployment and team docs for the new protocol:
  - `docs/WIF_GITHUB_ACTIONS.md`
  - `docs/DEPLOY_GCP.md`
  - `docs/DRIFT_DETECTION.md`
  - `docs/TEAM_WORKFLOW.md`
- Added ignore rules for local Terraform config files downloaded from GCS:
  - `.gitignore` now ignores `infra/gcp/cloud_run_demo/backend.hcl` and `infra/gcp/cloud_run_demo/terraform.tfvars`.

### Why it changed

- Align this repo with the production-grade, team-friendly protocol used in `grounded-knowledge-platform`:
  - centralized per-environment Terraform config in GCS,
  - WIF-only CI/CD auth,
  - explicit plan/apply/deploy lanes,
  - reproducible, less ad-hoc operator workflow.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (125 passed)
- Additional YAML parse check for workflows (including new untracked file):
  - `python - <<'PY' ... yaml.safe_load(...)` ✅

### Risks / rollout notes

- GitHub environments should define `GCP_TF_CONFIG_GCS_PATH` (recommended) to fully use the GCS config bundle flow.
- Existing deploy flow remains backward-compatible if `GCP_TF_CONFIG_GCS_PATH` is unset.

### Follow-ups

- [ ] Add `backend.hcl` + `terraform.tfvars` to each environment’s config path in GCS.
- [ ] Configure GitHub Environment variables per env (`dev|stage|prod`) and use the new `Terraform plan (GCP)` workflow as pre-apply gate.

## Microphone Mounting Clarification for RPi Pilot Hardware (2026-03-20)

### What changed

- Updated the field hardware and deployment docs to lock the pilot microphone posture:
  - use a short external protected USB microphone mount
  - keep the main enclosure sealed
  - do not rely on a loose microphone inside the sealed enclosure
- Added microphone mount accessory guidance to:
  - `docs/BOM.md`
  - `docs/HARDWARE.md`
  - `docs/DEPLOY_RPI.md`
  - `docs/TUTORIALS/RPI_FLASH_ASSEMBLE_LAUNCH_CHECKLIST.md`
  - `docs/TUTORIALS/RPI_ZERO_TOUCH_BOOTSTRAP.md`
  - `docs/RUNBOOKS/SENSORS.md`

### Why it changed

- A sealed weatherproof enclosure materially attenuates and colors the outside sound field.
- For threshold-based microphone monitoring, the pilot hardware needs a repeatable mounting pattern or the `60 dB` default becomes box-specific and unreliable.

### How it was validated

- Documentation review against the locked hardware posture and current Raspberry Pi microphone-first runtime.

### Risks / rollout notes

- The pilot build now assumes one additional short USB run and sheltered microphone mounting point outside the enclosure.
- Keep the external microphone cable short, strain-relieved, and protected with a drip loop.

### Follow-ups

- [ ] Lock a specific pilot hood/bracket part once the final Amazon order is chosen.

## Pilot microphone part selection locked (2026-03-20)

### What changed

- Updated the pilot BOM and hardware docs to name the current microphone choice explicitly:
  - `NowTH USB lavalier microphone` (`B0929CQSX4`)
- Updated:
  - `docs/BOM.md`
  - `docs/HARDWARE.md`

### Why it changed

- The pilot build now has a short external protected mic mount, and the selected lavalier form factor is a better mechanical fit than a stub USB mic because it already includes a `2 m` cable.

### How it was validated

- Documentation review against the locked field mounting posture and the current ALSA/`arecord` microphone runtime.

### Risks / rollout notes

- The chosen mic is still not weatherproof and must remain in a sheltered external mount with strain relief and a drip loop.

### Follow-ups

- [ ] Confirm USB audio enumeration on the first pilot Pi with `arecord -l` before sealing the field unit.

## Manual Deploy Runbook for EdgeWatch (2026-02-23)

### What changed

- Added a new manual deployment runbook:
  - `docs/MANUAL_DEPLOY_GCP_CLOUD_RUN.md`
- The runbook is tailored for EdgeWatch and documents:
  - reusing the existing GCP project and tfstate bucket,
  - creating a repo-specific WIF provider + deploy service account,
  - using separate config prefixes in GCS: `edgewatch/dev`, `edgewatch/stage`, `edgewatch/prod`,
  - setting GitHub Environment variables for `dev|stage|prod`,
  - deploying through the repo’s plan/apply/deploy workflows.
- Added discoverability links:
  - `docs/DEPLOY_GCP.md`
  - `docs/START_HERE.md`

### Why it changed

- Provide the same proven, production-minded manual setup flow used in `grounded-knowledge-platform`, adapted to EdgeWatch naming and workflow conventions.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- IAM role scopes in the runbook are intentionally broad enough for first-time success; tighten after first successful deploy.
- If WIF provider branch condition remains `main`-only, non-main workflow runs will fail by design.

### Follow-ups

- [ ] Add initial `backend.hcl` + `terraform.tfvars` objects to each env prefix under `edgewatch/*`.
- [ ] Run `Terraform plan (GCP)` for `dev` after setting environment variables.

## Notification events added to operator feeds (2026-04-17)

### What changed

- Extended the unified operator event surfaces so notification delivery audit now flows through:
  - `GET /api/v1/operator-events`
  - `GET /api/v1/event-stream`
- Notification delivery rows are now covered by the shared operator event schema, Live page defaults, and CLI default source-kind sets.
- Added route-level regression coverage in:
  - `tests/test_operator_tools_routes.py`

### Why it changed

- Notification delivery was searchable, but it was still missing from the main mixed operator history and live-stream workflows.
- That left delivery audit as a second-class operator surface compared with alerts, device events, procedures, and rollout events.

### How it was validated

- Added route tests covering notification events in both paged operator history and SSE replay/filter behavior.

### Risks / rollout notes

- Notification delivery audit remains admin-scoped by design because it includes delivery metadata and downstream channel details.

## Paged admin notification audit with delivery filters (2026-04-17)

### What changed

- Added filterable, total-aware notification audit paging on the admin surface:
  - `GET /api/v1/admin/notifications-page`
- Extended the existing notification list route to support shared delivery filters:
  - `source_kind`
  - `channel`
  - `decision`
  - `delivered`
- Updated the Admin notifications tab to use the paged route with previous/next controls and real delivery filters.
- Expanded the operator CLI with:
  - richer `admin notifications` filters
  - new `admin notifications-page`

### Why it changed

- Notification audit had become the odd admin lane out: fixed-size, device-only filtered, and missing totals.
- Operators need to isolate delivery failures and blocked notifications with the same level of precision already available on other audit surfaces.

### How it was validated

- Added backend regression coverage in `tests/test_admin_deployments.py`.
- Added CLI request-shape coverage in `tests/test_operator_cli.py`.

### Risks / rollout notes

- The original `admin notifications` list route remains for compatibility, while the Admin UI now prefers the paged route.

## Paged admin ingestion and drift audit lanes (2026-04-17)

### What changed

- Added total-aware paging for the remaining list-shaped admin audit lanes:
  - `GET /api/v1/admin/ingestions-page`
  - `GET /api/v1/admin/drift-events-page`
- Updated the Admin UI to use those paged routes for the Ingestions and Drift tabs, with previous/next controls and real totals.
- Expanded the operator CLI with:
  - `admin ingestions-page`
  - `admin drift-events-page`

### Why it changed

- Ingestions and drift were still capped lists while admin events and notifications had already moved to paged audit workflows.
- This keeps the admin audit surfaces consistent and prevents larger histories from being silently truncated in the UI.

### How it was validated

- Added backend regression coverage in `tests/test_admin_deployments.py`.
- Added CLI request-shape coverage in `tests/test_operator_cli.py`.

### Risks / rollout notes

- The original list endpoints remain in place for compatibility; the Admin UI now prefers the paged routes.

## Paged admin export audit lane (2026-04-17)

### What changed

- Added `GET /api/v1/admin/exports-page` with `status_filter`, `limit`, and `offset`.
- Updated the Admin Exports tab to use the paged route with total-aware previous/next controls.
- Expanded the operator CLI with `admin exports-page`.

### Why it changed

- Exports was the last remaining admin audit lane still using a capped list instead of a total-aware workflow.
- This makes the full Admin audit surface consistent across events, ingestions, drift, notifications, and exports.

### How it was validated

- Added backend regression coverage in `tests/test_admin_deployments.py`.
- Added CLI request-shape coverage in `tests/test_operator_cli.py`.

### Risks / rollout notes

- The original `admin exports` list route remains for compatibility while the Admin UI now prefers the paged route.

## Admin deep links carry richer filter state (2026-04-17)

### What changed

- Extended `/admin` route search state to carry notification-specific filters:
  - `sourceKind`
  - `channel`
  - `decision`
  - `delivered`
- Updated the System search page so notification-event and export-batch hits open the relevant Admin tab with more of the right filter context already applied.

### Why it changed

- Search results were landing on the correct Admin tab, but they were still too generic and forced operators to re-enter common filters manually.
- This reduces friction when moving from global discovery into focused audit investigation.

### How it was validated

- Web typecheck/build and full harness verification after the route-search wiring changes.

### Risks / rollout notes

- Admin route-search hydration intentionally only applies provided values; opening `/admin` without those search params preserves the existing in-page filter state behavior.

## Notification search deep links carry full delivery context (2026-04-17)

### What changed

- Extended unified-search notification-event metadata to include:
  - `source_kind`
  - `delivered`
- Updated the System search page so notification-event hits now pass those fields through to the Admin notifications tab.

### Why it changed

- Notification search hits already carried `channel` and `decision`, but they still dropped enough context to force extra operator filtering after navigation.
- This makes notification delivery search results land closer to the exact audit slice the operator was looking for.

### How it was validated

- Added regression coverage in `tests/test_operator_tools_routes.py` for notification-event search metadata.

### Risks / rollout notes

- This only affects unified-search metadata and Admin deep-link behavior; it does not change notification storage or delivery semantics.

## Ingestion and drift are now first-class search entities (2026-04-17)

### What changed

- Extended unified search with admin-only entities for:
  - `ingestion_batch`
  - `drift_event`
- Updated the System page default entity filter set and deep links so those hits open directly into the Admin Ingestions and Drift tabs.

### Why it changed

- Operators could page through ingestions and drift in Admin, but they still could not discover those records from the global search surface.
- This closes another practical discovery gap in the audit workflow.

### How it was validated

- Added regression coverage in `tests/test_operator_tools_routes.py` for mixed search results containing both ingestion batches and drift events.

### Risks / rollout notes

- These search entities are admin-only by design because they expose audit and lineage details not meant for general viewers.

## Notification destinations are now searchable (2026-04-17)

### What changed

- Extended unified search with the admin-only `notification_destination` entity.
- Updated the System page default entity filter set so notification destinations can be discovered from global search.
- Search hits for notification destinations now deep-link into Settings.

### Why it changed

- Notification destinations were configurable but still invisible to the main operator search surface.
- This closes another practical discovery gap in the operator tooling flow.

### How it was validated

- Added regression coverage in `tests/test_operator_tools_routes.py` for mixed search results containing notification destinations.

### Risks / rollout notes

- Notification destinations remain admin-only in search results because they expose delivery configuration details.

## Procedure definitions are now searchable (2026-04-17)

### What changed

- Extended unified search with the admin-only `procedure_definition` entity.
- Updated the System page default entity filter set so procedure definitions can be discovered from global search.
- Search hits for procedure definitions now deep-link into Admin.

### Why it changed

- Procedure definitions are a first-class device-cloud control surface, but they were still absent from the main operator search workflow.
- This closes another discovery gap around remote procedure governance.

### How it was validated

- Added regression coverage in `tests/test_operator_tools_routes.py` for mixed search results containing procedure definitions.

### Risks / rollout notes

- Procedure definitions remain admin-only in search because they are part of the privileged control plane.

## Settings deep-links can open a notification destination directly (2026-04-17)

### What changed

- Added route-search support on `/settings` for `destinationId`.
- Updated notification-destination search hits so they open Settings with the matching destination loaded into the existing edit form.

### Why it changed

- Notification destinations were searchable, but the hit still landed on a broad Settings page and forced another manual selection step.
- This makes global search materially more useful for configuration follow-up workflows.

### How it was validated

- Web typecheck/build and full harness verification after the route-search and edit-state hydration changes.

### Risks / rollout notes

- Destination deep-link hydration only applies when the destination list is available and the referenced id exists in the current admin-visible result set.

## Notification-destination search hits now land on the webhook section (2026-04-17)

### What changed

- Added a stable `#notification-webhooks` anchor to the Settings webhook-management section.
- Updated notification-destination search hits so they open the matching destination with both the destination id and the webhook section anchor.

### Why it changed

- Notification-destination search hits already loaded the correct destination into the editor, but still landed operators at the top of a long Settings page.
- This makes the landing state materially tighter without changing any backend behavior.

### How it was validated

- Web typecheck/build and full harness verification after the anchor/deep-link change.

### Risks / rollout notes

- This relies on the Settings page keeping the `notification-webhooks` anchor stable.

## Admin-required help links now land on the Settings admin-access section (2026-04-17)

### What changed

- Added a stable `#admin-access` anchor to the Settings admin-access card.
- Updated existing Admin and Device Detail help links so they land directly on that section instead of the top of Settings.

### Why it changed

- Several recovery and guidance flows already pointed operators to Settings, but still dropped them at the top of a long page.
- This tightens common admin-key remediation flows without changing any backend behavior.

### How it was validated

- Web typecheck/build and full harness verification after the anchor/deep-link changes.

### Risks / rollout notes

- This depends on the Settings page keeping the `admin-access` anchor stable.

## Fleet search hits now open the selected fleet directly (2026-04-17)

### What changed

- Added route-search support on `/fleets` for `fleetId`.
- Updated the Fleets page to hydrate its existing selected-fleet state from that route search.
- Fleet search hits from the System page now open the relevant fleet directly instead of the generic fleet list.

### Why it changed

- Fleet entities were searchable, but the result still dropped operators onto a broad page and forced another manual selection step.
- This makes global search materially more useful for fleet-governance follow-up work.

### How it was validated

- Web typecheck/build and full harness verification after the route-search wiring changes.

### Risks / rollout notes

- Fleet deep-link hydration only applies when the referenced fleet id is present in the current accessible fleet list.

## Export search hits can prefilter the exact batch (2026-04-17)

### What changed

- Added lightweight `exportId` route-search support on `/admin`.
- Admin now hydrates a local export-batch id filter from that route state.
- Export-batch search hits now carry both status and batch id into the Admin Exports tab.

### Why it changed

- Export search hits already landed on the correct Admin tab, but they still only filtered by status, which is often too broad.
- This makes export-batch follow-up materially more precise without adding backend complexity.

### How it was validated

- Web typecheck/build and full harness verification after the route-search wiring change.

### Risks / rollout notes

- The export id filter is local to the currently loaded page of export results; it is not a backend-filtered export lookup surface.

## Alert search hits now open a filtered alert feed (2026-04-17)

### What changed

- Updated System search alert hits so they open `/alerts` with the existing alert feed query-string filters already applied.
- Search hits now carry the matching alert type and device into the destination feed instead of landing on the generic Alerts page.

### Why it changed

- Alert entities were searchable, but the result still forced another manual filtering step in the alert feed.
- This makes global search materially more useful for alert follow-up workflows.

### How it was validated

- Web typecheck/build and full harness verification after the alert deep-link wiring change.

### Risks / rollout notes

- This uses the existing alert-feed URL contract instead of a new route-search surface, so it depends on the alert page continuing to honor those query-string filters.

## Device event and procedure hits now open the relevant device tab (2026-04-17)

### What changed

- Device Detail now honors a lightweight `?tab=` query string for existing tabs.
- Updated System search hits for:
  - `device_event`
  - `procedure_invocation`
- Updated Live view event links for:
  - `device_event`
  - `procedure_invocation`
- Those links now open the relevant device directly on the `Events` or `Procedures` tab instead of the generic Live stream.

### Why it changed

- Device events and procedure invocations are device-scoped records, so sending operators to the generic Live stream was a weaker navigation outcome than the device’s own focused workflow.
- This makes search and live-history follow-up materially more direct.

### How it was validated

- Web typecheck/build and full harness verification after the device-tab query-string wiring change.

### Risks / rollout notes

- The `?tab=` support is intentionally lightweight and local to the page; it does not currently synchronize tab changes back into the URL after the page loads.

## Deployment deep-links can prefilter rollout targets by device (2026-04-17)

### What changed

- Extended `/releases` route-search support with `targetDeviceId`.
- Releases now hydrates its existing rollout target search box from that route-search value.
- Deployment links from System search and Live events now carry the target device through when it is known.

### Why it changed

- Deployment results already opened the right rollout, but operators still had to re-enter the target device to inspect the relevant rollout row.
- This makes deployment-focused follow-up work materially tighter.

### How it was validated

- Web typecheck/build and full harness verification after the route-search wiring change.

### Risks / rollout notes

- This only preloads the existing rollout target search; it does not add any new target selection state beyond what the page already supports.

## Live alert rows now open a filtered alert feed (2026-04-17)

### What changed

- Updated Live alert links to use the existing alert-feed URL filter contract instead of linking to the generic Alerts page.
- Live alert rows now carry the current alert type, device id, and severity into the destination alert feed.

### Why it changed

- System search hits for alerts already landed on a filtered alert feed, but Live alert rows still forced an extra manual filtering step.
- This brings those two alert follow-up workflows into alignment.

### How it was validated

- Web typecheck/build and full harness verification after the alert-link change.

### Risks / rollout notes

- This relies on the Alerts page continuing to honor the current query-string filter contract.

## Alert links now land on the feed section (2026-04-17)

### What changed

- Added a stable `#alerts-feed` anchor to the Alerts feed section.
- Updated both System search hits and Live alert links to target that anchor after applying the existing alert filters.

### Why it changed

- Alert links already carried the right filter state, but still dropped operators at the top of the Alerts page.
- This removes another unnecessary scroll step from alert follow-up workflows.

### How it was validated

- Web typecheck/build and full harness verification after the anchor/deep-link change.

### Risks / rollout notes

- This depends on the Alerts page keeping the `alerts-feed` anchor stable.

## Ingestion and drift search hits can prefilter by batch id (2026-04-17)

### What changed

- Added lightweight `batchId` route-search support on `/admin`.
- Admin now hydrates a local batch-id filter for the Ingestions and Drift tabs from that route state.
- Ingestion-batch and drift-event search hits now carry the relevant batch id into the destination tab.

### Why it changed

- Ingestion and drift search hits already landed on the correct Admin tab, but they still lacked enough context to isolate the exact batch of interest.
- This makes audit follow-up materially tighter without adding backend complexity.

### How it was validated

- Web typecheck/build and full harness verification after the route-search wiring change.

### Risks / rollout notes

- The batch-id filter is local to the currently loaded page of ingestion/drift results, not a backend-filtered batch lookup surface.

## Admin deep-links now target the right results section (2026-04-17)

### What changed

- Added stable anchors for the Admin results sections:
  - `#admin-events`
  - `#admin-ingestions`
  - `#admin-drift`
  - `#admin-notifications`
  - `#admin-exports`
- Updated System search hits and Live admin-oriented links to target those anchors when they open the relevant Admin tab.

### Why it changed

- Admin-oriented links already chose the right tab, but still landed operators at the top of a long page.
- This tightens landing state without changing backend contracts or page structure.

### How it was validated

- Web typecheck/build and full harness verification after the anchor/deep-link changes.

### Risks / rollout notes

- This depends on those Admin section anchors remaining stable.

## Procedure-definition search hits now anchor into the right Admin section (2026-04-17)

### What changed

- Added a stable `#procedure-definitions` anchor around the Admin procedure-definition section.
- Updated procedure-definition search hits so they open `/admin` with the existing procedure filter plus that section anchor.

### Why it changed

- Procedure-definition hits already prefilled the right filter, but still landed operators at the top of a long Admin page.
- This makes the landing state materially tighter without adding any new backend or router surface.

### How it was validated

- Web typecheck/build and full harness verification after the anchor/deep-link change.

### Risks / rollout notes

- This relies on the browser’s normal hash navigation and the Admin page keeping the `procedure-definitions` anchor stable.

## Releases links now land on the relevant section (2026-04-17)

### What changed

- Added stable anchors for the main Releases sections:
  - `#releases-publish-manifest`
  - `#releases-launch-deployment`
  - `#releases-manifests`
  - `#releases-deployments`
  - `#releases-deployment-inspector`
- Updated System search and Live release-oriented links so:
  - deployment hits land on the deployment inspector
  - release-manifest hits land on the manifest section

### Why it changed

- Release-oriented links already picked the right ids, but still dropped operators at the top of a long page.
- This tightens rollout follow-up work without changing backend contracts.

### How it was validated

- Web typecheck/build and full harness verification after the anchor/deep-link changes.

### Risks / rollout notes

- This depends on the Releases page keeping those section anchors stable.

## Fleet search hits now land on the fleet devices section (2026-04-17)

### What changed

- Added a stable `#fleet-devices` anchor to the Fleets page device-membership section.
- Updated fleet search hits so they open the selected fleet plus that section anchor.

### Why it changed

- Fleet search hits already selected the correct fleet, but still landed operators at the top of the page.
- This makes fleet-governance follow-up work tighter without changing backend behavior.

### How it was validated

- Web typecheck/build and full harness verification after the anchor/deep-link change.

### Risks / rollout notes

- This depends on the Fleets page keeping the `fleet-devices` anchor stable.

## Device reported state is now searchable (2026-04-17)

### What changed

- Extended unified search with the `device_state` entity.
- Updated the System page default search entity set to include device-reported state.
- Device Detail state tab now supports a lightweight key filter, and device-state search hits use it via `?tab=state&stateKey=...`.

### Why it changed

- Reported state was a first-class device-cloud surface, but it was still invisible to global search and lacked a direct landing state.
- This closes another practical gap around viewer-facing device-state discoverability.

### How it was validated

- Added regression coverage in `tests/test_operator_tools_routes.py` for mixed search results containing device state.
- Web typecheck/build and full harness verification after the search and device-tab filter wiring changes.

### Risks / rollout notes

- The state-key filter is local to the loaded state tab data, not a backend-filtered state lookup surface.

## Device-detail links now land on the right section (2026-04-17)

### What changed

- Added stable anchors for the key Device Detail sections:
  - `#device-state`
  - `#device-procedures`
  - `#device-events`
- Updated System search hits and Live links so device state, device events, and procedure invocations land on the relevant tab and section.

### Why it changed

- Those links already chose the right tab, but still landed operators at the top of a long device page.
- This tightens device-scoped follow-up work without changing backend behavior.

### How it was validated

- Web typecheck/build and full harness verification after the anchor/deep-link changes.

### Risks / rollout notes

- This depends on the Device Detail page keeping those section anchors stable.

## Media objects are now searchable (2026-04-17)

### What changed

- Extended unified search with the `media_object` entity.
- Updated the System page default search entity set to include media objects.
- Device Detail media tab now accepts a lightweight `mediaCamera` landing-state parameter, and media-object search hits use it.

### Why it changed

- Media is a first-class device surface, but it was still invisible to the main operator search workflow.
- This closes another practical discovery gap around device media follow-up.

### How it was validated

- Added regression coverage in `tests/test_operator_tools_routes.py` for mixed search results containing media objects.
- Web typecheck/build and full harness verification after the search and media-tab wiring changes.

### Risks / rollout notes

- Media metadata is searchable, but actually opening media still depends on the existing per-device token flow in Device Detail.

## Deployment events are now searchable (2026-04-17)

### What changed

- Extended unified search with the admin-only `deployment_event` entity.
- Updated the System page default search entity set to include deployment events.
- Deployment-event search hits now land on the Releases deployment inspector with the deployment and target device preloaded.

### Why it changed

- Deployment events were visible in live/history, but still absent from the main operator search workflow.
- This closes another practical discovery gap in rollout investigation.

### How it was validated

- Added regression coverage in `tests/test_operator_tools_routes.py` for mixed search results containing deployment events.
- Web typecheck/build and full harness verification after the search wiring change.

### Risks / rollout notes

- Deployment-event search remains admin-only because it exposes rollout audit details.

## Release-manifest lifecycle events are now searchable (2026-04-17)

### What changed

- Extended unified search with the admin-only `release_manifest_event` entity.
- Updated the System page default search entity set to include release-manifest lifecycle events.
- Release-manifest-event search hits now land on the Releases manifest section with the relevant manifest id preloaded when available.

### Why it changed

- Manifest lifecycle changes were visible in event feeds, but still absent from the main operator search workflow.
- This closes another practical discovery gap in release governance investigation.

### How it was validated

- Added regression coverage in `tests/test_operator_tools_routes.py` for mixed search results containing release-manifest events.
- Web typecheck/build and full harness verification after the search wiring change.

### Risks / rollout notes

- Release-manifest-event search remains admin-only because it exposes privileged release audit details.

## Access grants are now searchable (2026-04-17)

### What changed

- Extended unified search with the admin-only entities:
  - `device_access_grant`
  - `fleet_access_grant`
- Updated the System page default search entity set to include both grant types.
- Added lightweight Admin route-state hydration so those hits can preselect the relevant device or fleet and land on the right governance section.

### Why it changed

- Device and fleet access grants are core governance surfaces, but they were still absent from the main operator search workflow.
- This closes another practical discovery gap in access-management follow-up work.

### How it was validated

- Added regression coverage in `tests/test_operator_tools_routes.py` for mixed search results containing access grants.
- Web typecheck/build and full harness verification after the search and landing-state wiring changes.

### Risks / rollout notes

- Access-grant search remains admin-only because it exposes privileged governance details.

## Media-object search hits now land on the media section (2026-04-17)

### What changed

- Added a stable `#device-media` anchor to the Device Detail media section.
- Media-object search hits already carried that anchor; they now land on a real target instead of the top of the page.

### Why it changed

- Media-object search hits already opened the correct device and camera filter, but they still landed operators above the media section itself.
- This removes another unnecessary scroll step from device-media follow-up workflows.

### How it was validated

- Web typecheck/build and full harness verification after the anchor fix.

### Risks / rollout notes

- This depends on the Device Detail page keeping the `device-media` anchor stable.
