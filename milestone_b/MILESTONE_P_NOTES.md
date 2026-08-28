# Milestone P notes — what is real, what remains

Status against [../MILESTONE_P_PLAN.md](../MILESTONE_P_PLAN.md). **396 tests green.**
All 10 days built. Moves "real artifact/version tracking" off the
`IMPLEMENTATION_STATUS.md` "still requiring real implementation" list.

## Real after Milestone P

| Area | Module | Notes |
|---|---|---|
| Blob store | `app/services/artifacts/store.py` | SQLite `blob{sha, bytes, kind, data, ts}` — sha-256 keyed, **deduped** (`INSERT OR IGNORE`). Text stored utf-8; content over `MAX_ARTIFACT_BYTES` (2 MiB) stored truncated with `truncated=True`. `check_same_thread=False` so the desktop shell can read while the orchestrator writes. |
| Version chain | `store.version{id, logical_key, kind, sha, task_id, parent_id, trust, truncated, archived, meta, ts}` | `put(kind, content, *, task_id, logical_key, parent_id=None, trust, meta)`. An omitted `parent_id` auto-links to `latest_for(logical_key)`. **Idempotent** on `(logical_key, sha, task_id)` — a resume never duplicates a version. Returns an `ArtifactRef` (`app/services/artifacts/ref.py`). |
| Retrieval | `get(id)` / `content(id)` / `text(id)` / `latest_for(key)` / `history(key)` (newest→oldest) / `chain(id)` (walks `parent_id`, cycle-safe) / `all(include_archived=)` / `active()`. |
| Diff between versions | `diff_versions(a_id, b_id)` → `difflib.unified_diff` (3 lines context) for text kinds (`diff` / `research_answer` / `kb_answer` / `document`); `""` for `file_snapshot`, a kind mismatch, or a missing id. |
| Retention (§11.3) | `archive_before(ts)` sets `archived=1` on older versions and returns the count — **marks, never deletes**. Nothing in the store has a delete path. |
| Orchestrator wiring | `orchestrator._store_artifact` / `_logical_key` / `_last_store_id` | `self.artifacts` opt-in. The four deliverable paths write a versioned artifact when a store is attached: `_execute` → `diff` (key `objective:<sha1>`); `_run_research` → `research_answer` at the answer's `retrieved_web` trust (key `q:<sha1>`); `_run_doc_analysis` → `kb_answer` at `doc_input` trust; `_run_authoring` → `document` (rendered text, `workspace`, key `doc:<sha1(title)>`). The `ARTIFACT` event payload gains `store_id`, `sha`, `parent_id`, `logical_key`, `artifact_kind`, `trust`. `TaskResult.artifact_ref` becomes the store id when wired (was the bare `ArtifactVersion.id` / `answer.id`). Store unset → the `ARTIFACT` event and `TaskResult` are byte-identical to Milestone O. |
| Desktop shell | `app/ui/server.py` | `UIServer(..., artifacts=<ArtifactStore>)` (opt-in). `GET /api/artifacts/{id}` → `{ref, text}` (read-only); the `ref` carries `trust` so a UI can badge it. Unknown id / no store → 404. |
| Schema | `+ ArtifactRef`, `ArtifactKind` Literal. |

## Security posture (§12)

- `put()` **requires an explicit `trust`**; the deliverable paths pass the answer's own
  `trust_level` (`retrieved_web` / `doc_input`), so a `research_answer` / `kb_answer` version
  keeps its trust in the `version` row and `GET /api/artifacts/{id}` returns it. The store
  never defaults a non-diff artifact to `workspace`, i.e. it cannot launder retrieved/doc
  content into workspace trust.
- The store writes **no file** and makes **no network call**. Materialising an artifact to
  disk stays an explicit `fs.write`-scoped step (out of scope here).
- The `ARTIFACT` event remains the timeline's source of truth; the store is the retrievable
  content layer, reconciled by `store_id`. Double-write is deliberate.

## Not yet real / deferred

- **No filesystem materialisation** — the store holds bytes, not files. Writing a rendered
  document to disk is an explicit capability-scoped step.
- **Binary artifact kinds** (images, PDF, `.docx` bytes) — the store already takes `bytes`;
  they arrive when the Milestone M renderers are real.
- **No packing / compression** — SQLite blob + sha dedup is enough for a single-user slice.
- **`logical_key` is a convenience** — it groups versions for `history()`; it is not a
  correctness boundary (every version is retrievable by id, and `parent_id` can be set
  explicitly). Two phrasings of the same objective get different keys.
- **Archive migration is manual** — `archive_before()` is the mechanism; a scheduler (desktop
  shell) drives the §11.3 "after 1 year" tier later.
- **The frontend does not yet render artifact content** — the `/api/artifacts/{id}` route
  exists; a timeline "view artifact" panel is a small `app.js` follow-up.

## Deferred past P (unchanged)

Filesystem materialisation; binary renderers (with Milestone M); a UI artifact viewer;
Milestone A hardening (Postgres / Redis / full telemetry); the live-harness runs and the
Tauri native build (need the subscription / toolchain).
