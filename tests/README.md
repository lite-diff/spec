# lite-diff v1.1 conformance corpus

Acceptance tests for implementations of **lite-diff v1.1** (`../SPEC.md`).
Every expected result in this directory was derived from the normative text alone: the corpus was written
from the text before any implementation existed, then aligned with the reference implementation
(`../reference/`) and the published text. Cases whose expectation follows a specific rule of the change list
cite the §12 item in their `notes`.
Where the text admits two readings, the case is marked `"uncertain": true` and the choice is documented in
[AMBIGUITIES.md](AMBIGUITIES.md).

| Group | Cases | Uncertain |
|-------|------:|----------:|
| `parse/` | 51 | 0 |
| `body/` | 24 | 1 |
| `headers/` | 16 | 0 |
| `paths/` | 35 | 0 |
| `matching/` | 39 | 0 |
| `levels/` | 11 | 0 |
| `boundary/` | 16 | 1 |
| `operations/` | 28 | 0 |
| `eof/` | 23 | 0 |
| `result/` | 18 | 0 |
| `generator/` | 10 | 0 |
| **total** | **271** | **2** |

## Layout

```
tests/
  README.md          this file
  AMBIGUITIES.md     places where the text is not deterministic, contradictory, or not testable
  run.py             the runner (Python 3, standard library only)
  cases/<group>/<case-id>/
    case.json        metadata
    input/           workspace before the patch (may be empty)
    patch.diff       the lite-diff document, byte-exact
    expected/        workspace after the patch (applied/checked cases, and result/ failure cases)
    expected.json    asserted subset of the result JSON (Appendix B)
```

### case.json

```json
{
  "id": "matching-E414-three-candidates",
  "title": "a short anchor matching three places is E414 listing all of them",
  "spec": ["§8.2", "§8.6"],
  "options": {"first-match": true},
  "uncertain": false,
  "notes": "free text: how the expectation follows from the cited sections",
  "setup": {"symlinks": {"link.txt": "target.txt"}}
}
```

- `id` is globally unique and equals the directory name; it starts with the group name.
- `spec` lists the sections the expectation is derived from.
- `options` is informative: the global options found in the patch preamble.
- `uncertain: true` means the expectation rests on one of two readings recorded in AMBIGUITIES.md. A failure
  of such a case is a question for the spec authors before it is a bug in the implementation.
- `setup` (optional) asks the runner to prepare things that cannot be stored as plain files. The only key is
  `symlinks` (`{link: target}`, created in the workdir after copying `input/`). Where the platform cannot
  create symbolic links the case is reported as `SKIP`.
- `platforms` (optional) is a list of `"windows"` / `"posix"`; on any other platform the case is reported as
  `SKIP`. Used for the platform rule of §6.3.5 (a colon in a path is E100 on Windows only).

### patch.diff

Stored byte-exact. Files that are about trailing whitespace, blank lines, tabs, CRLF or a missing final newline
really contain them; do not open and re-save these files with an editor that normalizes whitespace. Patches use
LF line endings except `eof-crlf-patch-file`.

### expected/ and expected.json

`expected/` is the complete workspace after the run. It exists for cases whose status is `applied` or `checked`,
and for the failure cases of `result/`, where it equals `input/` (atomicity: nothing is written).

`expected.json` contains:

| Key | Meaning |
|-----|---------|
| `status` | always present, always compared (`applied` / `checked` / `failed`) |
| `diagnostics` | expected diagnostics; each must match a **distinct** reported diagnostic; order is not significant; diagnostics that are not listed are allowed |
| `blocks`, `liteDiffVersion`, … | any other Appendix B field, compared as a subset (see below) |
| `absent` | runner key: workspace paths (files or directories) that must not exist after the run |
| `exactTree` | runner key: the workdir must contain exactly the files under `expected/` (no extra files) |
| `forbidDiagnostics` | runner key: codes that must **not** be reported |
| `diagnosticCounts` | runner key: `{code: n}`: the code must be reported exactly n times |

**Subset rule** (Appendix B, last paragraph): an object matches when every key it mentions is present in the
result and matches recursively; keys not mentioned are not compared. An array matches when it has the same
length and its elements can be matched one-to-one in any order (blocks and hunks carry `ordinal`, so they are
effectively matched by ordinal; `candidates` are compared as a set of positions). Scalars compare by equality;
booleans never equal numbers. The `diagnostics` array is the exception: it is a subset (see table).

All line numbers are 1-based (§8.6): `patchLine`, `cursor`, `appliedRange.firstLine`, `scopeLine`,
`candidates[].line`, `bestCandidate.line`, `bestCandidate.appearsAlreadyAppliedAt`.

What the corpus asserts per diagnostic: `code` always; `patchLine` for parse-phase codes when the offending line
is identifiable; `block` (file-system codes, W412 of a hunk-less block, W601, W603) or `block` + `hunk`
(matching codes); and the mandatory content of §8.6 that Appendix B can express (`candidates[].line`,
`classification`, `cursor`, `bestCandidate.line` / `failedElementIndex` / `classification` /
`wouldMatchIgnoringAllSpace` / `appearsAlreadyAppliedAt` / `segment`, `reindent`). Message texts, `hint`,
`severity`, `escalated` and the visible-whitespace renderings are never compared.

## Runner contract

```
python tests/run.py --impl "<command>" [--only <glob>] [-v] [--keep] [--timeout S]
python tests/run.py --list [--only <glob>]
```

For each selected case the runner

1. creates a fresh temporary directory, copies `input/` into `<tmp>/work` and `patch.diff` to `<tmp>/patch.diff`
   (so an implementation cannot damage the corpus), and performs `setup`;
2. runs `<command> <tmp>/patch.diff <tmp>/work` through the shell (the two paths are appended, quoted);
3. reads **stdout** as one JSON document per Appendix B. A non-zero exit status is allowed when the document
   failed; it is a failure when the reported status is `applied` or `checked`;
4. compares: (1) every file under `expected/` byte-for-byte with the workdir, (2) every path in `absent` must
   not exist, (2a) with `exactTree` no other file may exist, (3) `expected.json` against the result JSON with
   the subset rule above (`status` always compared; diagnostics by code plus asserted fields, order not
   significant; `forbidDiagnostics`, `diagnosticCounts`).

It prints a PASS/FAIL/SKIP line per case and a summary, and exits non-zero if any case failed. `--only` accepts
shell globs matched against the case id and against `<group>/<case-id>` (e.g. `--only "eof-*"`,
`--only "matching/*E41?*"`); it may be repeated. `--list` prints the case ids with their spec references and
marks uncertain cases. `-v` prints every mismatch of a failing case, `--keep` keeps the workdirs.

### Environment assumptions

- **Single root.** The workdir is the only workspace root (named roots, §5.3, are not exercised).
- **Default EOL is LF.** By §12 item 22 this is normative: the default EOL is LF unless `--eol crlf`
  (§5.3) or an equivalent host setting says otherwise. All create cases and `eof-empty-file-eof` expect LF; run
  the implementation without a CRLF host default.
- **Case-sensitive comparisons.** Paths in the corpus never differ only in case.
- **Portable file names.** No corpus file name contains a colon (impossible on Windows). A colon in a patch path
  is E100 on Windows and an ordinary character elsewhere (§6.3.5), so `paths-colon-E100-windows` runs on Windows
  only and `paths-colon-is-ordinary` on POSIX only, under `--check` (`platforms` in `case.json`; AMBIGUITIES R17).
- The implementation writes nothing outside the workdir and leaves no temporary files in it.

## Adding a case

1. Pick the group and a slug; the id is `<group>-<slug>` and must be unique.
2. Create `cases/<group>/<id>/` with `case.json`, `input/` (may be empty), `patch.diff` and `expected.json`;
   add `expected/` for `applied`/`checked` results. Write files with a tool that does not touch whitespace or
   line endings (e.g. a short Python script that writes bytes). Keep input files under 40 lines.
3. Derive every expectation from a cited section. Assert only what the text makes mandatory; prefer
   `forbidDiagnostics` to prove that a misreading does not happen.
4. If the text supports two readings, choose one, set `"uncertain": true`, and add an entry to AMBIGUITIES.md
   (case id, section, both readings, the choice).
5. Run `python tests/run.py --list` to check that the corpus loads, and add the case to the coverage table.

## Coverage (section → cases)

| Section | Cases |
|---------|-------|
| §1.1 | `parse-binary-files-differ`, `parse-gnu-diff-ruN-strip1`, `body-sentinel-dropped-in-edit`, `headers-unified-with-section`, `paths-unquoted-spaces`, `operations-symlink-mode-W603`, `operations-binary-delete-applied` |
| §1.2 | `parse-format-patch-envelope`, `headers-E403-no-space-BOF`, `headers-E403-at-at-at-at`, `headers-E403-unclosed-unified`, `headers-E403-combined`, `headers-E403-section-without-space`, `operations-symlink-on-disk-E103` |
| §1.3 | `body-blank-matches-whitespace-only`, `body-sentinel-dropped-in-edit`, `body-special-lines-as-insertion`, `matching-ignore-space-change`, `matching-trailing-whitespace-insignificant`, `eof-eof-on-unterminated`, `eof-insert-after-unterminated`, `eof-delete-unterminated-last`, `eof-replace-unterminated-last`, `eof-edit-elsewhere-keeps-unterminated`, `eof-crlf-mixed-preserved`, `eof-mixed-first-terminator-lf`, `eof-crlf-patch-file`, `eof-crlf-unterminated-eof`, `eof-bom-with-bof`, `eof-bom-replace-first-line`, `eof-bom-delete-first-line`, `eof-empty-file-eof`, `generator-python-blank-and-whitespace-context`, `parse-bom-E310`, `parse-invalid-utf8-E310`, `operations-create-misplaced-sentinel-W419`, `eof-context-last-sentinel-keeps-unterminated`, `eof-context-reaches-eof-without-sentinel-terminates`, `eof-eof-hunk-with-sentinel`, `eof-old-side-sentinel-context-then-plus`, `eof-old-side-sentinel-minus-new-side-decides`, `eof-old-side-sentinel-mismatch-W419`, `eof-replace-unterminated-last-with-sentinel`, `eof-sentinel-mid-file-W419`, `eof-sentinel-new-side-unterminates` |
| §2.3 | `body-insert-before-first-anchor`, `generator-add-import` |
| §2.4 | `paths-E608-differing-paths`, `operations-create-empty`, `operations-delete-plain`, `operations-rename-with-edit-hand` |
| §2.5 | `boundary-basic-range-delete` |
| §3.1 | `parse-git-create-sentinel`, `parse-comment-between-blocks`, `parse-comments-allowed`, `parse-gnu-diff-ruN-strip1`, `body-blank-line-empty-context`, `body-blank-matches-whitespace-only`, `body-trailing-blanks-stripped`, `body-tab-first-E401`, `body-hash-in-body-E401`, `body-sentinel-dropped-in-edit`, `body-backslash-section-E401`, `body-E416-empty-hunk`, `body-E411-blank-between-plus-in-BOF`, `matching-cursor-new-coordinates-E413`, `matching-delta-tie-breaker-W410`, `matching-qualifying-trailing-blank-tprime`, `boundary-E511-marker-last`, `operations-create-with-sentinel`, `generator-python-blank-and-whitespace-context`, `parse-comment-run-at-end-of-document`, `parse-comment-run-before-closing-fence`, `parse-comment-run-git-style`, `body-hash-then-body-line-E401`, `body-hash-then-hunk-header-E401`, `eof-context-last-sentinel-keeps-unterminated`, `eof-old-side-sentinel-context-then-plus`, `eof-old-side-sentinel-minus-new-side-decides`, `eof-replace-unterminated-last-with-sentinel`, `eof-sentinel-new-side-unterminates` |
| §3.2 | `parse-indented-diff-git`, `parse-indented-path-header`, `parse-indented-metadata`, `parse-indented-option`, `parse-tab-indented-hunk-header`, `parse-space-indented-hunk-header` |
| §3.4 | `matching-ignore-all-space` |
| §4.1 | `parse-git-edit-index`, `parse-git-create-sentinel`, `parse-delete-then-edit`, `parse-rename-pure-then-rename-edit`, `parse-pair-blank-hunk`, `parse-fenced-closed`, `parse-fenced-trailing-prose`, `parse-stray-body-before-hunk`, `parse-missing-hunk-header`, `parse-comment-between-blocks`, `parse-comments-allowed`, `parse-text-after-last-hunk`, `parse-options-outside-fence`, `parse-format-patch-envelope`, `parse-indented-diff-git`, `parse-indented-path-header`, `parse-indented-metadata`, `parse-indented-option`, `parse-tab-indented-hunk-header`, `parse-space-indented-hunk-header`, `parse-git-binary-patch`, `parse-gnu-diff-ruN-strip1`, `parse-two-hunkless-creates`, `parse-E200-unpaired`, `parse-E200-duplicate`, `parse-E300-option-in-header`, `parse-option-after-plus-is-E404`, `parse-unknown-option-E301`, `parse-pair-across-blank-and-comment`, `parse-hunk-before-block-E306`, `body-lua-comment-edit`, `body-body-pair-W401`, `body-body-pair-then-hunk-header`, `paths-rename-real-dir-a-with-edit`, `paths-E209-rename-to-vs-plus`, `paths-E209-rename-vs-diff-git`, `paths-rename-then-mismatched-pair`, `paths-E604-rename-and-dev-null`, `paths-rename-then-dev-null-pair`, `paths-E210-no-path-source`, `paths-rename-then-create-other-accepted`, `operations-rename-with-edit-git`, `operations-edit-after-rename`, `generator-three-block-fenced`, `parse-comment-run-at-end-of-document`, `parse-comment-run-before-closing-fence`, `parse-comment-run-git-style`, `body-hash-then-body-line-E401`, `body-hash-then-hunk-header-E401` |
| §5 | `parse-fenced-closed`, `parse-indented-option`, `parse-version-marker-E308`, `parse-unknown-option-E301`, `parse-option-with-equals-E306`, `result-applied-ranges-and-scope-line`, `parse-first-match-off`, `parse-profile-10-implied-first-match-no-conflict`, `parse-strip-invalid-E301` |
| §5.1 | `body-blank-matches-whitespace-only`, `matching-ignore-blank-lines-plus-after-last`, `matching-ignore-blank-lines-plus-between`, `matching-ignore-blank-lines-empty-minus`, `matching-ignore-blank-lines-skip-before-minus`, `matching-ignore-space-change`, `matching-ignore-space-change-presence`, `matching-ignore-all-space`, `matching-trailing-whitespace-insignificant`, `generator-python-blank-and-whitespace-context`, `matching-ignore-blank-lines-empty-anchor-E410`, `matching-ignore-blank-lines-removed-blank-ends-run` |
| §5.2 | `parse-block-option-first-match`, `parse-block-option-E305`, `paths-auto-rename`, `matching-first-match`, `matching-header-beats-first-match`, `matching-apply-all-matches`, `matching-apply-all-matches-E304`, `matching-skip-applied-W414`, `levels-indent-shift-tabs-to-spaces`, `levels-indent-shift-prefix-substitution`, `levels-lenient-W416`, `levels-lenient-strict-E307`, `levels-block-lenient-global-strict-E307`, `levels-lenient-after-refused-shift`, `boundary-early-return-strict-fails`, `result-check-mode`, `result-check-mode-failure`, `result-strict-W410`, `result-strict-W412-hunk`, `result-strict-W412-mode-block`, `result-strict-W413`, `result-strict-W418`, `result-strict-W401-parse-failure`, `result-strict-W415-not-escalated`, `matching-W417-reapplied-insertion`, `matching-W417-skip-applied`, `result-strict-W410-exact-hit`, `result-strict-W417` |
| §5.3 | `parse-gnu-diff-ruN-strip1`, `paths-strip-E104`, `paths-strip-0-keeps-letter-prefix`, `paths-npm-scope-plain-path` |
| §5.4 | `parse-E300-option-in-header` |
| §5.5 | `parse-block-option-first-match`, `parse-block-option-is-per-block`, `parse-block-option-E309`, `parse-block-option-E305`, `parse-block-option-E301`, `levels-block-lenient-global-strict-E307`, `parse-block-option-ignore-space-at-eol` |
| §6.1 | `parse-git-edit-index` |
| §6.2 | `parse-git-binary-patch`, `parse-binary-files-differ`, `parse-mode-change-only`, `operations-symlink-mode-W603`, `operations-submodule-mode-W603`, `operations-binary-delete-applied` |
| §6.3.1 | `parse-git-edit-index`, `parse-git-create-sentinel`, `parse-rename-pure-then-rename-edit`, `paths-git-dev-null-without-mode`, `paths-rename-lines-not-stripped`, `paths-E210-no-path-source` |
| §6.3.2 | `parse-E200-unpaired`, `parse-E200-duplicate`, `body-body-pair-residual-shape-E608`, `paths-git-dev-null-without-mode`, `paths-rename-lines-not-stripped`, `paths-rename-real-dir-a-with-edit`, `paths-E608-differing-paths`, `paths-E209-rename-to-vs-plus`, `paths-E209-rename-vs-diff-git`, `paths-rename-then-mismatched-pair`, `paths-E202-diff-git-vs-pair`, `operations-rename-with-edit-git` |
| §6.3.3 | `paths-E100-absolute`, `paths-E101-dot-slash`, `paths-E101-dotdot`, `paths-E102-glob`, `operations-symlink-on-disk-E103` |
| §6.3.4 | `parse-gnu-diff-ruN-strip1`, `paths-unquoted-spaces`, `paths-diff-git-with-spaces`, `paths-diff-git-split-E204`, `paths-quoted-octal-utf8`, `paths-trailing-space-stripped` |
| §6.3.5 | `parse-git-edit-index`, `paths-mnemonic-prefixes`, `paths-letter-R-not-a-prefix`, `paths-real-dir-b-with-prefix`, `paths-real-dir-b-without-prefix-E611`, `paths-rename-lines-not-stripped`, `paths-rename-real-dir-a-with-edit`, `paths-strip-0-keeps-letter-prefix`, `paths-colon-is-ordinary` |
| §6.3.6 | `paths-quoted-octal-utf8`, `paths-nfc-normalization` |
| §6.4.1 | `parse-delete-then-edit`, `parse-rename-pure-then-rename-edit`, `parse-missing-hunk-header`, `parse-edit-block-without-hunks`, `parse-mode-change-only`, `paths-real-dir-b-without-prefix-E611`, `paths-rename-then-dev-null-pair`, `operations-delete-plain`, `operations-copy-with-edit`, `operations-E600-create-existing`, `operations-E601-delete-missing`, `operations-E602-rename-target-exists`, `operations-E603-rename-source-missing`, `operations-E611-edit-missing`, `operations-symlink-mode-W603`, `operations-submodule-mode-W603`, `result-strict-W412-mode-block`, `operations-skipped-block-operation` |
| §6.4.2 | `parse-git-create-sentinel`, `paths-E608-differing-paths`, `paths-auto-rename`, `paths-E604-create-and-delete`, `paths-E604-rename-and-dev-null`, `paths-E605-rename-to-without-from`, `paths-rename-then-create-other-accepted`, `operations-E606-copy-incomplete`, `paths-E605-duplicate-rename-from` |
| §6.4.3 | `parse-rename-pure-then-rename-edit`, `operations-rename-with-edit-git`, `operations-rename-with-edit-hand`, `operations-copy-with-edit`, `operations-E602-rename-target-exists`, `operations-E603-rename-source-missing`, `eof-rename-inherits-crlf`, `generator-three-block-fenced`, `operations-delete-removes-empty-dir`, `operations-rename-removes-empty-dir` |
| §6.4.4 | `parse-git-binary-patch`, `paths-E209-rename-vs-diff-git`, `operations-symlink-on-disk-E103`, `result-parse-errors-all-reported`, `result-match-phase-stops-at-first-failure`, `operations-binary-delete-applied`, `operations-skipped-block-operation` |
| §6.4.5 | `parse-git-create-sentinel`, `parse-delete-then-edit`, `parse-two-hunkless-creates`, `body-E415-context-in-create`, `headers-create-ignores-scope`, `operations-create-empty`, `operations-create-with-sentinel`, `operations-create-header-form-irrelevant`, `operations-delete-git-hunk-ignored`, `operations-delete-with-plus-E415`, `operations-create-then-edit`, `operations-E415-two-hunks-in-create`, `operations-create-misplaced-sentinel-W419` |
| §7.1 | `parse-tab-indented-hunk-header`, `body-dots-and-more-E401`, `body-E411-blank-between-plus-in-BOF`, `headers-bof-insert`, `headers-eof-insert`, `headers-trailing-whitespace-in-headers`, `headers-unified-with-section`, `headers-scope-success`, `headers-scope-E418`, `headers-scope-W418`, `headers-scope-lowercase-bof`, `headers-create-ignores-scope`, `headers-E403-no-space-BOF`, `headers-E403-at-at-at-at`, `headers-E403-unclosed-unified`, `headers-E403-combined`, `headers-E403-section-without-space`, `headers-E417-BOF-not-first`, `headers-E417-EOF-not-last`, `boundary-marker-trailing-ws-zero-capture`, `generator-similar-methods-scoped`, `generator-append-functions-eof`, `eof-eof-hunk-with-sentinel` |
| §7.2 | `parse-pair-blank-hunk`, `parse-comment-between-blocks`, `parse-text-after-last-hunk`, `parse-options-outside-fence`, `body-blank-line-empty-context`, `body-trailing-blanks-stripped`, `body-tab-first-E401`, `body-hash-in-body-E401`, `body-sentinel-dropped-in-edit`, `body-backslash-section-E401`, `body-dots-and-more-E401`, `body-lua-comment-edit`, `body-body-pair-W401`, `body-body-pair-then-hunk-header`, `body-body-pair-residual-shape-E608`, `body-E416-empty-hunk`, `body-special-lines-as-context`, `body-special-lines-as-deletion`, `body-special-lines-as-insertion`, `body-two-space-context`, `body-context-only-W412`, `boundary-marker-trailing-ws-zero-capture`, `result-strict-W412-hunk`, `result-strict-W401-parse-failure`, `generator-markdown-front-matter`, `generator-lua-comment-change`, `body-hash-then-body-line-E401`, `body-hash-then-hunk-header-E401` |
| §7.3 | `boundary-basic-range-delete`, `boundary-early-return-W511`, `boundary-early-return-strict-fails`, `boundary-early-return-with-trailing-context`, `boundary-three-segments-interleaved`, `boundary-E510-double-marker`, `boundary-E511-marker-first`, `boundary-E511-marker-last`, `boundary-E511-precedes-E512`, `boundary-E512-context-next-to-marker`, `boundary-W511-window-to-eof`, `boundary-E410-failing-segment`, `boundary-AXAB-E414`, `boundary-context-around-segments`, `generator-replace-long-function`, `generator-three-block-fenced`, `generator-appendix-a5-verbatim`, `boundary-E410-failing-segment-compared-line` |
| §8.1 | `result-third-block-fails`, `result-parse-errors-all-reported`, `result-match-phase-stops-at-first-failure`, `result-parse-errors-suppress-match-phase` |
| §8.2 | `parse-block-option-first-match`, `parse-block-option-is-per-block`, `headers-bof-insert`, `headers-eof-insert`, `headers-trailing-whitespace-in-headers`, `headers-scope-success`, `headers-scope-E418`, `headers-scope-W418`, `headers-scope-lowercase-bof`, `matching-cursor-new-coordinates-E413`, `matching-delta-tie-breaker-W410`, `matching-delta-tie-breaker-explicit-counts`, `matching-non-qualifying-header-E414`, `matching-qualifying-trailing-blank-tprime`, `matching-tprime-must-be-shared`, `matching-overlapping-candidates-E414`, `matching-E414-three-candidates`, `matching-first-match`, `matching-header-beats-first-match`, `matching-E413-shared-context`, `matching-E413-wrong-order`, `matching-E413-above-scope`, `matching-W413-suspicious-order`, `matching-apply-all-matches-overlap-scope`, `matching-E410-leading-whitespace`, `matching-E410-tabs-vs-spaces`, `matching-E410-internal-whitespace`, `matching-E410-other-second-hunk`, `matching-E410-no-line-matched`, `matching-E410-single-line-indent`, `matching-E410-already-applied`, `matching-skip-applied-W414`, `levels-indent-shift-tabs-to-spaces`, `levels-indent-shift-prefix-substitution`, `levels-indent-shift-flush-left`, `levels-indent-shift-sigma-not-function`, `levels-indent-shift-plus-outside-domain`, `levels-lenient-W416`, `levels-exact-wins`, `levels-indent-shift-before-lenient`, `levels-lenient-after-refused-shift`, `boundary-early-return-W511`, `boundary-E410-failing-segment`, `boundary-AXAB-E414`, `boundary-marker-trailing-ws-zero-capture`, `operations-two-blocks-same-path`, `eof-eof-on-unterminated`, `result-strict-W413`, `result-strict-W418`, `result-strict-W415-not-escalated`, `result-applied-ranges-and-scope-line`, `generator-similar-methods-lazy-anchor`, `generator-similar-methods-scoped`, `parse-first-match-off`, `matching-W417-insert-before-anchor`, `matching-W417-reapplied-insertion`, `matching-W417-skip-applied`, `matching-already-applied-before-E413`, `matching-ignore-blank-lines-empty-anchor-E410`, `matching-ignore-blank-lines-removed-blank-ends-run`, `boundary-E410-failing-segment-compared-line`, `result-strict-W410`, `result-strict-W410-exact-hit`, `result-strict-W417` |
| §8.3 | `body-blank-matches-whitespace-only`, `body-insert-before-first-anchor`, `body-E412-anchorless`, `headers-bof-insert`, `headers-eof-insert`, `headers-scope-lowercase-bof`, `matching-ignore-blank-lines-plus-after-last`, `matching-ignore-blank-lines-plus-between`, `matching-ignore-blank-lines-skip-before-minus`, `matching-ignore-space-change`, `boundary-basic-range-delete`, `boundary-early-return-with-trailing-context`, `boundary-three-segments-interleaved`, `boundary-context-around-segments`, `eof-insert-after-unterminated`, `generator-add-import`, `generator-replace-long-function`, `generator-appendix-a5-verbatim`, `generator-append-functions-eof`, `matching-ignore-blank-lines-removed-blank-ends-run` |
| §8.4 | `matching-apply-all-matches`, `matching-apply-all-matches-overlap-scope`, `matching-apply-all-matches-E304`, `parse-profile-10-implied-first-match-no-conflict` |
| §8.5 | `paths-rename-then-dev-null-pair`, `paths-rename-then-create-other-accepted`, `operations-two-blocks-same-path`, `operations-edit-after-rename`, `operations-create-then-edit`, `operations-delete-then-recreate` |
| §8.6 | `parse-fenced-trailing-prose`, `parse-stray-body-before-hunk`, `parse-mode-change-only`, `body-body-pair-W401`, `body-body-pair-residual-shape-E608`, `body-context-only-W412`, `headers-scope-success`, `headers-scope-W418`, `paths-rename-then-mismatched-pair`, `paths-rename-then-dev-null-pair`, `matching-delta-tie-breaker-W410`, `matching-E414-three-candidates`, `matching-E413-shared-context`, `matching-E413-wrong-order`, `matching-W413-suspicious-order`, `matching-E410-leading-whitespace`, `matching-E410-tabs-vs-spaces`, `matching-E410-internal-whitespace`, `matching-E410-other-second-hunk`, `matching-E410-no-line-matched`, `matching-E410-single-line-indent`, `matching-E410-already-applied`, `matching-skip-applied-W414`, `levels-indent-shift-tabs-to-spaces`, `levels-indent-shift-plus-outside-domain`, `levels-lenient-W416`, `boundary-early-return-W511`, `boundary-early-return-strict-fails`, `boundary-E410-failing-segment`, `operations-delete-git-hunk-ignored`, `operations-edit-after-rename`, `operations-delete-then-recreate`, `result-third-block-fails`, `result-parse-errors-all-reported`, `result-check-mode`, `result-check-mode-failure`, `result-strict-W410`, `result-strict-W401-parse-failure`, `result-applied-ranges-and-scope-line`, `result-match-phase-stops-at-first-failure`, `result-parse-errors-suppress-match-phase`, `generator-similar-methods-lazy-anchor`, `matching-W417-skip-applied`, `matching-already-applied-before-E413`, `boundary-E410-failing-segment-compared-line`, `result-check-mode-continues-past-failure`, `result-check-mode-hunks-after-failure`, `result-strict-W417` |
| §9.2 | `paths-git-dev-null-without-mode`, `eof-context-last-sentinel-keeps-unterminated`, `eof-replace-unterminated-last-with-sentinel`, `eof-sentinel-mid-file-W419`, `eof-sentinel-new-side-unterminates` |
| §10 | `parse-edit-block-without-hunks`, `parse-block-option-E301`, `body-E412-anchorless`, `boundary-E511-precedes-E512`, `parse-bom-E310`, `parse-empty-document-W302`, `parse-invalid-utf8-E310`, `parse-options-only-W302`, `parse-strip-invalid-E301`, `paths-E605-duplicate-rename-from`, `paths-colon-is-ordinary`, `paths-colon-E100-windows`, `matching-W417-reapplied-insertion`, `operations-create-misplaced-sentinel-W419`, `eof-old-side-sentinel-mismatch-W419`, `eof-sentinel-mid-file-W419` |
| §11 | `operations-two-blocks-same-path`, `eof-crlf-mixed-preserved`, `eof-mixed-first-terminator-lf`, `eof-rename-inherits-crlf` |
| Appendix A.1 | `parse-text-after-last-hunk`, `paths-E101-dot-slash`, `eof-bom-with-bof`, `generator-add-import`, `generator-similar-methods-scoped`, `generator-replace-long-function`, `parse-comment-run-git-style` |
| Appendix A.2 | `body-special-lines-as-context`, `body-special-lines-as-deletion`, `body-special-lines-as-insertion`, `generator-markdown-front-matter` |
| Appendix A.3 | `parse-option-after-plus-is-E404` |
| Appendix A.4 | `generator-similar-methods-lazy-anchor` |
| Appendix A.5 | `generator-three-block-fenced`, `generator-appendix-a5-verbatim` |
| Appendix B | `matching-E410-leading-whitespace`, `matching-E410-no-line-matched`, `matching-E410-single-line-indent`, `result-applied-ranges-and-scope-line`, `operations-skipped-block-operation`, `result-check-mode-continues-past-failure` |
