# Milestone P — Artifact & Version Tracking Plan


---

## 1. Purpose

Every deliverable path already sets `TaskResult.artifact_ref`, but it points at a bare id
(an `ArtifactVersion.id`, a `ResearchAnswer.id`, a `KBAnswer.id`, a `DocumentModel.id`) with
**nothing behind it**: no store, no content addressing, no lineage between a task's output
and the one before it, no way to pull the actual bytes back. `ArtifactVersion` is a flat
event with a diff string.

Milestone P adds the store §11.3 assumes exists:

- a **content-addressed blob store** (SQLite, sha-256 keyed, dedup) for every artifact kind —
  `diff`, `research_answer`, `kb_answer`, `document`, `file_snapshot`;
- a **version chain per logical artifact** — successive outputs for the same objective / file
  / document link `parent → child`, with a text diff between adjacent text versions;
- **retrieval** — `get(id)`, `content(id)`, `history(logical_key)`, `diff_versions(a, b)`;
- **wiring** — the four deliverable paths write to the store when one is attached; the
  `ARTIFACT` event carries the store id + sha + parent; the desktop shell can serve content.

Guiding rules:
- **§11.3** — artifacts are canonical: never auto-deleted. `archive_before(ts)` *marks*
  old versions, it does not remove them.
- **Additive** — `self.artifacts` unset → the flat `ArtifactVersion` event path is
  unchanged. The store is opt-in.
- **Content-addressed** — identical content stored twice returns the same blob; the version
  row is still distinct (a re-run that produces the same diff is a new version pointing at
  the same blob).
- **Trust travels** — a stored `research_answer` / `kb_answer` keeps its `trust_level` in the
  version metadata; the store never launders `retrieved_web` / `doc_input` content into
  `workspace` trust.

## 2. In scope

| Concern | Milestone P implementation |
|---|---|
| Blob store | `artifacts/store.py`: SQLite `blob{sha, bytes, kind, data, ts}` (dedup on `sha`) + `version{id, logical_key, kind, sha, task_id, parent_id, trust, meta, ts, archived}`. `put(kind, content: str|bytes, *, task_id, logical_key, parent_id=None, trust="workspace", meta={}) -> ArtifactRef`. Text stored utf-8; large content capped at `MAX_ARTIFACT_BYTES` (records a truncation flag). |
| ArtifactRef | `artifacts/ref.py`: `ArtifactRef{id, sha, kind, bytes, task_id, logical_key, parent_id, trust, ts, truncated}` (pydantic). `ArtifactKind = Literal["diff","research_answer","kb_answer","document","file_snapshot"]`. |
| Version chain | `logical_key` groups versions. `put(parent_id=)` links to a predecessor; if omitted, `put` auto-links to `latest_for(logical_key)`. `history(logical_key) -> [ArtifactRef]` newest→oldest; `chain(id) -> [ArtifactRef]` walks `parent_id`. |
| Retrieval | `get(id) -> ArtifactRef | None`, `content(id) -> bytes | None`, `text(id) -> str`, `latest_for(logical_key)`. |
| Diff between versions | `diff_versions(a_id, b_id) -> str` — unified diff (`difflib.unified_diff`) for text kinds; `""` for binary/mismatched kinds. |
| Retention | `archive_before(ts) -> int` sets `archived=1` on versions older than `ts` (returns count); nothing is deleted. `active()` / `all(include_archived=)`. |
| Orchestrator wiring | `self.artifacts = None` opt-in. `_store_artifact(task_id, kind, content, *, logical_key, trust, meta)` helper. In `_execute`: after the `ArtifactVersion` event, also `put("diff", out.diff, logical_key=f"task-objective:{objective_hash}")` and set the returned id. In `_run_research` / `_run_doc_analysis` / `_run_authoring`: `put("research_answer"|"kb_answer"|"document", <serialised>, logical_key=<question/title hash>, trust=<answer.trust_level>)`. `TaskResult.artifact_ref` becomes the store id when the store is wired; the `ARTIFACT` event payload gains `store_id`, `sha`, `parent_id`, `logical_key`. Unset → unchanged. |
| Desktop shell | `app/ui/readmodels.py` + `server.py`: when the server is constructed with an `artifacts` store, `GET /api/artifacts/{id}` returns `{ref, text}` and `task_timeline` rows for `ARTIFACT` events carry the `store_id`. Read-only. |
| Events | no new kind — the `ARTIFACT` payload is extended; `history` / `diff_versions` are store queries, not events. |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Filesystem materialisation of an artifact (write the doc to disk) | an explicit `fs.write`-scoped step; the store holds bytes, not files |
| Git-object-style packing / compression | later — SQLite blob + sha dedup is enough for the slice |
| Cross-machine artifact sync | never (single-user) |
| Binary artifact types (images, PDFs, .docx bytes) | when the M renderers produce them — the store already takes `bytes` |
| Signed / notarised artifacts | later ops concern |
| Automatic archive-tier migration (§11.3 "after 1 year") | `archive_before()` is the mechanism; a scheduler drives it later |

## 4. Component layout

```
app/services/artifacts/
  ref.py       ArtifactRef, ArtifactKind
  store.py     ArtifactStore — blob + version tables; put / get / content / history /
               chain / latest_for / diff_versions / archive_before
app/schemas/contracts.py            + ArtifactRef re-export (or define here)
app/orchestration/orchestrator.py   opt-in self.artifacts; _store_artifact(); thread the 4 paths
app/ui/readmodels.py + app/ui/server.py   GET /api/artifacts/{id} when a store is wired
tests/
  unit/         test_artifact_store (dedup / chain / history / diff_versions / archive)
  integration/  test_artifact_lineage (a diff task then a re-run supersedes; a research task
                stores a research_answer with its trust level)
```

## 5. Work breakdown (~10 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `artifacts/ref.py` + `artifacts/store.py` schema + `put` (sha dedup, auto-parent-link, truncation cap) + `get` / `content` / `text` / `latest_for`. Unit: two `put`s of identical content share a `sha` but get distinct version ids; `latest_for` returns the newest. |
| 3–4 | `history(logical_key)` + `chain(id)` (parent walk, cycle-safe) + `diff_versions(a, b)` (unified diff for text kinds). Unit: a 3-version chain returns newest→oldest; `diff_versions` shows the change; a binary kind returns `""`. |
| 5 | `archive_before(ts)` + `active()` / `all(include_archived=)`. Unit: archiving marks, never deletes; `active()` excludes archived. |
| 6–7 | Orchestrator wiring — `self.artifacts` opt-in; `_store_artifact()`; thread `_execute` (diff) + `_run_research` + `_run_doc_analysis` + `_run_authoring`; extend the `ARTIFACT` event payload; `TaskResult.artifact_ref` = store id when wired. Integration: a `code_edit_local` task stores a `diff` artifact and `TaskResult.artifact_ref` resolves via `store.get()`. |
| 8 | Integration — re-running the same objective stores a **second** version whose `parent_id` is the first and whose `history()` has length 2; a `research_web` task stores a `research_answer` version at `retrieved_web` trust; `diff_versions` between two document versions is non-empty. |
| 9 | Desktop shell — `GET /api/artifacts/{id}` (opt-in on the server's `artifacts` arg) returns `{ref, text}`; `task_timeline` `ARTIFACT` rows carry `store_id`. Integration test on the real socket. |
| 10 | Regression; `../nexus/MILESTONE_P_NOTES.md`; update [STATUS.md](../STATUS.md), the [connective index](../requirements.md), and the top-level [README.md](../../README.md); commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `put` dedupes identical content to one `blob` row but distinct `version` rows;
  an omitted `parent_id` auto-links to `latest_for(logical_key)`; `history` is
  newest→oldest and `chain` walks `parent_id` without looping on a malformed cycle;
  `diff_versions` yields a unified diff for two text versions and `""` for a binary kind or a
  kind mismatch; `archive_before` marks and never deletes, `active()` excludes archived;
  content over `MAX_ARTIFACT_BYTES` is stored truncated with `truncated=True`.
- **Integration** — with `orch.artifacts` wired: a `code_edit_local` completion produces an
  `ARTIFACT` event carrying a `store_id` that `store.get()` resolves, and
  `TaskResult.artifact_ref` equals it; a second run of the same objective yields
  `history(logical_key)` of length 2 with `parent_id` set; a `research_web` task stores a
  `research_answer` version whose `trust == "retrieved_web"`; artifacts unset → the
  `ARTIFACT` event and `TaskResult` are byte-identical to Milestone O.
- **Failure** — `get`/`content` on an unknown id returns `None`, not an exception; a
  `diff_versions` with one missing id returns `""`; a store opened on a read-only path
  degrades to in-memory with a logged note (or raises a clear error — decide and test one).
- **Security (§12)** — a stored `research_answer` / `kb_answer` keeps its `trust` in the
  version row; nothing in the store path elevates trust; the store writes no file and makes
  no network call; `GET /api/artifacts/{id}` is read-only and returns the stored `trust` so a
  UI can badge it.
- **Recovery** — `reconcile()` + `resume()` work with the artifact tables present; an
  interrupted task that wrote a version leaves it (canonical, not rolled back) and a resume
  does not duplicate it (idempotent on `(logical_key, sha, task_id)`).
- **Benchmark** — n/a.

## 7. Tunable starting values

- `MAX_ARTIFACT_BYTES` = **2 MiB** (text deliverables; a truncation flag beyond).
- `logical_key` for a code task = `f"objective:{sha1(objective)[:12]}"`; for a document =
  `f"doc:{sha1(title)[:12]}"`; for research/KB = `f"q:{sha1(question)[:12]}"`.
- Archive threshold (operator-driven): **365 days** per §11.3.
- `diff_versions` context lines = **3**.

## 8. Risks

- **`logical_key` collisions / misses** — two different objectives that hash-collide would
  share a chain; two phrasings of the same objective would not. Accepted: the key is a
  convenience for `history()`, not a correctness boundary — every version is independently
  retrievable by id, and `parent_id` can be set explicitly.
- **Store growth** — every run appends a version. Blobs dedupe; version rows are small.
  `archive_before` + the never-delete rule mean growth is bounded by real output volume, not
  runaway; a single-user machine will not stress SQLite here.
- **Double-write** — the flat `ArtifactVersion` event *and* the store row. Kept deliberately:
  the event stays the source of truth for the timeline; the store is the retrievable content
  layer. They are reconciled by `store_id` on the event.
- **Trust laundering** — the one real risk. Mitigated: `put` requires an explicit `trust`
  and the deliverable paths pass the answer's own `trust_level`; the store never defaults a
  non-diff artifact to `workspace`.

## 9. Deliverables

- `app/services/artifacts/` — `ref.py`, `store.py`.
- `ArtifactRef` schema; extended `ARTIFACT` event payload.
- Orchestrator: opt-in `ArtifactStore`; the four deliverable paths store versioned,
  content-addressed artifacts with lineage.
- Desktop shell: `GET /api/artifacts/{id}` (opt-in).
- Test suite: the current 384 green, plus unit (store) and integration (lineage / trust /
  shell).
- `../nexus/MILESTONE_P_NOTES.md`.
- [STATUS.md](../STATUS.md), the
  [connective index](../requirements.md), and the
  top-level [README.md](../../README.md) updated: "real artifact/version tracking" moves off the
  "still requiring real implementation" list to FOUNDATION.
