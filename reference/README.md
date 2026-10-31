# lite-diff v1.1 — reference implementation

Python 3.10+, standard library only. The normative text is `../SPEC.md` (v1.1); every rule in the code
carries the section it implements (`§x.y`) in a comment, and rules listed in the change list also cite the
§12 item (`§12 item NN`).

## Running

```
cd reference
python -m litediff [--check] [--strict] [--eol lf|crlf] <patch-path> <workdir>
```

- Applies the patch (UTF-8) to the files under `<workdir>` (bytes) and prints the result JSON of
  Appendix B to stdout (UTF-8).
- Exit status: `0` for `applied` / `checked`, `1` for `failed`, `2` for usage errors (wrong arguments,
  unreadable patch, workdir not a directory).
- Options come from the patch document (§5, §5.5). `--check`, `--strict` and `--eol` before the positional
  arguments are host switches (§5.2 "tool-level switch"); they are OR-ed with the document.
- All-or-nothing (§8.6): everything is computed in memory; files are written only when every block
  succeeded and `--check` is off, each via a temporary file in the target directory plus `os.replace`.
  Directories emptied by a delete or a rename are removed afterward (§6.4.3).
- Check mode (§8.6, §12 item 33) does not stop at the first failing block or hunk: every block and hunk
  gets a status and the result carries `checkedWithSkips`.

Conformance corpus (the runner invokes `<command> <patch-path> <workdir>`, so run it from `reference/`):

```
cd reference
python ../tests/run.py --impl "python -m litediff"            # whole corpus
python ../tests/run.py --impl "python -m litediff" --only "parse-*" -v
```

Set `PYTHONDONTWRITEBYTECODE=1` to keep `__pycache__` out of the tree. Result on Windows: 269 passed,
2 skipped (`operations-symlink-on-disk-E103` needs symlink privileges, E103 was checked by hand with a
junction; `paths-colon-is-ordinary` is POSIX-only, its Windows counterpart `paths-colon-E100-windows` runs).

Library use: `litediff.apply(patch_bytes, workdir, check=False, strict=False) -> dict`.

## Modules (pipeline order)

| Module | Sections | Role |
|--------|----------|------|
| `lexemes.py` | §3.1, §5, §7.1 | stateless line predicates: path header, metadata keyword, option grammar, fence, sentinel, marker, the hunk header lexeme (forms 1–4, E403), indented lexemes (E205/E206/E207/E302/E400) |
| `options.py` | §5, §5.5 | option tables, version marker, `GlobalOptions` (document-wide), `MatchOptions` (per block), the `off` value |
| `model.py` | §3.1, §6, §7 | plain data classes: `Document`, `Block`, `Hunk` (with the recorded sentinel sides), `BodyElement`, `HeaderLine` |
| `parser.py` | §1.3, §4.1, §3.1, §7.2 | E310 (encoding), the four-state machine (PREAMBLE/HEADER/BODY/TRAILER), trailing comment runs, body-pair rule (W401), processing order (sentinels and their side, trailing blanks), global options, profile 1.0 |
| `paths.py` | §6.3.1, §6.3.3–§6.3.6, §5.3 | unquoting/escapes (E203), trailing-whitespace removal, letter prefixes, `--strip` (E104), NFC, security (E100–E102), `diff --git` split (E204) |
| `validate.py` | §6.4.4 steps 1–4, §6.3.2, §6.4, §5.5, §7, §6.4.5 | per-block parse-phase checks: W601/W603 skip (binary delete not skipped; operation of skipped blocks), source/target, E202/E209/E608, E604–E606, block options (E301/E305/E307/E309), hunk structure (E304, E404, E411, E412, E415–E417, E510–E512) |
| `textfile.py` | §1.3 | target file line model: bytes, per-line terminators, BOM, EOL convention, the final terminator (git semantics) |
| `compare.py` | §1.3, §3.4, §5.1, §8.2 step 5 | comparison keys (trailing whitespace, `--ignore-*`), indent/rest split, E410 classification, Levenshtein |
| `matcher.py` | §7.3, §8.2 steps 4–6 | pattern and segments, levels (a)/(b)/(c) as `Comparator`s, segment matching with `--ignore-blank-lines` skipping, candidates (overlapping), σ and prefix substitution, applied pattern, W511 |
| `applier.py` | §8.3 | the output sequence and the replacement of the anchor block |
| `diagnose.py` | §8.2 step 5, §8.6 | E410 content: best candidate, failing element, visible whitespace, classification, `--ignore-all-space` test, already-applied, segment |
| `engine.py` | §8.1, §8.2, §8.4, §8.6 | phases, W302, file-system checks (E103, E6xx), the hunk loop (cursor, delta, scope, ambiguity, E413/W413, W410/E414, W417/W414, W419 and the final-terminator decision), check-mode continuation, statuses |
| `workspace.py` | §8.5, §8.6, §6.4.3 | in-memory file-system overlay; write phase (temp file + rename), removal of emptied directories, `writeError` text |
| `diagnostics.py`, `result.py` | §8.6, Appendix B | diagnostics, `--strict` escalation (W410 exact-hit exception), visible-whitespace rendering, the result JSON (`checkedWithSkips`, `writeError`) |

Result extras (Appendix B allows `x-` fields): `x-patchLine` on blocks and hunks, `x-appliedRanges` for
`--apply-all-matches`, `bestCandidate.x-anchorPatchLine` / `x-fileLine`, `x-indentShiftRefusedLine`,
`x-scopeText` / `x-occursBeforeCursor` (E418), `x-line` (W414/W415/W416/W417), `x-segment` (W511),
`x-exactHit` (W410), `x-patchLines` (W419), `x-writtenBeforeError` (write phase, next to `writeError`).

## Implementation decisions

Each is marked in the code. The ones marked ★ are possible silent misapplications or contradictions.

### Decisions 1–12: settled by the published text

Kept as the record of why each rule reads as it does; each entry cites the §12 item that states the rule. For
decision 8 the published rule is stricter than the implementation's first choice (any `:` in a path is E100
on Windows, `paths.py`); the others are stated as implemented.

1. ★ **Which side a sentinel after a context line belongs to** (§12 item 24). §3.1 "Body lines": "a `-` line
   or a context line **not** followed by `+` lines = old-side sentinel; a `+` line, or a context line that is
   the hunk's last body line = new-side sentinel". §1.3 "Final terminator": old side = "after a `-` line or a context line
   **that is followed by** `+` lines". The two definitions contradict each other for a context line followed
   by `+` lines, and §3.1 makes a context line that is the last body line both. Implemented: a context line
   that is the last body line → new side **and** old side (it is the last line of both sides, as in
   `git diff`; the old-side assertion gives W419 when the file's last line is terminated); any other context
   line → old side. Every reading agrees on the cases git produces.
2. **Misplaced sentinels** (§12 item 24). A sentinel only decides or asserts something when it follows the
   *last* line of its side (§1.3: "after the last line of the new side"). A sentinel after an earlier `+`/`-` line, before
   the first body line, or after `...` is W419 and ignored, also in a hunk that reaches the end of file and in
   a create hunk (Appendix A.1 rule 6: "anywhere else it is ignored with a warning"). The old-side check is
   one-directional: an unterminated last line without an old-side sentinel is not W419.
3. **Location of E310, W302, W417 and W419** (§12 item 34). Implemented: E310
   with the patch line (line 1 for a BOM, the line of the first invalid byte otherwise); W302 without a
   location; W417 and W419 with block and hunk ordinals (match phase). Parsing continues after E310 so that
   the document's other parse errors are reported too; W302 is also emitted when a document without blocks
   has parse errors.
4. ★ **W417 "at the candidate position"** (§12 item 20) read literally never detects a re-applied insertion *before* its
   anchor (§2.3 shape `+new` / ` existing`): the applied pattern starts one line above the candidate.
   Implemented: the applied pattern is aligned on the first anchor element (tried `k` lines before the
   candidate when `k` `+` lines precede it), compared at the level the candidate was found at. W417 is
   tested before W413 (so `--strict` reports the re-application, not the order), and under
   `--apply-all-matches` for every occurrence (`--skip-applied` then skips that occurrence).
5. **Check mode inside a failing block** (§12 item 33): §8.6 continues "with the remaining blocks ... so that every block and
   hunk receives a status (checked or failed)". Implemented: the hunks after a failing hunk of the same block
   are matched too, as if the failed hunk had been skipped (cursor unchanged); their status is `checked`, as
   is the status of every successful block and hunk; the failing block's in-memory result is discarded.
   `checkedWithSkips` is present in every check-mode result and true iff a block failed in the match phase.
6. **Binary delete and W601** (§12 item 30): the binary delete is "not skipped", so no W601 is emitted ("Binary file
   skipped" would be false). W603 (mode `120000`/`160000`) still wins over a binary delete.
7. **A trailing comment run followed by a `---`/`+++` pair** (§12 items 5 and 10): the pair is a block start
   in the PREAMBLE/HEADER sense (blank and comment lines between `---` and `+++` skipped), and the body-pair rule of §7.2 does not
   apply after a comment run (the body has ended). Under profile 1.0 the trailing-run rule is applied first,
   so a run before the next block ends the block exactly as in 1.1; other `#` lines are dropped.
8. ★ **Colons in paths on Windows** (§12 item 29). With `<prefix>:` removed, `notes:2026.txt` is a plain path;
   on NTFS writing it would create an alternate data stream `2026.txt` of a file `notes` — a silent relocation
   of the same class the removal was meant to prevent, and platform-dependent. Likewise a single letter
   followed by `:` and anything other than `/` or `\` (`c:x.txt`) is a *drive-relative* path on Windows that
   escapes the workspace. Published rule, implemented in `paths.py`: on Windows any `:` in a path is E100;
   elsewhere a colon is an ordinary character (the POSIX corpus case runs under `--check`).
9. **Trailing whitespace in other unquoted paths** (§12 item 28): removed from `---`/`+++` paths and also from
   the unquoted `diff --git` remainder and from `rename`/`copy` paths, so that `+++ x␠` and
   `diff --git a/x b/x␠` or `rename to x␠` do not disagree (E202/E209) about the same file.
10. **Option values** (§12 item 8): `--lite-diff` with a value that is not `<major>.<minor>` → E301 (invalid
    value); a well-formed unsupported version stays E308. `--default-root` without a value → E301.
11. **E605 for duplicates** (§12 item 25) names the first duplicate line; E606 likewise covers duplicate
    `copy from`/`copy to` lines.
12. **Emptied directories** (§12 item 31) are removed after the write phase, walking up from each deleted file
    while the directory is empty (never the workspace root); they are not listed in `written` (MAY).

### Implementation choices the text leaves to hosts, and replay notes

13. **Replay finding (final newline).** On the 50 recorded v1.0 sessions, 6 files still differ
    from the v1.0 preview only by the final newline, all as §1.3/§6.4.5 prescribe: 3 created files (no
    sentinel → terminated, v1.0 wrote them unterminated) and 3 edits whose hunk ends `-last` / `\ No newline
    at end of file` / `+new…` without a sentinel after the last `+` line (old-side only → the new side
    decides → terminated, as `git apply` does; v1.0 kept the file unterminated).
14. **Whitespace-only lines outside bodies** are not "blank" (§3.1: "a line without any characters"): in
    PREAMBLE they are E306, in HEADER E404. Implemented as written; a tolerant host may want them ignored.
15. **E404 once per block** is stated for the after-`+++` bullet only. Implemented for all E404 sources of a
    block (both header bullets and the hunk-less edit block), as `parse-missing-hunk-header` needs.
16. **Offending line of two-line conflicts** (E202, E209, E604): the later of the two conflicting lines (E604:
    the first line introducing a second operation). E304: the block start line. Host-level option conflicts
    carry no patch line.
17. **Submodule pointer update** (§6.4.1): implemented as "an `index` line and exactly one hunk whose body lines
    all are `-Subproject commit …`/`+Subproject commit …`".
18. **After a W414 skip**: the cursor moves past the match (§5.2); the line delta is left unchanged (it counts
    applied hunks) and the skipped match is the "previous hunk's applied range" for a following E413.
19. **Classification with an empty indent** (AMBIGUITIES A14): the union of the characters of both indents is
    taken; one kind (or none) → leading whitespace, two → tabs versus spaces. Past end of file → `other`.
20. **"Fails everywhere only because of a `+` line outside the domain"** (level (b)): implemented strictly —
    every position whose rests matched was refused for that reason.
21. **W413 / E413 `candidates`**: W413 lists every earlier match plus the chosen one; E413 every match before S
    (the earliest is the classified one).
22. **`appliedRange` under `--apply-all-matches`** (AMBIGUITIES A9): the first application; all of them in
    `x-appliedRanges`. A pure deletion reports `firstLine` = the position where the lines were removed.
23. **Statuses of skipped (W601/W603) blocks in a failed document**: parse failure → `not-attempted` (§8.6
    "all other blocks"); match failure → blocks before the failing one keep `skipped`.
24. **NFC and the file system**: §6.3.6 normalizes patch paths to NFC; a file stored in NFD on a byte-oriented
    file system (Linux) cannot be addressed. Implemented as written.
25. **E103** also covers a symbolic link (or Windows junction) on any directory component of the path, so a
    patch cannot write through a link.
26. **Named roots** (§5.3, MAY) are not implemented: the implementation is single-root, `--default-root` gives
    W301, and `@types/…` is an ordinary path (§5.3 note, §12 item 29).

### Earlier implementation decisions that the published text settles

| Implementation choice | §12 item | Published rule |
|-----------------------|----------|----------------|
| ★ profile 1.0 does not accept every v1.0 document | 10 | the profile is defined by "v1.0 behavior where v1.0 applied to a definite place"; E404/E412/scope headers stay |
| profile 1.0 with `--apply-all-matches` | 10 | "implied options never raise a conflict error" |
| `--first-match off` | 8 | `off` for global booleans |
| `ignore-space-at-eol` at block level | 12 | in the allowed list |
| `--strip x` | 8 | E301 |
| ★ `<prefix>:` relocates `notes:2026.txt`; `--strip` with `<prefix>:` | 29 | form removed, E201 reserved (see 8 above for Windows) |
| ★ trailing whitespace in unquoted `---`/`+++` paths | 28 | stripped (see 9 above) |
| BOM / invalid UTF-8 patch | 9 | E310 (not dropped or replaced silently) |
| empty document | 9 | W302, `applied` |
| duplicate `rename from` | 25 | E605 |
| write-phase failure | 34 | `writeError` |
| named roots | 29 | only in a host-declared multi-root environment |
| `--ignore-blank-lines`: `+` lines after a removed blank; empty anchor | 19 | as implemented |
| `--skip-applied` vs E413 | 20 | the already-applied test precedes E413; without `--skip-applied` a re-applied hunk is E410 "already applied", not E413 |
| E410 compared line for a failing boundary segment | 18 | the line after the previous segment's match, not the longest-prefix position |
| terminator gained by a formerly unterminated last line | 22, 23 | the file's EOL convention |
| final terminator "iff the original unterminated last line is still last" | 23 | git semantics: the new side of the last hunk reaching the end of file decides |

## Porting to TypeScript

Mirror one-to-one: `lexemes`, `options`, `model`, `parser`, `paths`, `validate`, `textfile`, `compare`,
`matcher`, `applier`, `diagnose`, `engine`, `diagnostics`, `result`. They have no I/O. Replace `workspace.py`
by an adapter with the same queries (`isFile`, `exists`, `isSymlink`, `read`, and the overlay writes)
over `vscode.workspace.fs`, committing through a single `WorkspaceEdit` (including the removal of emptied
folders); replace `__main__.py` by the extension command. Keep target-file content as `Uint8Array`
(comparisons are on bytes, §1.3) and patch lines as strings encoded with `TextEncoder` where they are
compared; `String.prototype.normalize("NFC")` for paths. A preview UI should run check mode and show the
per-hunk statuses (`checked`/`failed`/`skipped`) together with `checkedWithSkips`.
