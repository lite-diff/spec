# Ambiguities, contradictions and untestable points found while writing the lite-diff v1.1 conformance corpus

Found while deriving the conformance corpus in `tests/cases/` from the text of `../SPEC.md` alone, before any
implementation existed, and while writing the reference implementation (`../reference/`). Most points were
resolved in the published text; the tables in the last part name the §12 item that settles each one, and
[Open points](#open-points) lists what the text still leaves open. Each entry names the sections involved, the
readings, the choice the corpus makes (if a case depends on it) and the affected case ids. Cases that depend
on a choice the published text does not settle carry `"uncertain": true` in their `case.json`.

Entry kinds:

- **C** contradiction between two places of the text;
- **A** ambiguity: two readings are possible, the corpus picks one;
- **U** consequence of the normative rules that is probably unintended (the corpus follows the rule as written);
- **N** not derivable or not expressible: no case was written, or the field is not asserted.

## Top findings

1. **C1** `--ignore-blank-lines`: the first example of §5.1 contradicts the placement rule of §8.3.
2. **C2** Appendix A.5 (the complete example meant as prompt material) inserts the new `load()` *inside*
   `save()` when applied by the rules of §8.3.
3. **C4** E410 classification when the first anchor element matches nowhere: §8.2/§8.6 require one of four
   difference classes, Appendix B offers `no-line-matched` as a fifth value of the same field. This decides
   whether the most common LLM error (a one-line anchor with wrong indentation) gets the "leading whitespace"
   fix hint.
4. **U3/U4** The HEADER split rule of §4.1 makes the natural-order forms of E209 and E604 unreachable: a
   mismatching `---`/`+++` pair after `rename from/to` silently becomes a separate block. Mostly this ends in
   E608/E600, but `rename from a`/`rename to b`/`--- /dev/null`/`+++ c` is **accepted** as rename + create,
   although §6.4.2 lists exactly this shape as E604.
5. **A5** The EOL of every created file and of lines inserted into a file without terminated lines is left to
   "the environment's default policy", so the bytes of every create case are environment-dependent.
6. **U5** A scope header (`@@ <scope>`) whose body has only `+` lines is not covered by E412 and has no defined
   position; `@@ bof` (the case §7.1 itself mentions) is exactly this shape.
7. **C5** Hunk status of skipped hunks in a successful block (`skipped` vs "the block's status").
8. **C6** `--strict` lists W416, which can never occur under `--strict` (E307).
9. **A2/A3** For many parse-phase codes the "patch line number and the offending line" (§8.6) is not
   identifiable from the text (hunk-level and header-level codes).
10. **U1/U2/C3** The §4.1 bullet order turns several shapes that §3.2, §6.3.2 and Appendix A.3 attribute to
    E400, E200 and E300 into E404.

---

## Contradictions

### C1 — `--ignore-blank-lines` example 1 (§5.1) vs. the placement rule (§8.3)

- §5.1: "file `a`,``,`b`; hunk ` a` / ` b` / `+c` → `a`,`c`,``,`b` (§8.3)".
- §8.3: skipped lines are emitted "immediately after the contribution of the anchor element that matched the
  file line preceding them **and after any `+` lines that directly follow that anchor element**", with the
  example "` a` / `+c` / ` b` on file `a`,``,`b` gives `a`,`c`,``,`b`".
- For the body ` a` / ` b` / `+c`, `+c` follows ` b`, so §8.3 gives `a`,``,`b`,`c`. The §5.1 result is the
  result of the *other* body ` a` / `+c` / ` b`; the §5.1 example most likely has its body lines transposed.
- **Choice:** §8.3 (normative rule): `a`,``,`b`,`c`.
- Cases: `matching-ignore-blank-lines-plus-after-last` (uncertain), `matching-ignore-blank-lines-plus-between`.

### C2 — Appendix A.5 places the new function inside the next one

- A.5 block 2 hunk: `-def load():` / `...` / `-    return raw` / ` ` / ` def save(data):` / `+def load():` /
  `+    return read_all()`.
- By §8.3 (output order = body order) the `+` lines are emitted *after* the context line `def save(data):`, so
  the renamed file becomes `""`, `def save(data):`, `def load():`, `    return read_all()`, `    write(data)`
  — the new `load()` lands between `def save(data):` and its body. The "Expected result" paragraph of A.5 only
  says the old function is "replaced", which a reader understands as "the new one takes its place".
- A.5 is meant to be prompt material for generators ("SHOULD use §A.1 verbatim"), so the example teaches the
  wrong placement. Moving the two `+` lines before the ` ` line fixes it.
- Cases: `generator-appendix-a5-verbatim` (expects the literal §8.3 result), `generator-three-block-fenced`
  (the corrected document).

### C3 — Appendix A.3 "E300 right after +++" vs. §4.1

- §4.1 HEADER, body-looking bullet: once the header holds `+++`, a line starting with `-` "…includes … an
  option-looking `--…` line in that position" → **E404**; the E300 bullet comes later and is never reached.
- A.3: "E300 right after `+++` — A `--…` line where the hunk header should be".
- **Choice:** §4.1 (Appendix A says the main text prevails). E300 is reachable only before `+++`.
- Cases: `parse-option-after-plus-is-E404`, `parse-E300-option-in-header`.

### C4 — E410 classification when the first anchor element matches nowhere

- §8.2 step 5 "Best candidate": if the first anchor element matches nowhere, the best candidate is the
  Levenshtein-closest line "and the diagnostic says that no line matched exactly". "E410 difference
  classification … The first applicable class is reported", four classes. §8.6: the message "MUST state the
  difference classification … (leading whitespace only / tabs versus spaces / internal whitespace / other)"
  and for the first two classes the re-indentation advice.
- Appendix B: `bestCandidate.classification` enum = the four classes **plus** `no-line-matched`.
- Reading 1: classification is the difference class of the failing element vs. the closest line; "no line
  matched" is an additional statement. Reading 2: `no-line-matched` replaces the class.
- Consequence: with reading 2 the single-line anchor `-  return 1` against `    return 1` — the typical LLM
  indentation error — never gets "leading whitespace only" and its fix hint.
- **Choice:** reading 1. Suggestion: a separate boolean (`noLineMatchedExactly`) in Appendix B.
- Cases: `matching-E410-no-line-matched` (uncertain), `matching-E410-single-line-indent` (uncertain).

### C5 — status of skipped hunks in a successful block (§8.6)

- §8.6 "Hunk statuses": "In a block that succeeds, every hunk has the block's status" and, in the same
  paragraph, "`skipped` applies to the hunks of delete blocks (§6.4.5), of W601/W603 blocks, and to hunks
  skipped under `--skip-applied` (W414)".
- A delete block and a `--skip-applied` block succeed (status `applied`), so both sentences apply.
- **Choice:** the specific enumeration: hunk `skipped`, block `applied`.
- Cases: `matching-skip-applied-W414` (uncertain), `operations-delete-git-hunk-ignored` (uncertain).

### C6 — `--strict` escalates W416, but W416 cannot occur under `--strict`

- §5.2 and §4 list W416 among the escalated warnings; §5.2/§5.5 make `--lenient` with `--strict` (globally or
  per block) E307, and W416 exists only under `--lenient`. The escalation is dead text (or E307 is meant to be
  something else, e.g. `--strict` escalating W416 *instead of* rejecting the combination).
- No escalation case can be written. Cases: `levels-lenient-strict-E307`,
  `levels-block-lenient-global-strict-E307`.

### C7 — `cursor` field: "search start" (Appendix B) vs. "the cursor" (§8.6)

- Appendix B: `cursor` = "1-based search start (E410, E413, E414, E418)". §8.6: E413 "MUST report … the
  cursor", E418 "the scope text and the cursor", E410 "the search start". With a scope header the search start
  `S` and the cursor differ.
- The corpus asserts `cursor` only for hunks without scope text, where both are equal.
- Case: `matching-E413-above-scope` (field deliberately not asserted).

### C8 — editorial

- §8.6 "a JSON schema is recommended, see Appendix B when it exists" — Appendix B exists.
- Appendix A.3 row E403 "Use exactly `@@`, `@@ BOF`, or `@@ EOF`" omits the scope form (§7.1 form 4).
- §12 described some rules in a form that later entries superseded (distance cap `D`, non-overlapping
  counting, "any `<letter>/` stripped", "both counts present"), so a reader looking for the current rule could
  be misled. Resolved: §12 states every change in its final form (items 15 and 27).

---

## Ambiguities (the corpus picks one reading)

### A1 — which line W401 names (§7.2, §8.6)

- "the implementation MUST emit W401 naming the line"; §8.6: patch line number for W401. The pair has two lines.
- **Choice:** the `---` line (the rule is "decidable … at the `---` line").
- Case: `body-body-pair-W401` (uncertain). `result-strict-W401-parse-failure` does not assert the line.

### A2 — patch line of hunk-level parse errors (§8.6)

§8.6 requires "the patch line number and the offending line" for E411, E412, E415–E417, E5xx, but for codes
that concern a whole hunk the offending line is not defined.

| Code | Readings | Choice | Case |
|------|----------|--------|------|
| E412 (no anchor) | hunk header / first `+` line | hunk header | `body-E412-anchorless` (uncertain) |
| E416 (empty hunk) | hunk header (only line) | hunk header | `body-E416-empty-hunk` (uncertain) |
| E510 (`...` `...`) | first / second `...` | second `...` | `boundary-E510-double-marker` (uncertain) |
| E512 (neighbor not `-`) | the `...` / the offending neighbor | the `...` | `boundary-E512-context-next-to-marker` (uncertain) |
| E415 (two hunks in create) | second hunk header / first header | second header | `operations-E415-two-hunks-in-create` |
| E415 (non-`+` line) | that line | that line | `body-E415-context-in-create`, `operations-delete-with-plus-E415` |
| E417 | the misplaced BOF/EOF header | that header | `headers-E417-*` |
| E411 | the non-`+` line | that line | `body-E411-blank-between-plus-in-BOF` |

### A3 — patch line of header-level and option-conflict codes (not asserted)

For E202, E209, E210, E604, E605, E606, E608, E100–E102 on an edit pair (two lines carry the path), E304, E305,
E307 and the E404 of a hunk-less edit block, the text gives no rule for which line is "the offending line".
The corpus asserts only the code. E200 at the end of a header is asserted at the unpaired `---` line
(`parse-E200-unpaired`), E200 for a duplicate at the second `---` (`parse-E200-duplicate`); E100–E102/E104 in
create blocks at the `+++` line (only one non-null path). Suggestion: "the first line of the block header" for
block-level codes, "the later of two conflicting lines" for conflicts.

### A4 — coordinates of positions in W511 (and other multi-position diagnostics)

- W511 names "the chosen position and the first later position". When the warning is emitted the hunk has
  been applied; positions can be read in the file as matched (before this hunk's replacement) or in the result.
- **Choice:** the file as it was when the hunk was matched (consistent with §8.2: positions are in the file
  "as it currently is" during the search), 1-based.
- Cases: `boundary-early-return-W511`, `boundary-W511-window-to-eof` (uncertain). W410/W413 cases are built
  so that both readings coincide.
- Also open: W511 lists "the first later position" only, the schema says "all positions involved"; the corpus
  cases have exactly one later position.

### A5 — default EOL policy (§1.3, §6.4.5, §11)

- Inserted lines get "the terminator of the first terminated line … or the environment's default policy if the
  file had none"; for create blocks "EOL is chosen by editor/environment policy" (§11) while §6.4.5 only says
  "ends with a line terminator".
- Every create case and every insertion into an empty file is therefore environment-dependent.
- **Choice:** LF; stated as an environment assumption in README.md. Suggestion: LF unless the host configures
  otherwise, or make the policy a documented option.
- Cases: `eof-empty-file-eof` (uncertain); implicitly all create cases.

### A6 — scope text that starts with whitespace (§7.1 form 4) — no case

"`@@`, exactly one space, then scope text: at least one non-whitespace character, the first of which is not
`-`, `+` or `@`." For `@@  BOF` or `@@  def f(` it is unclear whether "the first" means the first character of
the scope text or its first non-whitespace character, and whether the leading space is part of the substring.

### A7 — `--strip N` on a path with exactly N components — no case

"A path with fewer than N components → E104"; `--strip 1` on `+++ new.txt` leaves an empty path, which the
text does not handle. The corpus uses `--strip 2` on a one-component path (`paths-strip-E104`).

### A8 — E413 positions

E413 "MUST report the earliest position before the search start where the pattern matches"; Appendix B lists
E413 among the codes with "all positions involved" in `candidates`. The corpus asserts `classification` and
`cursor`, not `candidates`.

### A9 — `appliedRange` in two situations (not asserted)

- `--apply-all-matches` applies a hunk several times; the hunk has one `appliedRange`.
- A hunk whose output sequence is empty (pure deletion) has `lineCount` 0 and a `firstLine` that may lie past
  the end of the new file; the schema requires `firstLine >= 1`.

### A10 — overall status of a document whose blocks are all skipped — no case

A document consisting only of W601/W603 blocks: `applied` (nothing failed) is the likely intent; §8.6 does not
say it. The W601/W603 cases include a regular block so that the status is determined.

### A11 — `--lite-diff 1.0` in a 1.1 implementation — no case

"supports a lower minor version of the same major → E308" covers newer documents; whether a declared older
minor selects v1.0 semantics or is read under v1.1 is not stated. (`--lite-diff 1.2` → E308 holds for a 1.1
implementation but would break the corpus for a 1.2 one, so only `2.0` is tested.)

### A12 — block-level boolean options cannot be turned off — no case

`option <name>[ <value>]` defines no value syntax for boolean options, so "a later one for the same name wins"
has no effect for them, and a block cannot disable a global `--first-match`, `--ignore-*` or `--skip-applied`.

### A13 — `<prefix>:` form — no case

"the general form `<prefix>:` (everything before `:`)" does not say when a colon is a prefix separator: a path
such as `notes:2026.txt`, or `a/x:y`, would be truncated. The interaction with the letter-prefix rule and with
E201 needs a precise grammar.

### A14 — classification with an empty indent (§8.2 step 5) — avoided

"tabs versus spaces when `L_a` and `L_f` are not both composed of the same single character kind": for
`L_a = ""`, `L_f = "\t"` the empty string is composed of no kind. The corpus avoids empty indents in
classification cases.

### A15 — other unasserted fields

- `severity` of an escalated warning ("keeps the warning code"; `error` or `warning`?) and `escalated`
  (optional in the schema).
- `blocks[].source/target` for the null side (`"/dev/null"` or `null`; the schema allows both).
- E418 "whether the text occurs before the cursor" and the E410 statement naming a `+` line outside the
  domain of `σ` (§8.2 step 5): mandatory, but Appendix B has no field for them, so they are only in the
  message (`levels-indent-shift-plus-outside-domain`, `headers-scope-E418`).
- W602 and W200 are MAY and never asserted.

---

## Probably unintended consequences of the normative rules (the corpus follows the rules)

### U1 — E400 is unreachable for a space-indented `@@` after `+++`

§4.1 HEADER tests the body-looking bullet (first character space after `+++`) before the indented-lexeme bullet,
and §3.2 applies only to lines "not otherwise recognized". ` @@` after `+++` is E404 "missing `@@`?", which is
misleading for a line that *is* an indented `@@`; only a tab-indented `@@`, or one before `+++`, gives E400.
Cases: `parse-space-indented-hunk-header`, `parse-tab-indented-hunk-header`.

### U2 — E200 "a second `+++`" is unreachable

A second `+++` (or a lone second `---`) after the header holds `+++` starts with `+`/`-` and is E404 by the
body-looking bullet. E200 for duplicates is reachable only before the first `+++` (`parse-E200-duplicate`).

### U3 — E209 "rename/copy vs `---`/`+++`" is unreachable in the natural line order

In `rename from a` / `rename to b` / `--- a` / `+++ c`, the pair differs from from/to, so §4.1 ends the block:
block 1 is a valid pure rename, block 2 fails with E608. E209 check 3 fires only for unusual orders
(`rename from` / pair / `rename to`), check 4 only with `diff --git`. The document still fails, but with a code
and message that do not point at the rename lines; A.3's E209 row describes a situation that produces E608.
Cases: `paths-rename-then-mismatched-pair`, `paths-E209-rename-to-vs-plus`, `paths-E209-rename-vs-diff-git`.

### U4 — E604 examples of §6.4.2 are split into separate blocks, one of them silently accepted

- `rename from a` / `rename to b` / `--- /dev/null` / `+++ b` → rename + create, E600 in block 2
  (`paths-rename-then-dev-null-pair`), not E604.
- With a different create target (`+++ c`) the same shape is **accepted** as "rename a→b, create c" although
  §6.4.2 names it as an E604 example (`paths-rename-then-create-other-accepted`, uncertain: the corpus
  follows §4.1 and expects `applied`). Likewise `rename from a` / `rename to b` / `copy from a` / `copy to c`
  becomes rename + copy. These are silent acceptances of documents the text calls invalid.
- E604 is reachable when the conflicting indicator precedes the completion of the pair
  (`paths-E604-rename-and-dev-null`, `paths-E604-create-and-delete`).
- Suggestion: split on a new operation only when the current block's header is complete *and* the new lines
  could not belong to it, or report E604 when a pair after a completed rename/copy pair carries `/dev/null`.

### U5 — scope header with only `+` lines

E412 is defined for "a hunk with header `@@` or a unified header" without anchor elements. A scope header with
only `+` lines therefore passes the parse phase and has an empty anchor pattern at the match phase, whose
behavior is undefined (match at `S`? everywhere?). `@@ bof` + `+…` — the very example of §7.1 — has this
shape. **Choice:** E418 (the scope text is not found, the match phase fails first), not E412.
Case: `headers-scope-lowercase-bof` (uncertain). Suggestion: include scope headers in E412.

### U6 — git's submodule pointer update is not recognized as a submodule

`git diff` writes a submodule update as `diff --git a/lib b/lib` / `index abc..def 160000` / `--- a/lib` /
`+++ b/lib` / `-Subproject commit …` / `+Subproject commit …` — without any mode line. W603 looks only at mode
lines, so the block is an edit of the path `lib`, normally a directory: E611? E103? undefined. No case;
suggestion: honor the mode on the `index` line.

### U7 — options before the fence cascade into an E401 on the closing fence

With an option line before the opening fence, the fence is E306 and no fence is open, so the closing fence is a
body line with a backtick → E401 (`parse-options-outside-fence`). Correct by the text, but two errors for one
mistake.

---

## Not testable through the runner contract

- Named roots (`--default-root`, `@root/`, E214, E215, W301): the root dictionary is host-defined (§5.3); the
  runner provides a single workdir.
- Write-phase interruption (§8.6, explicitly "cannot be exercised by a conformance test").
- E103 needs a symbolic link in the workspace; `operations-symlink-on-disk-E103` creates it at run time and is
  SKIPPED where the platform does not allow it (e.g. Windows without developer mode).

---

## Found during the reference implementation

The reference implementation (`../reference/`) was written from the text and run against this corpus, and the
corpus was aligned with it and with the published text. No failing case had to be left undecided: every
failure was an expectation that the published text settles differently, and the case now cites the §12 item in
`notes`: `parse-space-indented-hunk-header`, `paths-E209-rename-vs-diff-git` and
`paths-rename-then-mismatched-pair` (item 1), `headers-scope-lowercase-bof` and `generator-appendix-a5-verbatim`
(item 14), `body-sentinel-dropped-in-edit` (item 23), `parse-comment-between-blocks` (item 5) and
`result-strict-W410` (item 21; an inexact hit, the exact-hit shape is `result-strict-W410-exact-hit`). Cases
added while aligning the corpus cite the item they test.

### Resolved in the published text: entries C, A and U

| Entry | §12 item | Cases (`uncertain: false`) |
|-------|----------|------------------------------|
| C1 `--ignore-blank-lines` example | items 14, 19 (the §5.1 example now agrees with §8.3) | `matching-ignore-blank-lines-plus-after-last` |
| C2 Appendix A.5 | item 14 | `generator-appendix-a5-verbatim` (the published A.5 text) |
| C3 Appendix A.3 "E300 right after +++" | item 36 (A.3 lists E404 for this position) | `parse-option-after-plus-is-E404` |
| C4 classification vs `no-line-matched` | item 35 (`noLineMatched` flag) | `matching-E410-no-line-matched`, `matching-E410-single-line-indent` |
| C5 skipped hunks in a successful block | item 34 | `matching-skip-applied-W414`, `operations-delete-git-hunk-ignored` |
| C6 W416 in the `--strict` list | item 21 | — |
| C7 `cursor` vs search start | item 34 (`searchStart`) | `matching-E413-above-scope` asserts both |
| A2 E412 / E416 / E512 line | item 34 ("offending line") | `body-E412-anchorless`, `body-E416-empty-hunk`, `boundary-E512-context-next-to-marker` |
| A4 W511 coordinates | item 34 | `boundary-early-return-W511`, `boundary-W511-window-to-eof` |
| A5 default EOL | item 22 | `eof-empty-file-eof` |
| A6 scope text starting with whitespace | item 17 | — |
| A7 `--strip N` with N components; A12 block-level booleans | item 8 (E104 for N or fewer components; `off`) | — |
| A10 all-skipped document | item 32 (the document is applied) | — |
| A11 `--lite-diff 1.0` | item 10 (compatibility profile) | — |
| A13 `<prefix>:` | item 29 | — |
| U1, U2, U3, U4 HEADER split / E400 / E200 / E209 / E604 | item 1 | `paths-rename-then-create-other-accepted` |
| U5 scope header with `+` lines only | item 14 | `headers-scope-lowercase-bof` (E412) |
| U6 submodule pointer update | item 30 | — |

### Points raised by the reference implementation

Each entry gives the implementation's choice; the table after the list names the §12 item that settles it
and the case that tests it.

- **R1 (C) Profile 1.0 vs the migration notes.** §5: `--lite-diff 1.0` "makes a v1.1 implementation accept every
  document that v1.0 accepted"; §12 migration notes: a v1.0 `@@ <text>` comment header "now fails with E418",
  and v1.0 blocks without `@@` are now E404 — and the profile keeps "all v1.1 diagnostics". Implemented: the
  enumerated profile only (auto-rename, first-match, no strict, `#` dropped in bodies).
- **R2 (A) Profile 1.0 with `--apply-all-matches`.** The implied `--first-match` would be E305. Implemented: no
  conflict (the implied option is not an option line; apply-all-matches precedes first-match in §8.2 step 6).
- **R3 (U) `<prefix>:` relocates names containing a colon.** `+++ notes:2026.txt` creates `2026.txt` — the
  same silent relocation that §12 item 27 removes for one-letter directories. Implemented as written.
- **R4 (U) Trailing whitespace of an unquoted `---`/`+++` path is part of the path** (§6.3.4). On POSIX a create
  block makes `new.txt␠`; on Windows the OS drops the space and the same document targets `new.txt`.
- **R5 (A) Boolean global option with a value** (`--first-match off`): grammar allows it, semantics undefined.
  Implemented: the §5.5 `off` rule.
- **R6 (A) `ignore-space-at-eol` at block level** is in neither list of §5.5. Implemented: accepted (no-op).
- **R7 (A) `--ignore-blank-lines` and `+` lines after a removed blank context** (§8.3 "directly follow").
  Implemented: the removed element ends the run (` a`/``/`+c`/` b` on `a`,``,`b` → `a`,``,`c`,`b`).
- **R8 (N) `--ignore-blank-lines` with an anchor of blank context lines only**: empty pattern, no position, no
  code. Implemented: E410 with an explanation.
- **R9 (A) `--skip-applied` vs E413**: both apply when the anchor matches only before S and the applied pattern
  matches once after S. Implemented: W414.
- **R10 (A) E410 in a boundary block whose failing segment matches nowhere**: the "file line it was compared
  against" is undefined. Implemented: the longest-prefix (else Levenshtein-closest) line after the previous
  segment's end; `noLineMatched` false.
- **R11 (A) Terminator gained by a formerly unterminated last line** (§1.3 "gains a terminator"): not named.
  Implemented: the file's EOL convention (`eof-crlf-unterminated-eof` agrees).
- **R12 (U) Whitespace-only lines outside bodies are not blank** (§3.1): E306 in PREAMBLE, E404 in HEADER.
- **R13 (N) No code** for: an empty document (implemented: `applied`, nothing written), a patch that is not UTF-8
  or has a BOM (implemented: BOM dropped, invalid bytes replaced), an invalid `--strip` value (E301), duplicate
  `rename from` lines (E605), a write-phase failure (`x-writeError`).
- **R14 (A) "E404 once per block"** is stated for the after-`+++` bullet only. Implemented for every E404 of the
  block (both header bullets and the hunk-less edit block).

- **R15 (A) W417 "at the candidate position" for an insertion before its anchor** (§8.2 step 5 "Already
  present"). Read literally, the applied pattern starts at the candidate; for a re-applied `+new` / ` existing`
  hunk (the §2.3 shape) the `+` line lies one line *above* the candidate, so the re-application is never
  detected and the line is duplicated silently. **Choice:** the applied pattern is aligned on the first anchor
  element (tried `k` lines before the candidate when `k` `+` lines precede it). Case:
  `matching-W417-insert-before-anchor`. Related, no case: the comparison level for a candidate found
  at level (b)/(c) (the implementation uses that level), W417 under `--apply-all-matches` (tested per
  occurrence), and the order of W417 and W413 under `--strict` (W417 first).
- **R16 (A) Check mode and the hunks after a failing hunk of the same block** (§8.6 "Check mode"): the text
  continues "with the remaining blocks" but promises that "every block and hunk receives a status (checked or
  failed)". **Choice:** the later hunks are matched as if the failed hunk had been skipped (cursor unchanged)
  and are `checked`. Case: `result-check-mode-hunks-after-failure`. Also unstated: the status of
  the blocks *before* a failure in check mode (`checked`, not `matched`; asserted in
  `result-check-mode-continues-past-failure`, which follows from "every block ... receives a status (checked
  or failed)") and whether `checkedWithSkips` is present when nothing failed (the implementation writes
  `false`; not asserted).
- **R17 (U) Colons in paths on Windows** (§6.3.5). `notes:2026.txt` is a plain path; on NTFS writing it
  creates the alternate data stream `2026.txt` of a file `notes` — a silent relocation again, now
  platform-dependent; and `c:x.txt` (a letter, a colon, no slash) is relative by §6.3.5 but drive-relative on
  Windows, i.e. outside the workspace. A corpus file cannot even be named `notes:2026.txt` on Windows, so
  `paths-colon-is-ordinary` runs under `--check`. Suggestion: reject `:` in path components with a code.
- **R18 (C) Which side a sentinel after a context line belongs to.** §3.1 "Body lines": "a context line **not**
  followed by `+` lines = old-side sentinel" and "a context line that is the hunk's last body line = new-side";
  §1.3: old side = "a context line **that is followed by** `+` lines". For git output (context with a sentinel
  is always the last body line) all readings give the same file; they differ in whether W419 is due for a
  context-last sentinel on a terminated file. The implementation treats a context-last sentinel as both sides.
  Cases (reading-independent): `eof-old-side-sentinel-context-then-plus`,
  `eof-context-last-sentinel-keeps-unterminated`.
- **R19 (A) Misplaced sentinels in a hunk that reaches the end of file** (a sentinel after an earlier `+` line,
  before the first body line, after `...`): §1.3 names W419 for an old-side mismatch and for a hunk that does
  not reach the end of file; Appendix A.1 rule 6 says "anywhere else it is ignored with a warning". The
  implementation emits W419 for them (and in create hunks: `operations-create-misplaced-sentinel-W419`).
- **R20 (N) Location of E310, W302, W417, W419**: not in the §8.6 location lists. The corpus asserts E310 with
  `patchLine`, W302 without a location, W417/W419 with `block` + `hunk`.
- **R21 (A) W601 for a binary delete** (§6.4.4 step 1): the block "is not skipped", so the corpus forbids W601
  (`operations-binary-delete-applied`).
- **R22 (A) Trailing whitespace in other unquoted paths** (`diff --git` remainder, `rename`/`copy` paths): §6.3.4
  strips it from `---`/`+++` only; stripping it elsewhere too avoids E202/E209 for the same file (reference
  implementation; no case).
- **R23 (A) A trailing comment run followed by a `---`/`+++` pair whose next line is a body line**: a block start
  (the body has ended, the body-pair rule does not apply) or two body lines? The implementation starts a block
  (E404 follows). No case.
- **R24 (A) `--lite-diff` with a malformed value** (`--lite-diff x`): E301 ("invalid value") or E308
  ("unsupported version")? The implementation reports E301. No case.
- **R25 (A) E606 for duplicate `copy` lines**: the §10 E605 row covers duplicates, the E606 row does not. The
  implementation reports E606. No case.
- **R26 (informative) Final newline, v1.0 sessions vs v1.1.** Replaying 50 recorded v1.0 sessions, 6 files
  still differ from v1.0 only by the final newline, all as §1.3 and §6.4.5 prescribe (§12 item 23):
  3 creates without a sentinel (§6.4.5: terminated; v1.0: unterminated) and 3 edits whose hunk ends `-last` /
  `\ No newline at end of file` / `+new…` (old-side sentinel only: the new side decides, terminated, as
  `git apply`; v1.0 kept the file unterminated). If v1.0 compatibility is wanted here, profile 1.0 would need
  its own rule; the text does not give one.

### Resolved in the published text: entries R

| Entry | §12 item (published rule) | Cases |
|-------|---------------------------|-------|
| R1 profile 1.0 vs migration notes | item 10 (v1.0 behavior only where v1.0 applied to a definite place) | — |
| R2 profile 1.0 with `--apply-all-matches` | item 10 ("implied options never raise a conflict error") | `parse-profile-10-implied-first-match-no-conflict` |
| R3 / A13 `<prefix>:` | item 29 (form removed, E201 reserved) | `paths-colon-is-ordinary` |
| R4 trailing whitespace of unquoted paths | item 28 (stripped) | `paths-trailing-space-stripped` |
| R5 boolean global option with a value | item 8 (`off`) | `parse-first-match-off` |
| R6 `ignore-space-at-eol` at block level | item 12 (accepted, a no-op) | `parse-block-option-ignore-space-at-eol` |
| R7 / R8 `--ignore-blank-lines` run end, empty anchor | item 19 | `matching-ignore-blank-lines-removed-blank-ends-run`, `matching-ignore-blank-lines-empty-anchor-E410` |
| R9 `--skip-applied` vs E413 | item 20 (the already-applied test precedes the E413 search, also without `--skip-applied`) | `matching-already-applied-before-E413` |
| R10 compared line of a failing boundary segment | item 18 (the line after the previous segment's match) | `boundary-E410-failing-segment-compared-line` |
| R11 terminator gained by an unterminated last line | items 22, 23 (the file's EOL convention) | `eof-context-reaches-eof-without-sentinel-terminates` |
| R13 missing codes | item 9: E310 (encoding), W302 (empty document); item 25: E605 (duplicate `rename from`); item 34: `writeError`; item 8: E301 (invalid value) | `parse-bom-E310`, `parse-invalid-utf8-E310`, `parse-empty-document-W302`, `parse-options-only-W302`, `paths-E605-duplicate-rename-from`, `parse-strip-invalid-E301` |
| R15 W417 alignment, level, order before W413, per occurrence | item 20 (§8.2) | `matching-W417-insert-before-anchor` |
| R16 check mode: hunks after a failing hunk, `checked` not `matched`, `checkedWithSkips` always present | item 33 (§8.6, B) | `result-check-mode-hunks-after-failure` |
| R17 colons in paths on Windows | item 29 (§6.3.3, §6.3.5, §10): any `:` is E100 on Windows, ordinary elsewhere | `paths-colon-E100-windows` (Windows only), `paths-colon-is-ordinary` (POSIX only) |
| R18 sentinel side after a context line | item 24 (§1.3, §3.1): final context line = both sides, other context = old side | `eof-old-side-sentinel-context-then-plus`, `eof-context-last-sentinel-keeps-unterminated` (reading-independent) |
| R19 misplaced sentinels | item 24: W419 everywhere, also in create hunks and hunks reaching EOF | `operations-create-misplaced-sentinel-W419` |
| R20 locations of E310, W302, W417, W419 | item 34 (§8.6, §10) | the cases of those codes |
| R21 W601 for a binary delete | item 30 (§6.2, §6.4.4): none | `operations-binary-delete-applied` |
| R22 trailing whitespace in `diff --git` and `rename`/`copy` paths | item 28 (§6.3.4): stripped | no case |
| R23 comment run before a `---`/`+++` pair | item 5 (§4.1, §7.2): block start, no body-pair rule | no case |
| R24 malformed `--lite-diff` value | item 8 (§5): E301 | no case |
| R25 duplicate `copy` lines | item 25 (§6.4.2, §10): E606, first repeating line | no case |

R26 is informative.

---

## Open points

The published text does not decide these; the cases keep `"uncertain": true`:

- **A1** which line W401 names (`body-body-pair-W401`; the reference implementation names the `---` line);
- the **E510** row of **A2**, first or second `...` (`boundary-E510-double-marker`; the reference
  implementation names the second).

Also left to implementations, with no case asserting them: A8 (E413 positions), A9 (`appliedRange` under
`--apply-all-matches` and for pure deletions), A14 (classification with an empty indent), A15 (severity of an
escalated warning; `source`/`target` of the null side), R12 (whitespace-only lines outside bodies), R14 (E404
once per block), and the first two editorial points of C8. The reference implementation's choices are listed
in `../reference/README.md`.
