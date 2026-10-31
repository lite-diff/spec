# Lite-diff Specification (v1.1, October 2026)

> **lite-diff** is an independent text format for describing file changes, inspired by the classic unified diff format. This specification defines the syntax and semantics of the format.

> **Status.** Version 1.1 supersedes v1.0 (December 2025). Changes relative to v1.0 are summarized in [§12](#12-changes-from-v10); patch generators should start with [Appendix A](#appendix-a-writing-lite-diff-for-patch-generators). Every change is motivated by the same goal: patches written by LLM agents must either apply exactly as intended or fail loudly; silent misapplication is never acceptable. The specification is accompanied by a conformance corpus (`tests/`) and a reference implementation (`reference/`) in the same repository.

## License

This specification is published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). You are free to share and adapt it with attribution.

---

## Table of Contents

- [1. Introduction](#1-introduction)
  - [1.1. Compatibility with Unified Diff](#11-compatibility-with-unified-diff)
  - [1.2. Out of Scope](#12-out-of-scope)
  - [1.3. Encoding and Line Endings](#13-encoding-and-line-endings)
- [2. Quick Start](#2-quick-start)
  - [2.1. Minimal File Edit Example](#21-minimal-file-edit-example)
  - [2.2. Insertion at Beginning/End](#22-insertion-at-beginningend)
  - [2.3. Insertion After Context Line](#23-insertion-after-context-line)
  - [2.4. Create, Delete, Rename](#24-create-delete-rename)
  - [2.5. Boundary Deletion](#25-boundary-deletion)
- [3. Terms and Conventions](#3-terms-and-conventions)
  - [3.1. Core Definitions](#31-core-definitions)
  - [3.2. First Position Rule](#32-first-position-rule)
  - [3.3. Normative Keywords](#33-normative-keywords)
  - [3.4. Whitespace Definition](#34-whitespace-definition)
- [4. Document Structure](#4-document-structure)
  - [4.1. Parser States (Normative)](#41-parser-states-normative)
- [5. Global Options (Extensions)](#5-global-options-extensions)
  - [5.1. Whitespace Matching Options](#51-whitespace-matching-options)
  - [5.2. Application Modes](#52-application-modes)
  - [5.3. Path Options and Named Roots](#53-path-options-and-named-roots)
  - [5.4. Restrictions and Errors](#54-restrictions-and-errors)
  - [5.5. Block-level Options](#55-block-level-options)
- [6. Block Header](#6-block-header)
  - [6.1. Header Boundaries](#61-header-boundaries)
  - [6.2. Header Content](#62-header-content)
  - [6.3. Path Extraction](#63-path-extraction)
  - [6.4. Operation Definition](#64-operation-definition)
- [7. Hunks (Core + Extensions)](#7-hunks-core--extensions)
  - [7.1. Hunk Headers](#71-hunk-headers)
  - [7.2. Hunk Body](#72-hunk-body)
  - [7.3. Boundary Blocks (Extension)](#73-boundary-blocks-extension)
- [8. Matching and Application Algorithm](#8-matching-and-application-algorithm)
  - [8.1. Algorithm Overview](#81-algorithm-overview)
  - [8.2. Position Search](#82-position-search)
  - [8.3. Change Application in Anchor Block](#83-change-application-in-anchor-block)
  - [8.4. --apply-all-matches](#84---apply-all-matches)
  - [8.5. Sequential Application Rule](#85-sequential-application-rule)
  - [8.6. Atomicity, Check Mode, and Result Reporting](#86-atomicity-check-mode-and-result-reporting)
- [9. Conformance](#9-conformance)
  - [9.1. Conformance Levels](#91-conformance-levels)
  - [9.2. Interoperability Notes](#92-interoperability-notes)
- [10. Errors and Warnings (Reference)](#10-errors-and-warnings-reference)
- [11. Compatibility and Edge Cases](#11-compatibility-and-edge-cases)
- [12. Changes from v1.0](#12-changes-from-v10)
- [Appendix A. Writing lite-diff (for patch generators)](#appendix-a-writing-lite-diff-for-patch-generators)
- [Appendix B. Result Schema](#appendix-b-result-schema)
- [Acknowledgments](#acknowledgments)

---

## 1. Introduction

**lite-diff** is a simplified text format for describing file changes. The goal is to provide a predictable, easy-to-read, and easy-to-implement specification covering common editing scenarios (point edits, insertions at the beginning/end, file creation/deletion/renaming/copying) with minimal rules.

### 1.1. Compatibility with Unified Diff

- Standard header forms are accepted: `diff --git`, `---` / `+++`, as well as extended Git headers (some are ignored).
- Hunk headers in the format `@@ -a[,m] +b[,n] @@ [section]` are supported. Position is always found by content; numeric ranges are used **only** to resolve an ambiguous match (see §8.2 step 6), and "section" is ignored.
- Hunk bodies follow unified diff semantics: context lines are kept, `-` lines are removed, `+` lines are inserted in body order. In particular, a hunk MAY start with `+` lines (insertion before the first context line), and a completely blank line inside a hunk body is accepted as the context of an empty line, exactly as `git apply` does.
- Diff blocks are delimited by the parser state machine of §4.1. A `--- ` line immediately followed by a `+++ ` line starts a new block except where §4.1 says otherwise: the pair of the block's own header, the pair that completes a `rename`/`copy` header, and the body-pair rule of §7.2; a single `--- …` or `+++ …` line inside a hunk body is an ordinary body line.
- Rename is **never** inferred from differing paths; it requires an explicit `rename from` / `rename to` header (see §6.4).
- Only the output of `git diff` and of GNU `diff -u` / `diff -ru` (with at least one line of context) is in scope. GNU diff output is supported when its `---`/`+++` paths are equal after prefix removal (§6.3.5): either the compared trees use git's prefix letters (`a/`, `b/`), or the global option `--strip N` (§5.3) removes the differing leading components. Without `--strip`, output comparing `old/` against `new/` yields differing paths and is rejected with **E608**.
- Paths containing spaces are accepted unquoted in `---`/`+++` lines and in `diff --git` lines, as `git diff` writes them (§6.3.4). The envelopes of `git format-patch`, `git log -p`, and `git show` (mail headers, commit messages, diffstat, `-- ` signature) are **not** supported; see §1.2 and §4.1. Zero-context diffs (`-U0`) are not supported either: a hunk without any anchor element has no position in a content-matched format (§8.3, E412).
- Files whose git mode is `120000` (symbolic link) or `160000` (submodule) are skipped with a warning (**W603**), like binary files.
- The **first position rule** is observed for all structural elements (see §3).
- Binary indicators (`Binary files ... differ`, `GIT binary patch`) cause the block to be skipped with a warning, except that a binary **delete** (`deleted file mode` with a binary indicator) needs no file content and is applied.
- The sentinel `\ No newline at end of file` is not a body line and never takes part in matching; it is honored exactly as `git apply` honors it: when a hunk reaches the end of the file, a sentinel after the new side's last line means the result has no final line terminator (§1.3), and in a create block it does the same (§6.4.5).
- Additional simplifications and capabilities (e.g., `@@`, `@@ BOF`, `@@ EOF`, `boundary blocks`, `global options`, and `comments`) are defined as **extensions**.

### 1.2. Out of Scope

1. Conditional application constructs (`if-exists`, `if-not-exists`).
2. Variables and templates (`$VAR`, `${VAR}`).
3. Regular expressions and fuzzy search — only exact matching, except that trailing whitespace is never significant (§1.3), considering `--ignore-*`. There is no progressive loosening of the comparison after a failed match other than the explicit opt-in options `--indent-shift` and `--lenient` (§5.2, §8.2 step 5).
4. Any work with binary data, and with symbolic links or submodules **declared by mode** in the header — skipped with a warning (W601, W603). A symbolic link found on disk at a regular-mode path is an error (E103).
5. Special limits on file/line sizes — not imposed by the specification.
6. Mail and log envelopes around a diff (`git format-patch`, `git log -p`, `git show`, `diff -r` output such as `Only in …`). Hosts that receive such input SHOULD strip the envelope before handing the diff to a lite-diff implementation.
7. Combined diffs (`@@@ … @@@`, `diff --cc`, `diff --combined`).
8. Zero-context diffs (`git diff -U0`, `diff -U0`): insertion-only hunks cannot be positioned by content.

### 1.3. Encoding and Line Endings

**Patch file encoding:**
- lite-diff files **MUST** be encoded in **UTF-8** without BOM.

**Line splitting:**
- Lines are split by `LF` (U+000A) or `CRLF` (U+000D U+000A).
- The internal line model uses `LF`; `CR` before `LF` is stripped during parsing.
- When applying patches, line endings in inserted content follow the target file's existing convention, or the default EOL (`LF`, or `--eol crlf`) when the file has none (see "Target file line model" below).

**Target file line model:**
- The target file content is treated as a sequence of **bytes**; it is not required to be valid UTF-8. It is split into lines on `LF` or `CRLF`. Each line is a pair (content bytes, terminator), where the terminator is `LF`, `CRLF`, or **none**. Only the last line can have terminator `none`; such a line is called an "unterminated last line". If the content ends with a terminator, there is **no** additional empty last line.
- An empty file has zero lines.
- **Matching** compares the content bytes of a file line with the UTF-8 bytes of the patch line content (after the prefix), **after trailing whitespace (§3.4) has been removed from both sides**; terminators never take part in matching. The `--ignore-*` options (§5.1) are applied in addition, to both sides, before comparison. This tolerance affects matching only: matched file lines are emitted unchanged (§8.3), and inserted lines are written as given.
- **Output:** every line of the result is written with its own terminator: unchanged lines keep theirs (so a file with mixed line endings is written back unchanged where not edited); inserted lines receive the file's **EOL convention**, which is the terminator of the first terminated line in the original file, or, if the file has none (empty file, unterminated single line, created file), the **default EOL**: `LF` unless the global option `--eol crlf` (§5.3) or an equivalent host setting says otherwise; the effective default is reported in the result's options (Appendix B). **Final terminator (git semantics):** a hunk **reaches the end of file** when its anchor block includes the file's last line, or when it is an `@@ EOF` hunk. If no hunk of the block reaches the end of file, the last line keeps its original terminator state. Otherwise the **new side** of the last such hunk decides: if the parser recorded a sentinel after the last line of the new side (the last `+` line, or the context line that is the hunk's last body line, §3.1 "Body lines"), the result's last line is **unterminated**; if not, it is **terminated** with the file's EOL convention (a previously unterminated last line gains a terminator, a new last line receives one). This is what `git apply` does and what the §9.2 promise "keeps the target file's terminator state" means: the state is kept unless the patch explicitly changes it. A sentinel recorded after the **old side** (after a `-` line, or after a context line that is not the hunk's last body line) asserts that the original last line was unterminated; a mismatch with the file is **W419** (not an error: generators often lose or add the sentinel). A context line that is the hunk's last body line is the last line of **both** sides, so a sentinel after it is both an old-side assertion and the new-side decision (this is what `git diff` emits for an unchanged unterminated last line). A sentinel in a hunk that does not reach the end of file is also **W419** and has no effect. A **misplaced** sentinel, one that does not follow the last line of either side (after an earlier `+` or `-` line, before the first body line, directly after a `...` marker, or in a create hunk after any line but the last `+` line), is **W419** and has no effect, whether or not the hunk reaches the end of file. For a file produced by a **create** block there is no original file; §6.4.5 applies the same new-side rule.
- **BOM:** a UTF-8 BOM (`EF BB BF`) at the start of the file is not part of the first line's content for matching and is preserved in the result regardless of what happens to the first line (deleted, replaced, or preceded by `@@ BOF` insertions). Other BOMs are not recognized and are ordinary content bytes.

**Content comparison:**
- Comparison and insertion occur at the byte/codepoint level without normalization transformations (except for `--ignore-*` whitespace options).
- The `--ignore-*` options affect **matching only**, not the actual content being inserted or deleted.

---

## 2. Quick Start

### 2.1. Minimal File Edit Example

```diff
--- hello.txt
+++ hello.txt
@@
-Hello, World
+Hello, lite-diff
```

### 2.2. Insertion at Beginning/End

```diff
--- BOF.txt
+++ BOF.txt
@@ BOF
+// inserted at file start
```

```diff
--- EOF.txt
+++ EOF.txt
@@ EOF
+// appended at file end
```

### 2.3. Insertion After Context Line

Insert new lines after a specific line in the middle of file:

```diff
--- app.js
+++ app.js
@@
 import { foo } from './foo.js';
+import { bar } from './bar.js';
+import { baz } from './baz.js';
```

This finds the line `import { foo } from './foo.js';` and inserts two new imports after it.

Insertion **before** a line works the same way, with the `+` lines placed first:

```diff
--- app.js
+++ app.js
@@
+import { bar } from './bar.js';
 import { foo } from './foo.js';
```

### 2.4. Create, Delete, Rename

**Create:**
```diff
--- /dev/null
+++ new.txt
@@
+First line
+Second line
```

A create block contains at most one hunk, consisting of `+` lines only (see §6.4.5). A create block without a hunk creates an empty file.

**Delete:**
```diff
--- old.txt
+++ /dev/null
```

Hunks in a delete block (as emitted by `git diff`) are allowed and ignored (see §6.4.5).

**Rename with changes:**
```diff
rename from old.txt
rename to new.txt
--- old.txt
+++ new.txt
@@
-Old content
+New content
```

The `rename from` / `rename to` lines are **required**: a block whose `---` and `+++` paths differ without them is an error (**E608**), not a rename. This protects against a mistyped path silently moving a file.

### 2.5. Boundary Deletion

Delete everything between two markers (inclusive):

```diff
--- config.js
+++ config.js
@@
-// START_OLD_CONFIG
...
-// END_OLD_CONFIG
+// NEW_CONFIG
+const config = {};
```

This deletes all lines from `// START_OLD_CONFIG` to `// END_OLD_CONFIG` (inclusive) and inserts the new content in their place.

---

## 3. Terms and Conventions

### 3.1. Core Definitions

- **Diff block** — a section of the document consisting of one **header** (§6) followed by zero or more **hunks** (§7). Where a block starts and ends is defined by the parser state machine in §4.1; informally, a block starts at `diff --git`, at a header metadata line, or at a `--- `/`+++ ` pair, and ends where the next block starts or the document ends. Blank lines never start or end a block.

- **Header line lexemes** (all in the first position):
  - **diff command line**: `diff ` followed by anything. `diff --git <src> <dst>` is parsed for paths; any other diff command line (`diff -ruN a/x b/x`, `diff -u …`) is a block start whose paths come from the following `---`/`+++` pair;
  - **path header**: `---` or `+++` followed by **a space or a horizontal tab** and then the path (optionally followed by a tab and a timestamp). `---` or `+++` followed by anything else (`----`, `---x`, `+++i`, `---` at end of line) is **not** a path header;
  - **metadata keyword line**: a line starting with one of `rename from `, `rename to `, `copy from `, `copy to `, `new file mode `, `deleted file mode `, `old mode `, `new mode `, `similarity index `, `dissimilarity index `, `index `, `Binary files `, `GIT binary patch`, `option `. The **operation-opening keywords** are `rename from `, `copy from `, `new file mode `, `deleted file mode `, `similarity index `, `dissimilarity index `. `option ` introduces a block-level option (§5.5);
  - **sentinel**: `\ ` (backslash followed by a space) and anything after it, e.g. `\ No newline at end of file` and its localized variants. A line starting with a backslash followed by any other character is **not** a sentinel;
  - **fence**: a line consisting of three or more backticks, optionally followed by a language name (`` ```diff ``);
  - **hunk header**: see §7.1.

- **Global option** — a line in the **preamble** (§4.1) starting with `--` that is not a path header. Affects parser/applicator behavior for the entire document. Lines starting with `--` in any other state are not options: in a header they are path headers or **E300**, in a hunk body they are deletion lines.

- **Header** — the part of a diff block from its beginning to the first `@@` line. If no `@@` exists, the header extends to the next diff block or end of file.

- **Hunk** — a unit of changes: `@@` header + body.

- **Body lines:** ` ` (context), `-` (deletion), `+` (insertion), a blank line (context of an empty line, see "Blank line" below), and the `...` marker inside boundary blocks. The sentinel `\ No newline at end of file` (lexeme `\ `, §3.1) may appear in the body but is not a body line: the parser records, per hunk, which body line it follows (a `-` line, or a context line that is not the hunk's last body line = **old-side sentinel**; a `+` line = **new-side sentinel**; a context line that is the hunk's last body line is the last line of both sides, so the sentinel counts as **both**; an old-side and a new-side sentinel may both be present, as in `git diff` output; a sentinel after any other line is misplaced, W419) and then drops it (§1.3 "Final terminator"). Comment lines (`#`) are allowed in a hunk body only as a trailing run directly before the next block or the end of the document (see "Comment"); anywhere else a first-position `#` is **E401**.

- **Anchor element** — a body element that participates in locating the hunk: a context line, a deletion line, or a `...` marker. Insertion lines and comments are not anchor elements.

- **Anchor pattern** — a template for finding a position in the file:
  1. **Formation:** the sequence of all anchor elements of the hunk, in body order (i.e., all body elements except `+` lines)
  2. **Element composition:**
     - Lines with ` ` (space) prefix — context lines
     - Lines with `-` prefix — lines to delete
     - `...` markers — special boundary block elements (not lines!)
  3. **Role:** used ONLY for finding the corresponding place in the file

- **Anchor block** — a specific area in the file after successful search:
  1. **Formation:** the result of matching anchor pattern with the file
  2. **Feature:** `...` lines are replaced with actual lines from the file (everything between boundaries)
  3. **Role:** the working area where all changes occur

- **Deletion block** — can be of two types:
  - **Simple deletion** — consecutive lines with `-` prefix
  - **Boundary deletion** — special format with `...` markers for deleting a range (see §7.3)

- **Insertion block** — consecutive lines with `+` prefix

- **Context block** — consecutive lines with ` ` (single space) prefix that serve to locate changes: they **must exactly match** the corresponding lines in the target file, are not modified during patch application, and are used only as positioning reference

- **Search cursor** — current position (0-based line index) in the file **as it currently is** (i.e., after the hunks already applied) from which anchor pattern search begins for the next hunk:
  - Initialized to 0 (file beginning) before processing the first hunk of a diff block
  - After applying a hunk, set to `start + len(output sequence)`, where `start` is the index of the first line of the matched anchor block and the output sequence is defined in §8.3; in other words, the first line after the replaced region in the new file
  - Guarantees that hunks are applied strictly top-to-bottom through the file

- **Line delta** — the signed number of lines by which the file has grown (positive) or shrunk (negative) due to the hunks already applied in the current diff block. Used only by the tie-breaker of §8.2 step 6.

- **Comment** — a line whose **first character** is `#`, located in the **preamble** or in a **header** (§4.1), i.e. before the first block or between a block start and the first hunk header of that block, **or** forming part of a **trailing comment run**: one or more first-position `#` lines, possibly interleaved with blank lines, that are followed directly by a block start line (a diff command line, a metadata keyword line, or a `--- `/`+++ ` pair), by a closing fence, or by the end of the document. A trailing comment run ends the hunk body before it (it is not part of the body) and is ignored. Comments are **not preserved** in parsing results. A first-position `#` line anywhere else in a hunk body (followed by a body line or a hunk header) is **not** a comment but an invalid body line → **E401**.
  - *Rationale (informative):* a `#` line in the middle of a body is almost always a context line whose leading space was lost, and dropping it would silently shorten the anchor; v1.1 therefore rejects it. A `#` line directly before the next block is almost always a comment (real generators write one before every block), and the only thing it could otherwise be is the **last** anchor element of the previous hunk, whose loss cannot change the file content (context lines are emitted from the file). The lookahead rule accepts the common habit while keeping the dangerous case loud.
  - *Rationale (informative):* v1.0 allowed `#` comments inside hunk bodies. A context line such as `#include <x>`, `# Title`, or `#!/bin/sh` whose leading space was stripped by the generator would then silently vanish from the anchor instead of failing. v1.1 trades the comment feature inside bodies for a loud error.

- **Blank line** — a line without any characters (only line feed).
  - **Outside hunk body** (global area, header, between blocks): **allowed** and **ignored**.
  - **Inside hunk body:** a blank line is equivalent to a context line with empty content (` ` followed by nothing). It is an anchor element and must match a file line that is empty or consists only of whitespace (§1.3: trailing whitespace is never significant). See §7.2.
  - **Trailing blank lines** of a hunk body (blank lines after the last body line, up to the body terminator of §7.2) are **not** part of the body and are ignored. To anchor on an empty line at the end of a hunk, write it explicitly as a single space. Sentinel lines (`\`) are not body lines for this purpose: a blank line followed only by a sentinel is still trailing.
  - **Note:** Lines with `+`/`-`/` ` prefix **without content after the prefix** are valid lines representing insertion/deletion/context of an *empty line*. A line of two or more spaces is a context line whose content is the remaining spaces (and, since trailing whitespace is not significant, it matches the same file lines as a blank line). A line whose first character is a horizontal tab is **not** a valid body line → **E401** (a context line for a tab-indented file line is written as space + tab + …).
  - **Processing order (normative):** (1) structural lines are recognized on the raw line sequence according to §4.1 (block starts, hunk headers, body terminators); (2) within each body, sentinel lines are removed (after recording their presence, see "Body lines"); (3) trailing blank lines are stripped. Comments exist only outside bodies (see "Comment") and are removed in step 1 as part of header/preamble processing. Consequently a `#` or `\ ` line inside a body can never influence whether a `--- `/`+++ ` pair is a block start.
  - **Rationale (informative):** v1.0 rejected blank lines in a hunk body (E402) and required a single space for empty context. That single trailing space is routinely stripped by LLM output, chat interfaces, Markdown renderers, clipboards, and editors, which made the most common context in source code (an empty line between definitions) a parse error. `git apply` accepts a blank line as empty context for the same reason.

### 3.2. First Position Rule

All structural elements of lite-diff must start from the **FIRST POSITION** of the line without any indentation. The codes in this table are reported in the **PREAMBLE** and **HEADER** states of §4.1 when a line that is not otherwise recognized becomes a structural lexeme after its leading spaces and tabs are removed. In the **BODY** state an indented line is a context line (a line starting with a space) or E401 (a line starting with a tab); the intended structure cannot be detected there.

| Element | Error Code |
|---------|------------|
| Global options `--` | **E302** |
| Header `diff --git` | **E205** |
| Path headers `---`/`+++` | **E206** |
| Hunk headers `@@` | **E400** |
| Metadata (index, mode, rename, copy) | **E207** |
| Body line prefixes (` `/`-`/`+`/`...`) | **E401** (informative: an indented body line is in general indistinguishable from a context line and is reported as E401 only when the first character is not a valid prefix, e.g. a tab) |

> **Removed in v1.1:** E303 (comment `#` not from first position). A line whose first character is not `#` is by definition not a comment; such lines are handled by the rules of the state they appear in (§4.1). The code is reserved.

### 3.3. Normative Keywords

The keywords **MUST**, **SHOULD**, **MAY** are used in their generally accepted RFC sense (RFC 2119).

### 3.4. Whitespace Definition

For the purposes of `--ignore-*` options, **whitespace** is defined as:
- ASCII space (U+0020)
- Horizontal tab (U+0009)

Other Unicode whitespace characters (non-breaking space, etc.) are **not** considered whitespace by default and are matched literally.

---

## 4. Document Structure

```
─────────────────────────────────────────────────────────────────────
[Global lite-diff options]              ◆ EXTENSION
--ignore-space-at-eol                   ◆ Ignore trailing whitespace (SP, TAB)
--ignore-space-change                   ◆ Ignore whitespace amount changes (SP, TAB)
--ignore-blank-lines                    ◆ Ignore blank lines
--ignore-all-space                      ◆ Ignore all whitespace (SP, TAB)
--apply-all-matches                     ◆ Apply to all matches
--first-match                           ◆ Ambiguous anchor: take first match (v1.0 behavior)
--auto-rename                           ◆ Differing ---/+++ paths = rename (v1.0 behavior)
--lite-diff 1.1                         ◆ Version marker (SHOULD be first)
--check                                 ◆ Validate and match everything, write nothing
--strict                                ◆ Treat W401, W410, W412, W413, W416, W418, W511 as errors
--indent-shift                          ◆ Re-indent a hunk whose anchor differs only in indentation (W415)
--lenient                               ◆ Fallback to --ignore-space-change per hunk (W416)
--skip-applied                          ◆ Skip a hunk that appears already applied (W414)
--strip <N>                             ◆ Remove N leading path components instead of a/ b/ stripping
[Comments (# from first position)]      ◆ EXTENSION (preamble and headers only)
```[lang]                               ○ One opening fence tolerated (W300); matching closing fence after the last block tolerated
─────────────────────────────────────────────────────────────────────
diff --git a/<path> b/<path>            ✓ PARSED (paths extracted)
diff <anything else>                    ✓ BLOCK START (paths from ---/+++)
[extended headers — everything before first @@]
  new file mode <mode>                  ✓ "new file" PARSED / mode IGNORED
  deleted file mode <mode>              ✓ "deleted file" PARSED / mode IGNORED
  old mode <mode>                       ○ IGNORED
  new mode <mode>                       ○ IGNORED
  similarity index <N>%                 ○ IGNORED
  dissimilarity index <N>%              ○ IGNORED
  rename from <path>                    ✓ PARSED (rename operation)
  rename to <path>                      ✓ PARSED (rename operation)
  copy from <path>                      ✓ PARSED (copy operation)
  copy to <path>                        ✓ PARSED (copy operation)
  index <sha>..<sha> [<mode>]           ○ IGNORED
  option <name> [<value>]               ◆ EXTENSION (block-level option, §5.5)
  # comments                            ○ IGNORED
  <any other line>                      ○ IGNORED (W200 optional)
--- a/<path> [\t timestamp]             ✓ path PARSED / timestamp IGNORED
+++ b/<path> [\t timestamp]             ✓ path PARSED / timestamp IGNORED
Binary files ... differ                 ⚠ FILE SKIPPED (W601)
GIT binary patch                        ⚠ FILE SKIPPED (W601), payload lines skipped
new file mode 120000 / 160000           ⚠ FILE SKIPPED (W603), symlink / submodule
─────────────────────────────────────────────────────────────────────
@@ -<start>[,<count>] +<start>[,<count>] @@ [section]  ✓ marker PARSED / numbers used ONLY to resolve ambiguity / section IGNORED
@@                                      ◆ EXTENSION (simplified format)
@@ BOF                                  ◆ EXTENSION (insert at beginning)
@@ EOF                                  ◆ EXTENSION (insert at end)
@@ <scope text>                         ◆ EXTENSION (search starts at the first line containing the text)
 <context line>                         ✓ USED
<blank line>                            ✓ USED (context of an empty line)
-<deleted line>                         ✓ USED
+<added line>                           ✓ USED
-<boundary> ... -<boundary>             ◆ EXTENSION (boundary block)
\ No newline at end of file             ○ IGNORED (sentinel `\ `, presence recorded, dropped from body)
# <anything>                            ✗ E401 (comments are not allowed inside a body)
<body line before any @@>               ✗ E404 (missing hunk header)
─────────────────────────────────────────────────────────────────────
```

> **Note:** Indentation, pseudo-lists, and alignment within the diagram are for clarity only. In a real document, **all** structural elements and lines with prefixes must start from the **FIRST POSITION** (see §3.2).

### 4.1. Parser States (Normative)

The document is parsed line by line with four states. A conformant parser MUST produce the same block/hunk structure as this machine. Within each state the bullets are tested **in the order listed**; the first bullet that applies decides. "Immediately followed by" means: the next line after skipping blank lines and comment lines in the PREAMBLE and HEADER states, and the very next line in the BODY state. In every state a first-position line starting with `@@` is a hunk header candidate: it is either one of the forms of §7.1 or **E403**; a malformed one does not change state.

**State PREAMBLE** (initial):
- blank line → ignored;
- `#…` → comment, ignored;
- a fence lexeme, occurring as the first non-blank, non-comment line → ignored with **W300**; the parser remembers that a fence is open;
- a line matching the option grammar of §5 (`--[a-z][a-z-]*` optionally followed by a space and a value) that is not a path header lexeme → global option; unknown name → **E301**;
- a diff command line, an operation-opening keyword or any other metadata keyword line, or a path header `--- ` immediately followed by a path header `+++ ` → enter **HEADER**; this line is the block start and is processed by the HEADER rules (so `rename from …` is recorded);
- a well-formed hunk header (§7.1) → **E306** (a hunk cannot precede its block);
- a line that becomes a structural lexeme after removing leading spaces/tabs → **E205** (`diff`), **E206** (`---`/`+++`), **E207** (metadata keyword), **E302** (option), **E400** (`@@`);
- any other line, including `---` alone, a lone `--- …` not followed by `+++ `, any other `--…` line, prose, `From …`, `Subject: …` → **E306** "unexpected text before first diff block".

**State HEADER** (from the block start line to the first hunk header or the next block):
- diff command line → ends the current block, starts a new one (stays in HEADER);
- path header `--- ` immediately followed by `+++ `, when the current header **already holds a `+++` line** → ends the current block, starts a new one (stays in HEADER). This is how a hunk-less block (delete, create of an empty file) is followed by the next block without `diff --git`;
- path header `--- ` immediately followed by `+++ `, when the current header holds a **completed `from`/`to` pair**: if the `---` path, after the processing of §6.3.1, equals `from`, the pair **belongs to this rename/copy header** (the ordinary "rename with changes" shape of §2.4 and of `git diff`; a `+++` path that differs from `to` is then **E209**, so a typo in `+++` is reported precisely). Otherwise (the `---` path differs from `from`, including `/dev/null`) → ends the current block, starts a new one (a pure rename followed by another block without `diff --git`).
- an **operation-opening keyword**, when the current header already holds a `+++` line or a completed `from`/`to` pair → ends the current block, starts a new one (the line is processed by the HEADER rules of the new block);
- a line that becomes a structural lexeme after removing leading spaces/tabs → **E205** / **E206** / **E207** / **E302** / **E400** as in PREAMBLE (tested before the body-looking rule, so an indented `@@` after `+++` is E400, not E404);
- **body-looking line after `+++`:** when the current header already holds a `+++` line, a line whose first character is a space, `+`, or `-` and which is not a hunk header, a diff command line, a metadata keyword line, a `+++ ` path header (that is E200 below), or a `--- ` path header immediately followed by `+++ ` → **E404** "body line before hunk header (missing `@@`?)". This includes a lone `--- …`, a `-- …` line and an option-looking `--…` line in that position (a `--- ` not followed by `+++ ` is a body line, not a duplicate path header). E404 is reported **once per block**, at the first such line, and the remaining body-looking lines of that block are skipped;
- `GIT binary patch` → **W601**; all following lines up to the next diff command line, metadata keyword line, or `--- `/`+++ ` pair are the binary payload and are skipped;
- path header `--- ` / `+++ ` otherwise → recorded; a second `---` or a second `+++`, or at the end of the header a `---` without `+++` or vice versa → **E200**;
- metadata keyword line → recorded (operation, `option`) or ignored (metadata), per §6.2 and §5.5;
- `#…` → comment, ignored;
- hunk header (§7.1) → enter **BODY**;
- blank line → ignored;
- a line matching the option grammar of §5 → **E300** (global options are allowed only in the preamble; use `option <name>` for a block-level option);
- a line whose first character is a space, `-` (and which is not a path header or metadata keyword line), `+` (and which is not a path header), or which starts with `...` → **E404** (header without `+++` yet, e.g. a block that starts with `---` and has body lines before `+++`);
- a fence lexeme while a fence is open → enter **TRAILER**;
- any other line → ignored; an implementation MAY emit **W200** "unrecognized header line".

**State BODY** (from the line after the hunk header):
- hunk header → ends this hunk, starts the next (stays in BODY);
- diff command line or a metadata keyword line → ends this hunk and the block, enter HEADER (these lines can never be body lines: they do not start with a valid prefix);
- path header `--- ` immediately followed by a path header `+++ ` → ends this hunk and the block, enter HEADER, **unless** the §7.2 body-pair rule applies, in which case both lines are body lines;
- a fence lexeme while a fence is open → ends this hunk and the block, enter **TRAILER**;
- a first-position `#` line → look ahead over the following `#` and blank lines: if the next other line is a block start line, a closing fence while a fence is open, or there is none (end of document), the run is a **trailing comment run** (§3.1 "Comment"): it ends this hunk and the block, and the `#` lines are ignored; otherwise the `#` line is **E401**. A `--- ` line in this position is a block start when it is followed, after blank and comment lines, by a `+++ ` line (the HEADER sense of "immediately followed"); the body-pair rule of §7.2 does not apply to it, since the body has already ended;
- any other line → body line, sentinel, or **E401** per §7.2; blank lines are body lines (empty context) and never end a body;
- end of document → ends the hunk and the block.

**State TRAILER** (after the closing fence):
- blank line → ignored;
- any other line, including a well-formed hunk header → **E306** "unexpected text outside the diff" (the same code as for text before the first block).

Trailing blank lines are stripped from each body after it is delimited (§3.1 "Blank line", processing order).

> **Rationale (informative):** v1.0 described block boundaries in prose, under which a normal `git diff` header read literally as three blocks (`diff --git`, `index`, `---`/`+++`) and E200 was unreachable. The state machine makes the structure deterministic. E404 exists because a block whose generator forgot the `@@` line would otherwise be a silent no-op.

---

## 5. Global Options (Extensions)

> Applicable **only in the preamble** (§4.1), i.e. before the first diff block. Each option on a separate line, starting from the FIRST POSITION (no indentation). Duplicates are ignored.

**Option line grammar:** `--<name>` or `--<name> <value>` (name and value separated by exactly one space; `=` is not a separator). `<name>` matches `[a-z][a-z-]*`. A boolean option is switched off with the value `off` (`--first-match off`), as at block level (§5.5); an invalid value for an option that takes one (`--strip x`, `--eol mac`) → **E301**. A `--` line in the preamble that is a path header lexeme (`--- ` or `--- <tab>`) is not an option: followed by `+++ ` it starts the first block, otherwise it is **E306**. A `--` line that does not match the grammar (`---` alone, `-- text`) → **E306**. An option line with an unknown name → **E301**.

**Version marker:** `--lite-diff <major>.<minor>` declares the version of this specification the document is written for (e.g. `--lite-diff 1.1`). It is optional and SHOULD be the first option. A value that is not of the form `<major>.<minor>` → **E301** (invalid option value). An implementation that does not support the declared major version, or supports a lower minor version of the same major, → **E308** "unsupported lite-diff version". Without the marker the document is interpreted as the newest version the implementation supports. Generators SHOULD emit the marker so that hosts can tell which rules a patch expects.

**Compatibility profile 1.0:** `--lite-diff 1.0` (or an equivalent host setting) runs a v1.1 implementation with the behavior of v1.0 wherever v1.0 applied a patch **to a definite place**, with one engine. It implies `--auto-rename` and `--first-match` (implied options never raise a conflict error such as E305), disables `--strict`, and makes a first-position `#` line inside a hunk body a comment that is dropped (as in v1.0) instead of E401 (the trailing-comment-run rule of §4.1 is applied first, so a run before the next block ends the block exactly as in 1.1). It does **not** restore v1.0 behavior where v1.0 did nothing or did something undefined: a block without a hunk header is still E404, a hunk without an anchor is still E412, and `@@ <text>` is a scope header (it was not valid in v1.0 either). All v1.1 widenings (blank lines as context, `+` before the first anchor, trailing whitespace tolerance, git compatibility) remain in effect, and all v1.1 diagnostics are produced. The profile exists for the transition of existing users; hosts SHOULD default to 1.1 with `--strict` and offer 1.0 as a setting.

### 5.1. Whitespace Matching Options

These options affect **matching only** — they do not modify the actual content being inserted or deleted. Line prefixes (` `, `-`, `+`, `...`) are structural markers and are **never** affected by these options.

- `--ignore-space-at-eol` — accepted for compatibility with v1.0. Trailing whitespace is **always** ignored during matching in v1.1 (§1.3); the option has no further effect.
- `--ignore-space-change` — ignore changes in the amount of whitespace (SP, TAB) during matching: any sequence of one or more whitespace characters, including leading indentation, is equivalent to any other such sequence; the presence or absence of whitespace is still significant (as in `git diff --ignore-space-change`).
- `--ignore-blank-lines` — during matching, **file** lines that are empty or consist only of whitespace (§3.4) are skipped, **unless** the next anchor element to match is a `-` line whose content equals that file line under the active comparison (an empty `-` line consumes an empty or whitespace-only file line; a `-` line with other content lets the blank be skipped). Blank **context** anchor elements (a blank body line or ` ` with empty content) are removed from the anchor pattern. Skipped file lines are emitted unchanged (§8.3). The **anchor block** starts at the file line matched by the first anchor element and ends after the file line matched by the last one; a candidate never starts on a skipped line, and blank lines after the last matched element are outside the anchor block (they do not move the cursor). Lines between two segments of a boundary block (§7.3) are captured by `...` and dropped regardless of this option. Examples: file `a`,``,`b`; hunk ` a` / ` b` / `+c` → `a`,``,`b`,`c`; hunk ` a` / `+c` / ` b` → `a`,`c`,``,`b` (§8.3: the insertion stays attached to the line it follows); hunk ` a` / `-` / ` b` → `a`,`b`; hunk ` a` / `-b` / `+c` → `a`,``,`c`.
- `--ignore-all-space` — ignore all whitespace (SP, TAB) during matching (overrides others).

Because trailing whitespace is ignored during matching, a context, blank or `-` element with empty content matches a whitespace-only file line, and a context line for `    ` (four spaces) may be written as a blank line. Leading and internal whitespace remain significant unless `--ignore-space-change` or `--ignore-all-space` is set, or the opt-in levels of §8.2 step 5 apply.

> *Rationale (informative):* there is deliberately no **default** that forgives leading whitespace after an exact match has failed. A hunk whose anchor is indented wrongly almost always carries the same wrong indentation on its `+` lines, and `--ignore-*` never alters inserted content, so forgiving the anchor would write the wrong indentation into the file — a semantic change in indentation-sensitive languages. Trailing whitespace is forgiven because no rule of §8.3 can carry that difference into the result. The E410 diagnostic of §8.6 is the intended fix path for indentation errors; `--indent-shift` (§5.2) is the opt-in that corrects them, and `--lenient` the opt-in for hosts whose targets are whitespace-insensitive.

### 5.2. Application Modes

- `--apply-all-matches` — apply hunk to **all** occurrences of the corresponding **anchor block** in the target file. **Restriction:** allowed only for diff blocks with a single hunk → **E304**. The ambiguity check and the order checks of §8.2 steps 6–8 do not apply under this option (§8.4).
- `--first-match` — when an anchor pattern matches more than once after the search cursor and the hunk header does not resolve the ambiguity (§8.2 step 6), apply the hunk to the **first** match instead of reporting **E414**. This restores v1.0 behavior for hand-written `@@` hunks; `git diff` output normally resolves ambiguity through its qualifying unified headers and does not need this option. Mutually exclusive with `--apply-all-matches` → **E305**.
- `--auto-rename` — treat a diff block whose source and target paths (§6.3.1) differ (neither being `/dev/null`) and which has no explicit operation header as a rename, instead of reporting **E608**. This restores v1.0 behavior.
- `--check` — parse, validate, and match every block and hunk exactly as for a real application, produce the full result (§8.6), but write nothing to the file system. Hosts SHOULD also expose this mode as a tool-level switch.
- `--strict` — the warnings **W401**, **W410**, **W412**, **W413**, **W417**, **W418**, and **W511** are treated as errors (W416 cannot occur under `--strict`, since `--lenient` with `--strict` is E307): the diagnostic keeps the warning code and the document is not written. **Exception for W410:** when the chosen candidate starts **exactly** at `expected` (§8.2 step 6.2), the hint was precise, as it always is in `git diff` output, and W410 is **not** escalated; it is escalated only when the chosen candidate is merely the closest one. *Informative:* on real `git diff` output with three lines of context about one hunk in three hundred needs the hint, and every one of them hits exactly; a hand-written header rarely does. W401 is a parse-phase warning, so under `--strict` it is a parse failure: the block containing the W401 line is `failed`, all other blocks `not-attempted` (§8.6). The others are match-phase warnings, so the hunk and its block are `failed` and the match phase stops there. **W415** is not escalated (the re-indented content is consistent with the file). Together with `--lenient` → **E307**. Hosts that apply LLM-generated patches SHOULD enable this mode by default, since each of these warnings marks a place where the patch may have been applied somewhere other than intended, or not applied at all.
- `--indent-shift` — enables level (b) of §8.2 step 5 (re-indentation): a hunk whose anchor matches only after a uniform change of leading whitespace is applied with the same change applied to its `+` lines. Off by default. **W415** is mandatory on use and is not escalated by `--strict`.
- `--lenient` — enables level (c) of §8.2 step 5: when a hunk has no candidate at the earlier levels, its anchor is compared with `--ignore-space-change` semantics; `+` lines are written as given. **W416** (hunk, position) is mandatory on use. Off by default. Together with `--strict` → **E307**. *Informative:* intended for hosts whose target files are whitespace-insensitive and reformatted after application (Go, Rust, C, JSON); it never corrects the indentation of inserted lines, and it applies to every file the document touches, since options are document-wide, unless overridden per block (§5.5).
- `--skip-applied` — when a hunk appears to be already applied (§8.2 step 5: no candidate but the **applied pattern** matches exactly once from the search start, or a pure insertion whose applied pattern matches at its candidate), the hunk is skipped with **W414** instead of E410 / W417, and the cursor moves past the match. Off by default. Without the option the E410 diagnostic MUST still state that the hunk appears to be already applied and where, and W417 is emitted (§8.6).

### 5.3. Path Options and Named Roots

**Component stripping:** `--strip <N>` (N ≥ 0) removes the first N path components from every `diff --git` and `---`/`+++` path (never from `rename`/`copy` paths or `/dev/null`) **instead of** the letter-prefix rule of §6.3.5, which is then not applied. `--strip 1` makes GNU `diff -ru old/ new/` output usable (`old/x` and `new/x` both become `x`). A path with N or fewer components (the result would be empty) → **E104**.

**Default line ending:** `--eol lf` (default) or `--eol crlf` sets the terminator used where the target file has no terminated line to copy (§1.3). Any other value → **E301**.

**Named roots**, for environments with multiple project roots (e.g., monorepos, multi-folder workspaces):

- `--default-root @<root-name>` — set default root for paths without explicit `@root` prefix (without a value → **E301**)
  - `<root-name>` must correspond to an existing root name → **E215**
  - In single-root environments, ignored with warning **W301**
  - Without `--default-root` in multi-root: paths without prefix → **E214**
  - First occurrence is used for duplicates

**Path prefix format:**
- Syntax: `@<root-name>/path/to/file`
- Prefix is part of the path and is removed during resolution

**Resolution priority (highest to lowest):**
1. Explicit prefix in path (`@frontend/src/app.js`)
2. Value from `--default-root` for paths without prefix
3. Single root in single-root environment

> **Note:** The dictionary of available roots and detection of multi-root environment are the responsibility of the host tool/environment, not the lite-diff format itself. The `@<root-name>/` prefix is recognized **only** when the host has declared a multi-root environment; in a single-root environment a path such as `@types/index.d.ts` (an npm scope directory) is an ordinary relative path.

### 5.4. Restrictions and Errors

- A global option line is recognized only in the preamble. A line matching the option grammar that appears in a header → **E300**; in a hunk body a line starting with `--` is a deletion line, never an option. Block-level options use the `option ` header line (§5.5), not the `--` form.
- `--ignore-*` affects context and boundary search but **does not change** the inserted/deleted lines themselves.
- **Line prefixes are structural markers:** `--ignore-*` options apply only to line CONTENT (after prefix), not to the prefixes themselves.

### 5.5. Block-level Options

A header line `option <name>[ <value>]`, where `<name>` is an option name **without** the leading `--`, sets that option for the current diff block only, overriding the global value. Several `option` lines are allowed; a later one for the same name wins.

- Allowed at block level: `ignore-space-at-eol` (a no-op, accepted for symmetry), `ignore-space-change`, `ignore-blank-lines`, `ignore-all-space`, `apply-all-matches`, `first-match`, `indent-shift`, `lenient`, `skip-applied`. A boolean option is switched **off** for the block with the value `off` (`option lenient off`); any other value, or no value, switches it on.
- Not allowed at block level (document-wide by nature): `lite-diff`, `strict`, `check`, `auto-rename`, `strip`, `eol`, `default-root` → **E309**. An unknown name → **E301**.
- Conflicts are checked per block with the effective values: `apply-all-matches` with `first-match` → **E305**; `lenient` with a global `strict` → **E307**.
- `option apply-all-matches` is the intended way to replace all occurrences in one file while other blocks of the same document keep several hunks (E304 is checked per block).

---

## 6. Block Header

### 6.1. Header Boundaries

**Start:** the block start line as defined by the state machine in §4.1:
- If `diff --git` exists — from this line
- Otherwise — from the first metadata keyword line (rename/copy/new/deleted/index/…)
- If no metadata — from the `--- ` line of a `--- `/`+++ ` pair

**End:**
- First hunk header line
- If no hunk header exists, header extends to the start of the next diff block or end of document

**Unrecognized lines** inside a header (anything that is not a path header, a metadata keyword line, a diff command line, a hunk header, a fence while a fence is open, a body-looking line (E404), a comment, or blank) are **ignored**; an implementation MAY emit **W200**. Examples: `literal 1234` and base85 payload after `GIT binary patch` (always skipped, §4.1), `Only in …` from `diff -r`.

### 6.2. Header Content

| Category | Elements | Processing |
|----------|----------|------------|
| **Paths** | `diff --git a/<path> b/<path>`, `--- <path>` (or `/dev/null`), `+++ <path>` (or `/dev/null`) | ✓ Extracted |
| **Operations** | `new file mode`, `deleted file mode`, `rename from/to`, `copy from/to` | ✓ Type determined |
| **Metadata** | `index`, `similarity/dissimilarity index` | ○ Ignored |
| **Mode lines** | `old mode`, `new mode` | ○ Values ignored, except `120000`/`160000` (W603); their presence makes a hunk-less edit block valid (§6.4.1) |
| **Block options** | `option <name> [<value>]` | ✓ Block-level option (§5.5) |
| **Binary** | `Binary files ... differ`, `GIT binary patch` | ⚠ W601, block skipped — except a binary delete (`deleted file mode`), which is applied like any delete and emits no W601 |
| **Non-regular** | `new file mode 120000` / `160000`, `deleted file mode 120000` / `160000`, `old mode`/`new mode` with these values | ⚠ W603, block skipped (symbolic link / submodule) |
| **Other** | any other line | ○ Ignored (W200 optional) |

### 6.3. Path Extraction

#### 6.3.1. Required Elements and Path Extraction

Every block has exactly one **source path** and one **target path** (either may be the special value `/dev/null`). They are determined once, as follows, and all later checks (§6.3.2, §6.4) refer to them:

- **Path sources:** `diff --git <src> <dst>`, the `---`/`+++` pair, and the `rename from`/`rename to` or `copy from`/`copy to` pair.
- **Extraction priority:**
  0. If the `---` path is `/dev/null`, source = `/dev/null`; if the `+++` path is `/dev/null`, target = `/dev/null`. These assignments take precedence over every rule below, which then determine only the non-null side(s). (git writes `diff --git a/new b/new` together with `--- /dev/null`.)
  1. If `diff --git` exists — source = `<src>`, target = `<dst>`.
  2. Otherwise, if `---`/`+++` exist — source = `---` path, target = `+++` path.
  3. Otherwise, if `rename from/to` or `copy from/to` exist (a pure git rename/copy has no `---`/`+++`) — source = `from` path, target = `to` path.
  4. Otherwise → **E210** "block has no path source".
- **Path processing order** (applies to every path everywhere in this specification): (1) unquoting and escape decoding (§6.3.4); (2) prefix removal (§6.3.5) — for `diff --git` and `---`/`+++` paths only; (3) normalization (§6.3.6); (4) security checks (§6.3.3).
- **Special path `/dev/null`:**
  - As the `---` path, or as the source, means file creation
  - As the `+++` path, or as the target, means file deletion
  - `/dev/null` is never prefix-stripped, quoted, or normalized, and is exempt from the consistency checks below on the null side.

#### 6.3.2. Path Consistency

Checks are performed in this order; the first failure is reported:

1. **Unpaired or duplicate path headers:** a `---` without `+++`, a `+++` without `---`, a second `---`, or a second `+++` in one header → **E200**.
2. **`diff --git` vs `---`/`+++`** (when both are present): `<src>` must equal the `---` path and `<dst>` must equal the `+++` path, except that a `/dev/null` side of `---`/`+++` is not compared. Mismatch → **E202**.
3. **Operation header vs `---`/`+++`** (when both are present): `rename from` / `copy from` must equal the `---` path, `rename to` / `copy to` must equal the `+++` path. Mismatch → **E209**.
4. **Operation header vs `diff --git`** (when both are present and `---`/`+++` are absent): `from` must equal `<src>`, `to` must equal `<dst>`. Mismatch → **E209**.
5. **No implicit rename:** without a `rename`/`copy` header and with neither path being `/dev/null`, the source path and the target path must be **equal**. Differing paths → **E608** (unless `--auto-rename` is set, see §5.2).

All comparisons are made after the path processing order of §6.3.1. Prefix removal (or `--strip`) applies to `diff --git` and `---`/`+++` paths only; `rename`/`copy` paths are unquoted and normalized but **never prefix-stripped** (git never prefixes them), so `rename from a/old.txt` names a file in a real directory `a/`.

#### 6.3.3. Allowed / Prohibited

- **Allowed:** relative workspace paths; slashes `/` and `\` (normalized); dots in names (`.env`, `config.local.json`).
- **Prohibited:**
  - absolute paths (**E100**); on Windows also any path containing `:` (§6.3.5)
  - path traversal (`..`, `.`) — **E101**
  - glob patterns (`*`, `**`, `?`) — **E102**
  - symbolic links — **E103** (path validation checks file type in filesystem; symlinks are rejected)

#### 6.3.4. Quoting and Escape Sequences

- C-style escapes allowed: `\"`, `\\`, `\n`, `\r`, `\t`, `\xHH`, `\NNN`.
  - Octal escape sequences `\NNN` valid only in range `\000`-`\377` (0-255 decimal).
  - Values `\400`-`\777` are invalid → **E203**.
- **Decoding:** escapes yield **bytes** (git quotes non-ASCII paths as UTF-8 byte sequences, e.g. `"a/caf\303\251.txt"`); the resulting byte string is decoded as UTF-8 (invalid UTF-8 → **E203**). Prefix removal and normalization follow, in the order given in §6.3.1.
- **Quoting is optional.** A path is quoted when its first character is `"`; the path then extends to the matching unescaped `"`, and escapes are decoded inside. Git quotes a path only when it contains control characters, `"`, `\`, or (by default) non-ASCII bytes.
- **Unquoted paths in `---`/`+++` lines** extend from the character after the lexeme's space or tab to the first **tab** or the end of line; a tab and anything after it is the optional timestamp. Spaces inside are part of the path (`--- a/my file.txt` names `my file.txt`), as `git diff` writes them. **Trailing** spaces and tabs are removed from every unquoted path: the `---`/`+++` path, the remainder of a `diff --git` line (before it is split), and `rename`/`copy` paths (git never writes them, generators and editors add them, on Windows a trailing space cannot even be part of a file name, and otherwise two spellings of the same file would disagree with E202 or E209).
- **Unquoted paths in `diff --git <src> <dst>`:** the remainder after `diff --git ` is split at the single space position for which the two halves are **identical after prefix removal**, or, failing that, at the single space position for which both halves are non-empty and the second starts with a letter-prefix (§6.3.5) when the first does. If no position or more than one position qualifies → **E204** "cannot split diff --git paths; quote them". (Git itself can only guess here; a generator that needs spaces in a renamed path SHOULD quote or rely on the `---`/`+++` lines.)
- A quoted path with an unterminated `"` → **E203**.

#### 6.3.5. Prefixes `a/` `b/`

- Standard `a/` and `b/`, git mnemonic prefixes (`i/`, `w/`, `c/`, `o/`, produced by `diff.mnemonicPrefix`), and no prefix are supported. Custom `--src-prefix`/`--dst-prefix` values are supported through `--strip 1` (§5.3).
- **The v1.0 `<prefix>:` form is removed in v1.1.** A colon in a path is not a separator of any kind. A single letter followed by `:` and `\` or `/` is a Windows drive and the path is absolute → **E100** on every platform. **On Windows** (and on any platform where `:` has a file-system meaning) a path containing `:` anywhere → **E100**: `c:x.txt` is a drive-relative path that leaves the workspace, and `notes:2026.txt` would name an alternate data stream of the file `notes` on NTFS, a silent relocation. On other platforms a colon is an ordinary character; a host MAY apply the Windows rule everywhere for portability. *Rationale:* `+++ notes:2026.txt` silently created `2026.txt` in v1.0, the same kind of relocation that the prefix rule of §6.3.5 excludes for one-letter directories; named roots use the `@root/` form (§5.3). **E201** is reserved.
- **Letter-prefix rule:** in a `diff --git` line and in `---`/`+++` path headers, a leading `a/`, `b/`, `c/`, `i/`, `o/` or `w/` (git's prefix letters, exactly these six) is a prefix and is removed (the two sides need not use the same letter: `--- i/x` / `+++ w/x` resolves to `x` / `x`; a `/dev/null` side is simply not stripped). Any other single-letter directory (`R/`, `t/`, `x/`) is **not** a prefix and is kept. A real top-level directory named with one of the six letters must be written with a prefix in these lines (`a/b/file`). `rename`/`copy` paths are never prefix-stripped (§6.3.2). When `--strip N` is set, this rule is replaced by component stripping (§5.3).
- Prefixes are removed before normalization (§6.3.1 order), so the rule is applied to the path as written with `/`. `/dev/null` is never prefix-stripped.

#### 6.3.6. Normalization

- Slashes normalized to OS format (`/` on Unix, `\` on Windows)
- Unicode normalized to **NFC** (e.g., é as U+00E9, not e + U+0301)
- Paths always relative to workspace root

### 6.4. Operation Definition

#### 6.4.1. Operation Types

| Operation | Indicators | Checks | Errors |
|-----------|------------|--------|--------|
| **Create** | `new file mode` or source = `/dev/null` | File does not exist | **E600** (if file EXISTS) |
| **Delete** | `deleted file mode` or target = `/dev/null` | File exists and is regular | **E601** (if not found or not regular file) |
| **Rename** | `rename from/to` (explicit header required; see §6.4.2) | Source exists, target does not | **E603** (source NOT exists) / **E602** (target EXISTS) |
| **Copy** | `copy from/to` | Source exists, target does not | **E603** (source NOT exists) / **E602** (target EXISTS) |
| **Edit** | Other cases | File exists | **E611** (file NOT exists) |

**Non-regular modes:** if any mode line in the header (`new file mode`, `deleted file mode`, `old mode`, `new mode`) carries `120000` (symbolic link) or `160000` (submodule), the whole block is skipped with **W603** and its hunks are not applied. Other mode values are ignored. A **submodule pointer update** has no mode line: `git diff` emits an `index` line and one hunk whose body lines all begin with `-Subproject commit ` or `+Subproject commit `; such a block is also skipped with **W603**.

**Document with every block skipped** (W601/W603 only): overall status `applied` (or `checked`), `written` empty.

**Edit block without hunks:** valid only when the header contains an `old mode`/`new mode` pair (`git diff` emits this for pure mode changes); the file must exist (**E611** otherwise), nothing is changed, and the implementation MUST emit **W412**. An edit block without hunks and without mode lines → **E404** (the generator most likely forgot the hunk header, or the body lines were reported as E404 already).

#### 6.4.2. Operation Validation Rules

- **Mutual exclusion:** the indicators of §6.4.1 (operation headers **and** `/dev/null` paths) must imply at most one operation within one block → **E604** otherwise. Examples: `new file mode` together with `+++ /dev/null`; `rename from` together with `copy from`; `deleted file mode` together with `--- /dev/null`. (A `--- /dev/null`/`+++ x` pair after a completed `rename from`/`rename to` pair starts a **new** block by §4.1 and is a rename followed by a create, not E604.)
- **Incomplete or duplicated operations:** either half of the pair missing (`from` without `to`, or `to` without `from`), or either half repeated in one header → **E605** (rename) / **E606** (copy); for a repetition the offending line is the first repeating line
- **No implicit rename:** if no explicit operation header is present and the source and target paths (§6.3.1) differ (neither being `/dev/null`) → **E608**. The block is rejected; nothing is moved or written. With the global option `--auto-rename` such a block is treated as a rename (v1.0 behavior).
  - *Rationale (informative):* a one-character typo in a path (`src/app.ts` vs `src/App.ts`) must not silently turn an edit into a file move. An explicit `rename from`/`rename to` pair costs two lines and makes the intent unambiguous.

#### 6.4.3. Application Order for Rename/Copy with Hunks

For `rename` and `copy` operations that include hunks:

1. Hunks are matched against the **source** file content as it exists **before** the operation.
2. After all hunks are applied to the source content in memory, the resulting content is written to the **target** path.
3. For `rename`: source file is removed after successful write to target. Directories left empty by a rename or a delete SHOULD be removed, as `git apply` does; they are not listed under `written`, which names files only.
4. For `copy`: source file remains unchanged.
5. If source does not exist → **E603**; if target already exists → **E602**.
6. EOL/BOM handling follows §1.3 and §11 (inherited from source).

#### 6.4.4. Validation Order for a Block

Checks are performed per block in this order. Steps 1–4 belong to the parse phase (§8.1): every failure found in steps 2–4 of every block is reported (a block MAY accumulate several parse errors, e.g. E209 and E415). Steps 5–7 belong to the match phase and stop at the first failure of the first failing block.

1. Binary (**W601**) or non-regular mode (**W603**) → block skipped: steps 2–7 are not performed for it, except that a **binary delete** (`deleted file mode` plus a binary indicator) is not skipped and proceeds as a delete (its content is not needed; no W601 is emitted, since nothing was skipped; a non-regular mode still wins: W603). Its structure is still parsed by §4.1 (so an E401 inside it is still an error of the document). The `operation` reported for a skipped block is the one its header indicators imply (§6.4.1: create, delete, edit), not a placeholder.
2. Header structure and path consistency (§6.3.2: E200, E202, E209, E608), block-level options (§5.5: E301, E305, E307, E309) and operation validity (§6.4.2: E604–E606).
3. Path syntax (§6.3.3: E100–E102; §5.3: E104) on the non-null paths.
4. Hunk structure (§7, §6.4.5: E400–E404, E411, E412, E415–E417, E5xx).
5. Path type (§6.3.3: **E103**) — a symbolic link at a non-null path, so deleting or editing a symlink is E103, not E601/E611, unless the header declared mode `120000` (then step 1 applies).
6. File-system state (§6.4.1: E600–E603, E611).
7. Matching (§8.2: E410, E413, E414).

#### 6.4.5. Hunks in Create and Delete Blocks

**Create** (`--- /dev/null` or `new file mode`):
- The block MAY contain **zero or one** hunk. Zero hunks → an empty file is created.
- The hunk header MAY be any of `@@`, `@@ BOF`, `@@ EOF`, or a unified header (typically `@@ -0,0 +1,N @@` as emitted by `git diff`); the header form has no effect on the result.
- The hunk body MUST consist of `+` lines only (sentinel lines are allowed; one after the last `+` line is the new-side sentinel, one anywhere else is **W419** and ignored). Any context, deletion, blank, or `...` element → **E415**. In a create block **E415 takes precedence** over E411 (for `@@ BOF`/`@@ EOF`) and over E412.
- More than one hunk → **E415**.
- The file content is the sequence of `+` line contents. The created file ends with a line terminator (the default EOL, §1.3) unless the parser recorded a new-side sentinel after the last `+` line of the hunk (§3.1 "Body lines").

**Delete** (`+++ /dev/null` or `deleted file mode`):
- The block MAY contain hunks (as emitted by `git diff`, typically `@@ -1,N +0,0 @@` with `-` lines only). Such hunks are **not applied**.
- An implementation MAY compare the `-` lines of those hunks with the current file content and report **W602** if they do not match; this never prevents the deletion.
- A hunk containing `+` lines in a delete block → **E415** (takes precedence over any other hunk error).

---

## 7. Hunks (Core + Extensions)

### 7.1. Hunk Headers

- **Unified:** `@@ -<start>[,<count>] +<start>[,<count>] @@ [section]` — the position is found by content; `<start>` of the old range is used **only** as a tie-breaker when the anchor pattern matches more than once, and only when the `<count>` values are consistent with the body (§8.2 step 6). `section` is ignored.
- **Simplified** (Extension): `@@`.
- **BOF/EOF** (Extension): `@@ BOF` (insert at beginning) / `@@ EOF` (insert at end). After such headers, only `+` lines and sentinel lines are allowed. Any other line → **E411**. Since a blank line inside a body is a context line (§3.1), a blank line **between** `+` lines of a BOF/EOF hunk is **E411**; an empty line to insert must be written as `+` with no content. Trailing blank lines after the last `+` line are not part of the body (§7.2) and are ignored.

- **Scope** (Extension): `@@ <scope>` — the anchor is searched only from the first line at or after the cursor that contains the scope text (§8.2 step 2a). Typically the enclosing definition, e.g. `@@ def parse(`.

**Hunk header lexeme (normative):** a line in the first position starting with `@@` is a hunk header candidate. It MUST have exactly one of these forms (trailing spaces and tabs are permitted and ignored in all forms); the forms are tested in this order and the first that matches decides:
1. `@@` alone;
2. `@@ BOF` or `@@ EOF` (uppercase only, exactly one space);
3. `@@ -<a>[,<m>] +<b>[,<n>] @@` optionally followed by a space and arbitrary section text;
4. `@@ <scope>`: `@@`, exactly one space, then **scope text**: at least one non-whitespace character, the first of which is not `-`, `+` or `@`, and not a space or tab (`@@  text` with two spaces is E403, not a scope with leading whitespace). The scope text is compared as an exact substring of a file line's content under the whitespace rules of §1.3 and §5.1, never as a pattern. In a create block the scope text is ignored. `@@ bof` and `@@ eof` (lower case) are scope headers: with a `+`-only body they are **E412** (§8.3), otherwise almost certainly **E418**; both messages carry the uppercase hint.

Any other line starting with `@@` → **E403** "malformed hunk header". This includes `@@BOF`, `@@ @@`, `@@ -12,7 +12,8` (a remainder starting with `-`, `+` or `@` is read as an attempt at a unified header and is never scope text), and combined-diff headers `@@@ … @@@` (out of scope, §1.2).

**Position of BOF/EOF hunks:** `@@ BOF` is allowed only as the **first** hunk of its block and `@@ EOF` only as the **last**; otherwise → **E417**. (A `@@ BOF` hunk after another hunk would move the search cursor backwards, violating §8.5.)

**Note:** All hunk headers must start from the FIRST POSITION (no indentation), otherwise error **E400** (detectable in the PREAMBLE and HEADER states only, §3.2). The `...` marker and body prefixes likewise; a `...` marker MAY carry trailing spaces or tabs, but `...` followed by anything else (`...and more`) is **E401**, never a marker.

### 7.2. Hunk Body

**Hunk body boundaries** (see the BODY state in §4.1):
- Start: line immediately after the hunk header
- End: the line before the first of:
  1. the next hunk header (§7.1);
  2. a diff command line or a metadata keyword line (§3.1 lexemes) — these start a new block from anywhere, since they can never be body lines;
  3. a path header `--- ` immediately followed by a path header `+++ `, unless the **body-pair rule** below applies;
  4. a closing fence while an opening fence was tolerated (§4.1 TRAILER);
  5. end of document.
- Blank lines never terminate a body. Trailing blank lines of the body (after the last body line, up to the terminator above) are NOT part of the hunk body.
- Any other line in the first position that is not a valid body line or a sentinel (see table) → **E401**.
- A hunk whose body contains no body lines at all (after removing sentinels and trailing blanks) → **E416** "empty hunk body".

**`---` / `+++` inside a body (normative):**
- Only the path header lexeme counts: `---` or `+++` followed by a space or tab. `----`, `---x`, `+++i;` and `---` alone are ordinary body lines (deletion of `---`, deletion of `--x`, insertion of `++i;`, deletion of `--`).
- A path header `--- X` **not** immediately followed by a path header `+++ Y` is a body line: deletion of the content `-- X`. A path header `+++ Y` **not** immediately preceded by `--- X` is a body line: insertion of the content `++ Y`.
- A consecutive pair `--- X` / `+++ Y` is a **block start**, except under the **body-pair rule**: the pair is two body lines (deletion of `-- X`, insertion of `++ Y`) when the line immediately after `+++ Y` has a first character of ` ` (space), `-`, `+`, or starts with `...`, and is not itself a path header, a metadata keyword line, or a hunk header. A **blank line**, a sentinel, a hunk header, a diff command line, a metadata keyword line, a fence, or end of document after `+++ Y` means the pair is a genuine header. The rule is decidable with two lines of lookahead at the `---` line. It applies only to a pair that is still inside a body: a pair that follows a trailing comment run (§4.1 BODY) is a block start. When the body-pair rule fires the implementation MUST emit **W401** naming the line, because a generator that forgot a hunk header after `+++` produces exactly the same shape (in that case the next block's body lines are mis-parsed and the error surfaces later as E410 in the wrong block; the W401 text MUST mention this possibility).
- *Informative:* the shape arises rarely in practice. `git diff` of a change to a `-- comment` line in SQL, Lua or Haskell emits `--- old comment` followed by `+-- new comment`, which is not a pair (`+--` is not a path header). A real pair appears only when a `-- X` line is deleted **and** a line starting with `++ ` is inserted directly after it, or when a generator forgot `@@`. The residual ambiguous shape is such a pair as the last two lines of a hunk, followed by a blank line or a header; a generator that needs it MUST append a context line after the pair or split the edit into two hunks.

| Prefix | Role | In anchor pattern | Notes |
|--------|------|-------------------|-------|
| ` ` | Context | **Yes** | Not changed |
| *(blank line)* | Context (empty line) | **Yes** | Equivalent to ` ` with empty content; see §3.1 "Blank line" |
| `-` | Deletion | **Yes** | Deleted on application |
| `+` | Insertion | **No** | Inserted in body order relative to neighboring anchor elements (§8.3) |
| `...` | Boundary marker | **Yes** | Not a line, but a "seam" between boundaries; trailing whitespace allowed |
| `\ ` | Sentinel (`\ No newline at end of file`) | **No** | Lexeme is backslash + space; which side it follows is recorded (§3.1 "Body lines"), then the line is dropped; decides the final terminator when the hunk reaches the end of file (§1.3); not a body line; does not affect trailing-blank stripping |
| `#` (trailing run before the next block / end) | Comment | **No** | Ends the body; ignored (§3.1 "Comment") |
| `\` + other | — | — | **E401** (e.g. an unprefixed LaTeX line `\section{…}`) |
| `#` (followed by a body line or hunk header) | — | — | **E401**: comments are not allowed inside a hunk body (§3.1 "Comment") |

**Clarification on line prefixes:**
Line prefix in hunk body is **exactly one character** in the first position (` `, `-`, `+`), defining line type; everything after this character is line content. Boundary marker `...` is a special case: three dots **from the first position**, recognized as a single unit for designating deleted block boundary.

**Writing file lines that start with special characters (informative):** a file line is always written with its prefix in front of it, whatever it starts with:

| File line | As context | As deletion | As insertion |
|-----------|------------|-------------|--------------|
| `# comment` | ` # comment` | `-# comment` | `+# comment` |
| `-- note` | ` -- note` | `--- note` *(body line, see rule above)* | `+-- note` |
| `++i;` | ` ++i;` | `-++i;` | `+++i;` *(body line: no space after `+++`)* |
| `...` | ` ...` | `-...` | `+...` |
| `@@` | ` @@` | `-@@` | `+@@` |
| `++ x` (with space) | ` ++ x` | `-++ x` | `+++ x` *(path header lexeme! see body-pair rule)* |
| `- item` (Markdown list) | ` - item` | `-- item` | `+- item` |
| `\section{…}` | ` \section{…}` | `-\section{…}` | `+\section{…}` |
| *(empty)* | ` ` or blank *(a blank as the last body line is stripped; in BOF/EOF/create hunks only `+` is valid)* | `-` | `+` |
| *(whitespace only, 4 spaces)* | ` ` + 4 spaces (5 spaces) | `-` + 4 spaces | `+` + 4 spaces |
| *(tab-indented)* | ` <tab>code` | `-<tab>code` | `+<tab>code` |

**What a forgotten prefix does (informative):** a file line written without its prefix is a loud error when it starts with `#`, a letter, a tab, a backslash not followed by a space (E401), with `@@` (E403 or a spurious hunk header), or is `...` next to a non-`-` line (E512). It is **not** an error when the file line starts with `+` (it becomes an insertion and duplicates content), with `-` (it becomes a deletion), with a space (it becomes a shorter context line), or is `...` between two `-` lines (it becomes a wildcard). Generators MUST therefore prefix every line, and hosts SHOULD run with `--check` first.

Examples:
- `-- text` = prefix `-` (deletion) + content `- text`
- `++ code` = prefix `+` (insertion) + content `+ code`
- `  data` = prefix ` ` (context) + content ` data`

**Prohibited:**
- A first character that is not ` `, `-`, `+`, the sentinel lexeme `\ `, the start of `...`, or an empty line → **E401**. This includes tab, `#`, backtick (outside the closing-fence case of §4.1), a backslash followed by anything other than a space, and letters. Note that a line starting with a space *is* a context line; `  +bar` is the context line ` +bar`, and an implementation cannot detect that a prefix was intended.

> **Removed in v1.1:** E402 (blank line inside hunk body). Blank lines are now empty-context lines. The code E402 is reserved and MUST NOT be reused.

**Hunk with no changes:** a hunk whose body contains anchor elements but no `+` or `-` lines is valid and is a no-op after successful matching (the cursor still advances). The implementation MUST emit **W412**; under `--strict` it is an error, because a generator that forgot its `-` prefixes produces exactly this shape.

### 7.3. Boundary Blocks (Extension)

Boundary blocks allow deleting a range of lines between two markers:

**Syntax:** `-boundary1` `...` `-boundary2` [`...` `-boundary3`...]

**Rules:**
- The `...` markers split the anchor pattern into **segments**: a segment is the maximal run of consecutive anchor elements between two `...` markers, or before the first / after the last marker. Every anchor element of the hunk belongs to exactly one segment, including context lines before the first `-` line and after the last one. `+` lines may be interleaved anywhere and belong to no segment.
- The anchor element immediately **before** a `...` and the one immediately **after** it ("nearest anchor element on either side") MUST be `-` lines.
- `...` marker designates "everything between"
- **Matching (normative):** the first segment is matched as in §8.2. Each following segment is matched **as a unit** at the first position after the end of the previous segment's match where **every** element of the segment matches consecutively; the `...` captures the lines in between. Once a segment has matched, it is never re-matched at a later position (no backtracking across segments). If a segment matches nowhere after the previous one, the hunk fails with **E410**, and the diagnostic MUST name the segment and the position where the previous segment ended.
- Everything from the start of the first segment's match to the end of the last segment's match is deleted or kept according to §8.3 (lines captured by `...` are dropped; `-` lines are dropped; context lines are kept)
- New lines are inserted at the position implied by the output-sequence rule of §8.3

*Consequence (informative):* because a segment includes the context lines that follow its `-` lines, writing `-    return x` / ` after` as the last segment makes the matcher skip an early `    return x` that is not followed by `after`. Writing `-    return x` alone stops at the **first** `    return x`, which may be an early return inside the function.

**Generator guidance (informative):** the **last** segment SHOULD contain at least one context line after its final `-` line (middle segments cannot: E512 requires them to end with a `-` line), or the `-` lines of every segment SHOULD be unique after the start of the block.

**W511 (normative):** after a boundary block has matched, for every segment after the first that ends with a `-` line (i.e. has no trailing context), the implementation MUST test whether that segment would also match as a unit at any start position from the line after the end of its chosen match to the end of file; if so it MUST emit **W511** naming the segment, the chosen position and the first later position. Under `--strict` this is an error. *Rationale:* an early `return` inside a long function matches the bare segment `-    return result` first and silently deletes only part of the function; a window shorter than the file would miss it. The warning makes generators either add a context line after the last `-` line or make the segment unique.

**Best candidate for E410 in a boundary block:** the diagnostic reports the first segment's earliest match position and the first segment after it that failed to match anywhere after that position (§8.6).

**Prohibited (in order of precedence):**
- `...` at the beginning or end of block (no anchor element before/after it in the hunk) → **E511**
- Two `...` in a row without an anchor element between them → **E510**
- The nearest anchor element on either side of `...` is not a `-` line → **E512**

**Example:**

File content:
```
line1
// START
old content
more old content
// END
line6
```

Patch:
```diff
--- file.txt
+++ file.txt
@@
-// START
...
-// END
+// NEW SECTION
+new content
```

Result:
```
line1
// NEW SECTION
new content
line6
```

---

## 8. Matching and Application Algorithm

### 8.1. Algorithm Overview

1. **Parse phase:** run the state machine of §4.1 over the whole document; parse global options, headers, and hunk bodies; perform all parse-time checks (E1xx–E4xx parse codes, E5xx, header checks of §6.3–§6.4). All parse errors of the document are collected and reported together; a document with any parse error is not applied.
2. **Match phase:** for each block in document order, against the in-memory file-system state produced by the previous blocks: determine the operation, check file-system preconditions (E6xx), match and apply hunks in memory (§8.2–§8.3). Stop at the first failing block.
3. **Write phase:** only if every block succeeded and `--check` is not set, write all results to the file system (§8.6).

### 8.2. Position Search

1. For **each** hunk, an `anchor pattern` is formed.

2. **Search cursor** (all positions are 0-based line indexes in the file **as it currently is**):
   - Initialized to 0 (file start) before the first hunk of diff block; the line delta (§3.1) is initialized to 0
   - Anchor pattern search starts from current cursor position
   - After successful hunk application, cursor = `start + len(output sequence)` (the first line after the replaced region); delta += `len(output sequence) − len(anchor block)`
   - Between diff blocks, cursor and delta reset to 0

   *Example:* file `a`,`b`; hunk 1 ` a` / `+a`; hunk 2 ` a` / `+y`. After hunk 1 the file is `a`,`a`,`b` and the cursor is 2 (new coordinates), so hunk 2 finds no `a` after the cursor and, since `a` exists before it, reports **E413**. (With old coordinates the cursor would be 1 and hunk 2 would silently match the line just inserted.)

2a. **Search start (scope).** Let `S` be the search start of the hunk. Without scope text (§7.1 form 4), `S = cursor`. With scope text, `S` is the smallest line index `p ≥ cursor` whose content contains the scope text as a substring (under the whitespace rules of §1.3 and the active `--ignore-*` options). If no such line exists from the cursor to the end of file → **E418** "scope line not found". The E418 diagnostic MUST report the scope text and the cursor, MUST state whether a line containing the scope text exists before the cursor (hunk order), and SHOULD suggest `@@ BOF`/`@@ EOF` when the scope text equals `bof` or `eof` ignoring case. If more than one line from the cursor to the end of file contains the scope text, the implementation MUST emit **W418** listing all such positions and the one used (the first). In steps 5–8, `S` replaces the cursor as the lower bound of the candidate search (a candidate may start at `S` itself); the search cursor and the line delta are not affected by scope text. A match at a position `p` with `cursor ≤ p < S` is not reported when a candidate `≥ S` exists; when none exists it is reported in steps 7 and 8 as "anchor lies above the scope line", a third classification beside the two of step 7. W413 continues to apply to `p < cursor`. Under `--apply-all-matches` (§8.4) the first search starts at `S` and later searches continue from the cursor.

3. **Special cases:**
   - `@@ BOF`: anchor block absent; `start` = 0; cursor after application = number of inserted lines
   - `@@ EOF`: anchor block absent; `start` = number of lines in the file; cursor after application = end of file
   - **Boundary blocks**: anchor block end — position after the last line matching the last anchor pattern element (including all lines captured by boundary wildcard `...`)

4. When matching anchor pattern with file content:
   - **Regular lines** — require exact sequential match (considering active `--ignore-*` options)
   - **Boundary markers** `...` — split the pattern into **segments** (§7.3):
     * The first segment is matched as a unit at the candidate position
     * Each following segment is matched as a unit at the first position after the end of the previous segment's match; the `...` captures the lines in between, **any number including zero**
     * No backtracking across segments (§7.3)
     * On application, captured lines and `-` lines are dropped, context lines are kept (§8.3)
     * `--ignore-*` options apply to the segment comparison, not to the captured lines

5. **Complete** sequential match of entire `anchor pattern` is required, computed at **levels**:

   **Levels.** Candidates (step 6) are computed at the first of the following levels that yields at least one candidate at or after `S`: (a) the comparison of §1.3 with the active `--ignore-*` options; (b) with `--indent-shift`, the re-indentation rule below; (c) with `--lenient`, `--ignore-space-change` comparison. Steps 6–8 use the candidates and the comparison of that level only. If no level yields a candidate → **E410** (or **E413**, step 7), with the diagnostic computed at level (a). On a level-(b) match the implementation MUST emit **W415**; on a level-(c) match **W416**.

   **Re-indentation (level b).** A line's *indent* is its maximal leading run of SP/TAB; its *rest* is the remainder. A start position `p` is a candidate at level (b) when, for every anchor element `i` matched to file line `F_i`, the rests are equal under the level-(a) comparison, and the pairs (indent of element `i` → indent of `F_i`), taken over all anchor elements whose rest is non-empty, form a function `σ` (equal anchor indents always pair with equal file indents) that is not the identity. Each `+` line is written with its indent replaced by `σ(indent)` when its indent is in the domain of `σ`. Otherwise, if `σ` is a single **prefix substitution** — removing from every pair its longest common suffix yields the same `(X, Y)` with `X ≠ Y`, and every domain indent starts with `X` — and the `+` line's indent starts with `X`, then `X` is replaced by `Y`. Otherwise `p` is **not** a candidate at level (b). Blank and whitespace-only lines take no part in `σ` and are not re-indented; lines captured by `...` are never re-indented. W415 names the hunk, the position and every pair of `σ`. If level (b) fails everywhere only because of a `+` line outside the domain, the E410 diagnostic MUST say so and name that line. *Informative:* mixed tabs and spaces inside one hunk make `σ` a non-function and are refused; a `+` line deeper than any anchor line is accepted only under a pure depth error (`X → Y`), not under a tab/space conversion; an anchor with no leading whitespace at all (flush-left patch) has `σ = {"" → Q}` and every `+` line gets `Q` prepended.

   **Best candidate for E410.** The start position `≥ S` at which the longest prefix of the anchor pattern matches at level (a); if the first anchor element matches nowhere, the position whose line has the smallest Levenshtein distance to the first anchor element's content (ties → earliest), and the diagnostic additionally sets the flag *no line matched exactly*. For a boundary block, the first segment's earliest match and the first segment after it that failed; the file line "compared against" for that segment is the line at the position where the segment was tried, i.e. the first line after the end of the previous segment's match (§7.3).

   **`--ignore-blank-lines` and the anchor.** A blank context element removed from the pattern by this option ends the run of `+` lines "directly following" the anchor element before it (§8.3), so insertions after the removed blank are placed after the skipped file line. An anchor pattern that becomes **empty** after the removal (a hunk whose only anchor elements are blank lines) has no position → **E410** with the hint that `--ignore-blank-lines` removed every anchor element.

   **E410 difference classification.** Always computed, also when no line matched exactly (then against the Levenshtein-best line), so that a one-line anchor with wrong indentation still receives the indentation hint. Let `L`/`R` be the indent and rest of the failing anchor element and of the compared file line, both after trailing-whitespace removal. If `R_a = R_f`: *tabs versus spaces* when `L_a` and `L_f` are not both composed of the same single character kind; otherwise *leading whitespace only*. Else, if the two lines are equal after removing all whitespace (§3.4): *internal whitespace*. Else: *other*. The first applicable class is reported (§8.6).

   **Coordinates of match-phase diagnostics.** All positions reported by E410, E413, E414, E418 and by W410–W418 and W511 refer to the file **as it was when the hunk was matched**, i.e. after the previous hunks of the block were applied and before this hunk is applied (1-based in the result, §8.6). The applied range of a hunk refers to the file after that hunk.

   **Already applied (no candidate).** When no level yields a candidate, the implementation MUST additionally test whether the hunk's **applied pattern** (the output sequence of §8.3: context, blank and `+` lines in body order, `-` lines and `...` omitted) matches at level (a) exactly once from `S`. If so, the E410 diagnostic MUST state "hunk appears to be already applied at line N"; with `--skip-applied` (§5.2) the hunk is instead skipped with **W414** and the cursor moves to the line after that match. This test is performed **before** the hunk-order search of step 7, so a re-applied hunk is reported as already applied, not as E413.

   **Already present (candidate found).** For a hunk that has a candidate and contains **no `-` line** (a pure insertion), the implementation MUST test whether the hunk's applied pattern also matches **aligned on the candidate**: the applied pattern's first anchor element is placed at the candidate position, so when `k` `+` lines precede the first anchor element (the insertion-before shape of §2.3) the pattern starts `k` lines above the candidate; the comparison is made at the level the candidate was found at. If it matches, the insertion is already present there and applying the hunk would duplicate it. The implementation MUST emit **W417** "insertion already present at the match position" and, under `--strict`, treat it as an error; with `--skip-applied` the hunk is skipped with **W414** instead. The test is performed before the order check of step 8, so under `--strict` a re-applied document is reported as re-applied, not as a hunk-order problem; under `--apply-all-matches` (§8.4) it is performed for every occurrence, and with `--skip-applied` that occurrence is skipped. *Rationale (informative):* a pure insertion's anchor still matches after the patch has been applied, so re-applying a document duplicates its insertions without any error; on real data this check caught every such case and produced no false positive on first applications.

6. **Uniqueness (ambiguity check):** a **candidate** is a start position `p ≥ S` at which the whole anchor pattern matches at the current level (for patterns containing `...`, with the segment rule of §7.3 applied from `p`). The implementation MUST count **all** candidates, including candidates that overlap one another (file `}`,`}`,`}` with anchor ` }`,` }` has two candidates, 0 and 1; file `A`,`X`,`A`,`B` with `-A`/`...`/`-B` has two candidates, 0 and 2). If the count is greater than one, the rules below apply **in this order of precedence**:
   1. with `--apply-all-matches`: the non-overlapping matches are applied left to right (§8.4); steps 7 and 8 do not apply;
   2. if the hunk header is a **qualifying unified header**: let `expected = a − 1 + delta` (the old-range start converted to the current file's 0-based coordinates with the line delta of §3.1). The candidate closest to `expected` is used (on a tie, the earlier one) and the implementation MUST emit **W410** listing all candidate positions and the one chosen. A unified header `@@ -a[,m] +b[,n] @@` **qualifies** when the body contains no `...` and its counts are consistent with the body as written: an omitted count means 1 (unified-diff convention); for the same integer `t'` with `0 ≤ t' ≤ t`, where `t` is the number of trailing blank lines stripped by §3.1, `m` must equal the number of context, blank and `-` lines of the body plus `t'`, and `n` must equal the number of context, blank and `+` lines plus `t'` (trailing blank lines beyond `t'` are separators between blocks and are ignored). Counting uses the body as written, before any `--ignore-blank-lines` removal. *Informative:* for hunks of one or two lines the count check passes trivially, so a hand-written header still steers an ambiguous short anchor; W410 is mandatory and `--strict` is the defense;
   3. with `--first-match`: the earliest candidate is used;
   4. otherwise → **E414**. The diagnostic MUST list the line numbers of all candidates (§8.6), so that the generator can add context or a scope header to disambiguate.

   *Example (delta):* original file `start`,`}`,`mid`,`}`; hunk 1 `@@ -1 +1,4 @@` with body ` start` / `+a` / `+b` / `+c` (m = 1, n = 4: qualifies); hunk 2 `@@ -4 +7 @@` with body `-}` / `+)` (m = n = 1: qualifies). After hunk 1, delta = 3 and the braces are at current lines 4 and 6 (0-based). `expected = 4 − 1 + 3 = 6` → the second brace is chosen, as `git apply` would. Without the delta the first brace (current line 4) would have been chosen. The same headers written `@@ -1,1 +1,4 @@` / `@@ -4,1 +7,1 @@` qualify as well.

   *Rationale (informative):* short anchors (`}`, `return`, `end`) frequently match an earlier, unrelated place. For hand-written and LLM-written patches a loud error is strictly better than a silent edit in the wrong function. For `git diff` output the numeric hint resolves the ambiguity without a new option, and the count check (`m`, `n` consistent with the body) separates genuine `git diff` headers, whose counts are always right, from headers written from memory, whose counts rarely are. LLM generators are advised **not** to emit numeric ranges at all.

7. **Hunk order:** if no candidate exists from `S` to the end of file, but the anchor pattern matches (at level (a)) at some start position `p < S` — **E413** instead of E410. The implementation MUST perform this search (§9.1 requires E413 and W413). The diagnostic MUST classify the earliest such `p`: **inside the applied range of the previous hunk** of this block (the generator repeated the previous hunk's trailing lines as this hunk's leading context; fix: merge the hunks or drop the shared lines), **before** it (the hunks are in the wrong order; fix: reorder), or **above the scope line** (`cursor ≤ p < S`; fix: check the scope text). Not applicable under `--apply-all-matches`.

8. **Suspicious order (W413):** if exactly one candidate exists from `S` to the end of file **and** the anchor pattern also matches at some `p < cursor`, the hunk is applied at the candidate, and the implementation MUST emit **W413** naming both positions. Matches with `cursor ≤ p < S` (skipped by a scope header) do not trigger W413: skipping them is the purpose of the scope, and the scope line position is reported in the hunk result instead (§8.6). Editing the second of two identical places in order is legitimate, but a generator that emitted its hunks in the wrong order produces exactly this shape; under `--strict` W413 is an error, and the applied-range report of §8.6 lets the generator verify where the edit landed. Not applicable under `--apply-all-matches`.

### 8.3. Change Application in Anchor Block

**Normative rule.** The anchor block found in §8.2 is replaced by the **output sequence** of the hunk body, built by walking the body top-to-bottom:

| Body element | Contribution to output sequence |
|--------------|---------------------------------|
| ` ` context line / blank line | the matched file line, unchanged (the original file line, not the patch line, so `--ignore-*` never alters content) |
| `-` deletion line | nothing |
| `...` boundary marker | nothing (all lines captured by the wildcard are dropped) |
| `+` insertion line | the line content after the prefix |
| `\` sentinel | nothing (removed by the parser before this step) |

**Interaction with `--ignore-blank-lines` and other `--ignore-*` options:** a file line that was skipped during matching because of `--ignore-blank-lines` (§5.1; the other options never skip whole lines) lies inside the anchor block but corresponds to no body element. Such lines are emitted **unchanged**, immediately after the contribution of the anchor element that matched the file line preceding them **and after any `+` lines that directly follow that anchor element in the body** (so ` a` / `+c` / ` b` on file `a`,``,`b` gives `a`,`c`,``,`b`: the insertion stays attached to the line it follows). A file line is deleted only when it was matched by a `-` line; blank context elements removed from the pattern by `--ignore-blank-lines` contribute nothing. `--ignore-*` therefore never deletes or alters a file line that the body did not explicitly delete.

This is exactly the semantics of unified diff. The position of every insertion is implied by its place in the body:

- `+` lines **after** a context line are inserted after that line;
- `+` lines **after** a deletion block (or boundary block) take the place of the deleted lines;
- `+` lines **before** the first anchor element are inserted immediately before the matched anchor block (insertion before a line);
- `+` lines between a context line and a deletion line, or between two deletion blocks, follow the same rule: output order = body order.

**Examples (informative):**

```diff
@@
+new first line
 existing line
```
→ `new first line` is inserted immediately before `existing line`.

```diff
@@
 keep
-old A
+new A
 keep too
-old B
```
→ `old A` becomes `new A`, `old B` is removed, both `keep` lines unchanged.

**`@@ BOF` / `@@ EOF`:** the body consists of `+` lines only (§7.1); the output sequence is inserted at the beginning / appended at the end of the file. There is no anchor block.

**Error E412 (unbound insertion):** a hunk with header `@@`, a unified header, or a scope header whose body contains `+` lines and **no** anchor element at all (no context, no blank, no deletion, no `...`), in a block that is not a create block (§6.4.5). Such a hunk has no position in the file: a scope header only narrows the search, it does not provide one. E412 is a parse-time error and therefore precedes E418. The generator should use `@@ BOF`, `@@ EOF`, or add a context line; when the scope text is `bof`/`eof` ignoring case the message SHOULD suggest the uppercase form.

**Informative summary of v1.0 wording (retained for readers of v1.0):**
- a) deletion blocks: simple deletions remove the listed lines; boundary deletions remove everything from the first boundary to the last, inclusive;
- b) insertion blocks: inserted at the place implied by body order (after context, instead of a deletion, before the first anchor, or at BOF/EOF);
- c) context lines: remain unchanged and serve only for positioning.

### 8.4. `--apply-all-matches`

**Restriction:** option is allowed only for diff blocks containing **exactly one hunk**. With multiple hunks — error **E304**.

**Algorithm:**
1. Search for the first anchor pattern occurrence starts from position 0
2. After applying changes, cursor moves to line immediately after processed anchor block
3. Search for next occurrence of same anchor pattern continues from new cursor position
4. Process repeats until end of file

**Example:**
```
File (one token per line): A B C A B D
Hunk body:                 -A / -B / +X
Result:                    X C X D   (both occurrences replaced)
```

**Rationale:** With multiple hunks, ambiguity arises — where should the cursor be for the second hunk after multiple applications of the first? Separation into individual diff blocks eliminates ambiguity.

**Interaction with §8.2 steps 6–8:** under `--apply-all-matches` multiple matches are the expected case, so the ambiguity check of step 6 and the order checks of steps 7 and 8 (E413, W413) are skipped; the loop ends when no candidate exists after the cursor. Zero matches in the first iteration is still **E410**. Overlapping candidates are resolved left to right: after a match is applied, the next search starts at the new cursor, so a candidate that started inside the applied region is not applied. With a scope header the first search starts at `S` (§8.2 step 2a) and later searches continue from the cursor.

### 8.5. Sequential Application Rule

1. Between **diff blocks** — strictly in document order.
2. Between **hunks** — strictly top-to-bottom within block.
3. **Within file** — search is conducted from current cursor position to end; hunks **must** be arranged in ascending position order in file.
4. Two diff blocks MAY target the same path; the second sees the result of the first (including a rename or create performed by an earlier block).

### 8.6. Atomicity, Check Mode, and Result Reporting

**Atomicity (normative):**
- An implementation MUST apply a document **all-or-nothing**: every block is parsed, validated, and matched against the file system and file contents **in memory**, in document order (§8.1), and nothing is written, created, renamed, or deleted until every block has succeeded. If any block fails, the file system is left unchanged and the result reports the failure.
- Blocks that depend on earlier blocks (same path edited twice, edit after rename) are evaluated against the in-memory state produced by the earlier blocks.
- The write phase SHOULD be made as atomic as the platform allows (write to temporary files, then rename). An implementation interrupted during the write phase (a crash, a permission error on the third file) SHOULD report which files were written; this cannot be exercised by a conformance test and is a requirement on the host's error handling, not on the format.
- *Rationale (informative):* with partial application, a generator that resends a corrected patch re-applies the insertion-only hunks of the blocks that had succeeded, duplicating lines without any error.

**Check mode:** with `--check` (§5.2) or an equivalent host switch, the same procedure is run up to and including matching, and the full result is produced, but the write phase is skipped. In check mode the match phase SHOULD **not** stop at the first failing block: it continues with the remaining blocks against the in-memory state as if the failed block had been skipped, so that every block and hunk receives a status (`checked` or `failed`) and a preview interface can show all problems at once. Within a failing block, the hunks after the failing hunk are matched as well, as if the failed hunk had been skipped (the cursor is not moved by it); the block's in-memory result is discarded. In check mode the status `matched` is not used: every hunk that matched is `checked`, including the hunks of a block whose other hunk failed. The overall status is still `failed` when any block failed. The result field `checkedWithSkips` (Appendix B) MUST be present in every check-mode result; it is `true` when a block failed in the match phase and the later statuses were computed with it skipped.

**Phases and stopping (normative):** the parse phase (§8.1 step 1) processes the whole document and reports **all** parse errors; a document with any parse error has overall status `failed`, no block is matched, blocks with parse errors are `failed` and all other blocks are `not-attempted`. The match phase processes blocks in order and **stops at the first failing block**: that block is `failed`, blocks before it are `matched`, blocks after it are `not-attempted`. When every block succeeds, blocks are `applied` (or `checked` under `--check`). Under `--strict`, see §5.2. **When the overall status is `failed`, no block has status `applied` and nothing was written; the generator MUST resend the whole corrected document.**

**Hunk statuses:** `applied` / `checked` / `matched` / `failed` / `not-attempted` / `skipped`. In a block that succeeds, every hunk has the block's status, except hunks that were skipped (`skipped`). In a block that fails in the match phase, hunks before the failing hunk are `matched`, the failing hunk is `failed`, later hunks `not-attempted` (in check mode: `checked` or `failed`, see "Check mode" above); in an earlier block of a failed document all hunks are `matched`. In a block with a parse error every hunk is `not-attempted` except the hunks that carry an error, which are `failed`. `skipped` applies to the hunks of delete blocks (§6.4.5), of W601/W603 blocks, and to hunks skipped under `--skip-applied` (W414).

**Result (normative minimum):** an implementation MUST make the following available to its caller for every application attempt, in a machine-readable form (a JSON schema is recommended, see Appendix B when it exists). All line numbers and ordinals in the result are **1-based** (editor convention); the 0-based cursor and positions of §8.2 are internal.
- overall status: `applied`, `checked`, or `failed`;
- for each block: ordinal, source path, target path, operation, status (`applied` / `checked` / `matched` / `skipped` / `failed` / `not-attempted`), and warnings;
- for each hunk: ordinal within the block, status, on success the **applied range** in the new file (1-based first line and number of lines of the output sequence), the **level** at which it matched (`exact`, `indent-shift`, `lenient`), and for a hunk with scope text the 1-based position of the scope line used;
- for each error and warning: code, message, and location: the **patch line number** and the offending line for parse-phase codes (E100–E102, E104, E2xx, E3xx including E310, E400–E404, E411, E412, E415–E417, E5xx, E604–E608, W200, W300, W301, W401); the **block ordinal** for file-system codes (E103, E600–E603, E611, W601–W603, and W412 for a hunk-less block); the **block and hunk ordinals** for matching codes (E410, E413, E414, E418, W410, W412 for a hunk, W413–W419, W511). **W302** (no diff block) has no location.

**Diagnostic content for matching errors (normative):**
- **E410** MUST report: the hunk's first anchor element (text), the search start, and the **best candidate** as defined in §8.2 step 5: its start line, the index and text of the first anchor element that failed there, and the file line it was compared against. The two lines MUST be rendered with whitespace made visible: `·` for space, `→` for tab, a marker for trailing whitespace, and **escape sequences for every non-ASCII whitespace or invisible code point** (NBSP, zero-width characters, a BOM inside a line), which would otherwise be indistinguishable from spaces. The message MUST state the difference classification of §8.2 step 5 (leading whitespace only / tabs versus spaces / internal whitespace / other); for the first two classes it MUST add that the hunk's `+` lines are probably indented the same way and that the generator should re-read the file region and resend the whole hunk with the file's indentation. It MUST state whether the anchor would match at the best candidate under `--ignore-all-space`, and whether the hunk appears to be already applied (§8.2 step 5). When the failing element's content starts with `-- ` the message SHOULD add that a `+++` path header or a hunk header may be missing. For a boundary block, the message MUST name the segment that failed and the line where the previous segment ended (§7.3). The message SHOULD include the two file lines before and after the best candidate.
- **E413** MUST report the earliest position before the search start where the pattern matches, the cursor, and the classification of §8.2 step 7 (shared context with the previous hunk / wrong order / above the scope line).
- **E414** MUST report every candidate position, and SHOULD report for each candidate the file line before and after the match (whitespace made visible), so that the generator can pick distinguishing context without re-reading the file.
- **E418** MUST report the scope text and the cursor, and whether the text occurs before the cursor.
- **E404** and **E608** raised on a block whose header is a `--- `/`+++ ` pair that ended a hunk body SHOULD add the hint that a hunk header may be missing in the next block or that the pair may be a `-- `/`++ ` comment edit (§7.2). **E608** MUST show both paths after prefix removal.
- **W410**, **W413** and **W418** MUST report all positions involved and the one chosen; W410 SHOULD include the neighboring lines of each candidate as for E414. **W415** MUST report the re-indentation table `σ`. **W416** and **W414** MUST report the position used.
- Parse errors MUST report the patch line number and the offending line, with whitespace made visible as for E410 (a tab in the first position must be recognizable as such). **Which line is "offending":** for a code raised by one specific line (E1xx on a path, E20x on a header line, E30x on an option line, E40x on a body line, E5xx on a `...` marker, E209/E604–E606/E608 on the operation or path line that conflicts), that line; for a hunk-level code with no single line (E412, E416, E417, E411 raised at the end of a hunk) the hunk header line; for a block-level code with no single line (E210, E404 for a hunk-less block) the block start line; for a conflict between two options (E305, E307) the later of the two lines.

---

## 9. Conformance

### 9.1. Conformance Levels

**Minimal conformant parser** MUST:
- Parse `diff --git`, `---/+++` headers
- Parse all hunk header forms of §7.1 (unified, `@@`, `@@ BOF`, `@@ EOF`, `@@ <scope>`) and reject others (E403)
- Recognize ` `, `-`, `+` prefixes, blank lines, the `...` marker and the `\ ` sentinel in hunk body
- Implement the parser state machine (§4.1) including comments and fence tolerance (W300), the lexemes of §3.1 and §7.1, and the body-pair rule (§7.2)
- Accept blank lines in a hunk body as empty context (§3.1 "Blank line") and drop sentinel lines
- Parse the `--lite-diff` version marker (E308) and block-level `option` lines (§5.5)
- Report parse errors E100-E102, E104, E200-E207, E209, E210, E300-E302, E304-E310, E400, E401, E403, E404, E411, E412, E415-E417, E5xx, E604-E606, E608 and warnings W200 (MAY), W300, W302, W401

**Minimal conformant applicator** MUST:
- Apply changes according to §8 algorithm, including the output-sequence rule of §8.3 and the target file line model of §1.3 (trailing whitespace never significant)
- Implement the search cursor mechanism with the coordinates and line delta of §8.2, and the scope search start of step 2a
- Implement boundary blocks with segment matching and the W511 check (§7.3)
- Perform the ambiguity check with overlapping candidates (E414) and honor the unified-header tie-breaker with count validation and line delta (§8.2 step 6)
- Search before the search start for E413 and W413 (§8.2 steps 7–8)
- Handle create/delete/rename/copy operations, including hunks in create/delete blocks (§6.4.5), and skip binary and non-regular modes (W601, W603)
- Apply documents atomically with the phases of §8.1 and produce the result and diagnostics of §8.6
- Report applicability errors E103, E410, E413, E414, E418, E600-E603, E611 and warnings W410, W412, W413, W417, W418, W419, W511, W601-W603

**Full conformance** additionally requires support for:
- Global options `--ignore-space-change`, `--ignore-blank-lines`, `--ignore-all-space`, `--apply-all-matches`, `--first-match`, `--auto-rename`, `--strip`, `--skip-applied` (MAY); `--check`, `--strict` (SHOULD)
- Opt-in matching levels `--indent-shift` (W415) and `--lenient` (W416) (MAY)
- Named roots `@root` (MAY)
- The machine-readable result of Appendix B (SHOULD)

### 9.2. Interoperability Notes

| Feature | lite-diff | git apply | Notes |
|---------|-----------|-----------|-------|
| Numeric ranges in `@@` | Tie-breaker only | Used for validation | lite-diff finds position by content; old-range start resolves ambiguous matches |
| Blank line in hunk body | Empty context | Empty context | Same behavior |
| `+` before first context line | Insert before | Insert before | Same behavior |
| Ambiguous anchor (`@@` without numbers) | E414 | n/a (numbers required) | Use more context, a unified header, or `--first-match` |
| Rename without `rename from/to` | E608 | Not a rename (paths must match) | lite-diff v1.0 inferred rename; v1.1 does not |
| Spaces in paths | Unquoted accepted in `---`/`+++`; `diff --git` split heuristically (E204 if ambiguous) | Unquoted | Same behavior |
| `--- `/`+++ ` pair inside a hunk (`-- ` comment languages) | Body-pair rule + W401 | Resolved by line counts | Same result for `git diff` output |
| `\ No newline at end of file` | Honored when the hunk reaches the end of file (§1.3) | Honored | Same behavior; a sentinel elsewhere is W419 |
| Trailing whitespace in context | Never significant | Significant (unless `--ignore-space-at-eol`) | lite-diff v1.1 default (§1.3) |
| `@@ <scope>` header | Search start | `@@ … @@ section` ignored | lite-diff extension |
| `/dev/null` with `diff --git a/x b/x` | Accepted | Accepted | Same behavior |
| Mnemonic prefixes `i/` `w/` `c/` `o/` | Stripped | Stripped | Same behavior |
| Symlink / submodule modes | Skipped, W603 | Applied | lite-diff limitation |
| `format-patch` / `log -p` envelope | E306 | Accepted by `git am` / `git apply` | Out of scope (§1.2) |
| `-U0` (zero context) | E412 | Applied by line numbers | Out of scope (§1.2) |
| Multi-file GNU `diff -ru` | Accepted (`diff ` block start) | Accepted | Same behavior |
| Missing `@@` line | E404 | Error ("corrupt patch") | Same behavior (v1.0 silently did nothing) |
| `@@ BOF` / `@@ EOF` | Supported | Not recognized | lite-diff extension |
| Boundary `...` | Supported | Not recognized | lite-diff extension |
| Comments `#` (preamble, headers) | Ignored | May cause errors | lite-diff extension |
| Comments `#` inside hunk body | E401 | Error | Same behavior (v1.0 allowed them) |
| Atomic application | Required | `git apply` is atomic by default | Same behavior |
| `--ignore-*` in file | Supported | Not recognized | lite-diff extension |

---

## 10. Errors and Warnings (Reference)

Codes are organized by logical ranges for diagnostic convenience.

**Domain by hundreds:** 1xx PATH, 2xx HEADER, 3xx GLOBAL, 4xx HUNK, 5xx BOUNDARY, 6xx FILE_OP.

**Phase by tens (informative):** x0x codes are generally parse-time (syntax/format) and x1x codes applicability (matching or file-system semantics). The phase of each code is given normatively by §8.6 ("location"); codes added in v1.1 (E210, E411–E417) do not all follow the by-tens convention.

### Range E1xx: Path Security (PATH)

| Code | Description |
|------|-------------|
| **E100** | Absolute path prohibited (a Windows drive on every platform; on Windows any path containing `:`, §6.3.5) |
| **E101** | Traversal detected (`..`, `.`) |
| **E102** | Glob pattern detected in path |
| **E103** | Path leads to symbolic link |
| **E104** | Path has fewer components than `--strip N` removes |

### Range E2xx: Header Parsing (HEADER)

| Code | Description |
|------|-------------|
| **E200** | Unpaired or duplicate path header (`---` without `+++`, `+++` without `---`, or a second `---`/`+++` in one header) |
| ~~**E201**~~ | *Removed in v1.1* (the `<prefix>:` scheme no longer exists). Code reserved. |
| **E202** | Path conflict between sources (`diff --git` vs `---/+++`) |
| **E203** | Invalid escape sequence |
| **E204** | `diff --git` paths with spaces cannot be split unambiguously (quote them); unquoted spaces are otherwise accepted (§6.3.4) |
| **E205** | Header `diff --git` not from first position |
| **E206** | Header `---` or `+++` not from first position |
| **E207** | Header metadata (index, mode, rename, copy, etc.) not from first position |
| **E209** | `rename`/`copy` header paths differ from `---`/`+++` (or from `diff --git` when `---`/`+++` are absent) |
| **E210** | Block has no path source (no `diff --git`, no `---`/`+++`, no `rename`/`copy` pair) |
| **E214** | Missing workspace indication in multi-root without `--default-root` |
| **E215** | Unknown workspace root in multi-root workspace |

### Range E3xx: Global Options (GLOBAL)

| Code | Description |
|------|-------------|
| **E300** | Option-like line in a header (global options are allowed only in the preamble; use `option <name>` for a block-level option) |
| **E301** | Unknown option name (global `--name` or block-level `option name`), or invalid option value |
| **E302** | Global option `--` not from first position |
| ~~**E303**~~ | *Removed in v1.1* (undefinable: a line not starting with `#` is not a comment). Code reserved. |
| **E304** | `--apply-all-matches` used for diff block with multiple hunks |
| **E305** | `--apply-all-matches` and `--first-match` used together |
| **E306** | Unexpected text outside the diff: before the first block (prose, mail headers, a lone `---`, a second fence, a hunk header) or after the closing fence |
| **E307** | `--lenient` together with `--strict` (globally or per block) |
| **E308** | Unsupported `--lite-diff` version |
| **E309** | Option not allowed at block level (`lite-diff`, `strict`, `check`, `auto-rename`, `strip`, `eol`, `default-root`) |
| **E310** | Patch document is not valid UTF-8, or starts with a BOM (§1.3); reported at line 1 for a BOM, at the line of the first invalid byte otherwise; parsing continues (with the invalid bytes replaced) so that the document's other parse errors are reported too |

### Range E4xx: Hunks and Context (HUNK)

| Code | Description |
|------|-------------|
| **E400** | Hunk header `@@` not from first position |
| **E401** | Invalid line in hunk body (the line must start with ` `, `-`, `+`, the sentinel lexeme `\ `, or `...`, or be blank; `#`, tab, letters, backticks and `\` followed by anything but a space are invalid) |
| ~~**E402**~~ | *Removed in v1.1* (blank line inside hunk body is now empty context). Code reserved. |
| **E403** | Malformed hunk header (a line starting with `@@` that is not `@@`, `@@ BOF`, `@@ EOF`, or a unified header; includes `@@@`) |
| **E404** | Body line before any hunk header in a block, or edit block without hunks and without `old mode`/`new mode` (missing `@@`?) |
| **E410** | No `anchor pattern` match found from the search start to end of file at any enabled level |
| **E411** | Invalid content after `@@ BOF/EOF` (only `+` allowed) |
| **E412** | Hunk has `+` lines but no anchor element (no context/blank/deletion/`...`) and is not in a create block (also raised for `-U0` output) |
| **E413** | No match after the search start, but anchor pattern matches before it (hunk order violated, shared context, or anchor above the scope line) |
| **E414** | Ambiguous anchor: pattern matches at more than one start position (overlapping candidates included) after the search start and no tie-breaker applies |
| **E415** | Invalid hunk in create/delete block (non-`+` lines or multiple hunks in create; `+` lines in delete) |
| **E416** | Empty hunk body (no body lines after removing sentinels and trailing blanks) |
| **E417** | `@@ BOF` not the first hunk of its block, or `@@ EOF` not the last |
| **E418** | Scope text of a `@@ <scope>` header not found from the cursor to the end of file |

### Range E5xx: Boundary Blocks (BOUNDARY)

| Code | Description |
|------|-------------|
| **E510** | Multiple `...` in a row in boundary block (no anchor element between them) |
| **E511** | `...` at beginning or end of boundary block (takes precedence over E512) |
| **E512** | Nearest anchor element on either side of `...` is not a `-` line |

### Range E6xx: File Operations (FILE_OP)

| Code | Description |
|------|-------------|
| **E600** | Creating file, but target already exists |
| **E601** | Cannot delete: file not found or not a regular file |
| **E602** | Target path already exists for `rename/copy` |
| **E603** | Source file missing for `rename/copy` |
| **E604** | Indicators (operation headers and/or `/dev/null` paths) imply more than one operation |
| **E605** | `rename from` without `rename to`, or vice versa, or a duplicate of either in one header |
| **E606** | `copy from` without `copy to`, or vice versa, or a duplicate of either in one header |
| **E608** | `---` and `+++` paths differ without `rename`/`copy` header (implicit rename is not allowed) |
| **E611** | File not found for regular edit |

### Warnings

| Code | Description |
|------|-------------|
| **W200** | Unrecognized line in a header, ignored |
| **W300** | Markdown fence line before the first block, ignored (a matching closing fence after the last block is then accepted) |
| **W301** | `--default-root` in a single-root environment, ignored |
| **W302** | Document contains no diff block (status `applied`, nothing written) |
| **W401** | `--- `/`+++ ` pair inside a hunk body was treated as two body lines (body-pair rule, §7.2); may indicate a missing hunk header in the next block |
| **W410** | Ambiguous anchor resolved using the unified header line hint (all candidates and the chosen one are reported) |
| **W412** | Hunk contains no `+`/`-` lines, or mode-change block contains no hunks (no-op); mandatory, error under `--strict` |
| **W413** | Anchor also matches before the cursor; applied at the match after the cursor (possible hunk order mistake) |
| **W414** | Hunk appears already applied and was skipped (`--skip-applied`) |
| **W415** | Hunk applied with re-indentation (`--indent-shift`); the `σ` table is reported; not escalated by `--strict` |
| **W416** | Hunk matched at the `--lenient` level (whitespace amount ignored); `+` lines written as given |
| **W417** | Pure-insertion hunk whose result is already present at the match position (would duplicate); error under `--strict`, skipped under `--skip-applied` |
| **W419** | `\ No newline at end of file` in a hunk that does not reach the end of file, or an old-side sentinel that contradicts the file; ignored |
| **W418** | Scope text occurs more than once from the cursor; the first occurrence was used |
| **W511** | A boundary segment without trailing context would also have matched later in the file (mandatory check, §7.3) |
| **W601** | Binary file skipped (`Binary files differ`/`GIT binary patch`) |
| **W602** | Hunk content in a delete block does not match the file being deleted (file deleted anyway) |
| **W603** | Block skipped: symbolic link or submodule mode (`120000` / `160000`) |

---

## 11. Compatibility and Edge Cases

- Some git metadata is intentionally ignored (`index`, `old/new mode`, `similarity/dissimilarity index`).
- Timestamps in `---/+++` are ignored; only the path part matters.
- In `rename/copy`, EOL and BOM are inherited from source; for "create", EOL is chosen by editor/environment policy.
- Code points, Unicode escaping, and slashes are normalized.
- Two diff blocks MAY target the same path within one document; they are applied in document order, and the second block sees the result of the first (including a rename performed by an earlier block). See §8.5.
- End-of-file behavior (unterminated last line, `@@ EOF`, BOM with `@@ BOF`, empty files) follows the target file line model of §1.3.
- Files with mixed line endings: the EOL of the **first** line terminator in the file is the file's convention; existing lines keep their own terminators, inserted lines use the convention.

---

## 12. Changes from v1.0

All changes are driven by one requirement: a patch written by an LLM agent must either apply as intended or fail with a clear error. Each entry below states the v1.1 rule in its final form. The **Effect** column says whether a change **widens** the set of accepted documents, **narrows** it (a document that v1.0 accepted is now rejected or reported), **adds** a feature or a requirement on implementations, or only **clarifies** what v1.0 left open or contradictory. Before publication the text was validated against the conformance corpus (`tests/`), the reference implementation (`reference/`), the recorded sessions of a v1.0 implementation and the `git diff` history of a live repository.

§12.1 is what a user of v1.0 must check; §12.2 is the complete list by area; §12.3 lists the diagnostic codes that were added or removed.

### 12.1 Migration: v1.0 patches that may stop applying

- **Implicit rename.** A `---`/`+++` pair with differing paths and no `rename from`/`rename to` is **E608** (item 25). Add the rename lines, or set `--auto-rename`.
- **Ambiguous anchor.** A hunk whose anchor matches more than once after the cursor is **E414**; v1.0 took the first match (item 15). Add one or two lines of context, give the hunk a unified header with the correct old-range start, or set `--first-match`.
- **Unified header counts.** A header whose counts disagree with the body no longer breaks a tie (item 15), and a qualifying header now decides before `--first-match`. Fix the counts or add context.
- **`#` comments inside hunk bodies.** A `#` line followed by more body lines is **E401** (item 5). A comment run directly before the next block, before the closing fence or at the end of the document is accepted. Move other comments between the block's `---`/`+++` pair and its first `@@`, into the preamble, or remove them.
- **Text after `@@`.** `@@ <text>` is a **scope header** (item 17): the text is searched for in the file (**E418** if absent); a remainder starting with `-`, `+` or `@` is **E403**. A v1.0 patch that used `@@ <text>` as a free comment now fails unless the text happens to occur in the file.
- **Other hunk header forms.** Anything that is not one of the five forms of §7.1 (`@@@`, a malformed range) is **E403** (item 2).
- **Blocks without `@@`.** A `---`/`+++` pair followed by body lines and no hunk header is **E404** (item 4); v1.0 silently did nothing. Add the `@@` line.
- **Re-applied insertions.** A pure-insertion hunk whose lines are already present at its position is **W417**, an error under `--strict`, skipped under `--skip-applied` (item 20); v1.0 inserted the lines a second time.
- **No-op hunks and `...` with text.** A hunk with no `+`/`-` lines is **W412** (error under `--strict`); a `...` marker followed by text is **E401** (item 7).
- **`<prefix>:` paths.** The v1.0 `<prefix>:` root syntax is removed; a colon is an ordinary character on POSIX and **E100** on Windows (item 29). Use the host's root setting or a declared multi-root environment instead.
- **`--strict`.** Hosts for agents are recommended to enable it (item 21); W401, W410, W412, W413, W417 and W511 then stop the document.
- **Everything else** that was valid in v1.0 remains valid and applies with the same result; trailing whitespace in context lines is still accepted and is no longer required to match (item 12), and the final newline of a file is decided exactly as `git apply` decides it (item 23).

### 12.2 Changes by area

**Document structure and parsing** (§1.2, §3, §4, §5, §7.2)

| # | Change | Sections | Effect |
|---|--------|----------|--------|
| 1 | Normative parser state machine (PREAMBLE, HEADER, BODY, TRAILER) replaces the prose block rules; a block starts at any `diff ` line, metadata keyword line or `---`/`+++` pair; a pair after a completed `rename`/`copy` header belongs to it when its `---` path equals `from`; unknown header lines are W200; a `GIT binary patch` payload is skipped; indented lexemes in PREAMBLE/HEADER map to E205/E206/E207/E302/E400 | §3.1, §4.1, §6.1 | clarifies (v1.0 read a `git diff` header as three blocks) |
| 2 | Lexemes fixed: a path header is `---`/`+++` followed by a space or tab; five hunk header forms (§7.1), anything else E403; `...` may carry trailing whitespace; the sentinel lexeme is `\ ` (backslash, space), other `\…` body lines are E401 | §3.1, §7.1, §7.2 | **narrows** (`@@@`, malformed ranges) |
| 3 | Preamble: one Markdown fence is tolerated (W300), options may follow it; any other text is E306; the TRAILER state accepts the closing fence; `format-patch` / `log -p` envelopes and `-U0` output are out of scope | §1.2, §4.1, §5 | clarifies |
| 4 | **E404**: body lines before any hunk header, and an edit block with neither hunks nor mode lines, are errors | §4.1, §6.4.1, §10 | **narrows** (silent no-op → error) |
| 5 | `#` comments are not allowed inside a hunk body (E401, E303 removed); a **trailing comment run** directly before the next block, the closing fence or the end of the document ends the body; a run before a `---`/`+++` pair makes the pair a block start | §3.1, §4.1, §7.2 | **narrows** (silent context loss → error) |
| 6 | Body-pair rule: a `--- `/`+++ ` pair that is still inside a body and is followed by a body line (` `, `-`, `+`, `...`) is two body lines, with a mandatory W401; `git diff` of `--`-comment languages parses | §7.2 | clarifies |
| 7 | Body processing order: structure, then sentinels, then trailing blank lines; a tab-first body line is E401; an empty hunk body is E416; a hunk with no `+`/`-` lines is a no-op reported as W412 (mandatory, error under `--strict`); `...` followed by text is E401 | §3.1, §7.2 | clarifies / **narrows** |
| 8 | Option grammar: version marker `--lite-diff <ver>` (unknown version E308, malformed value E301); block-level `option <name>` lines (§5.5, E309) with `off` for boolean options at both levels; an invalid option value is E301; conflicting options are E305; `--default-root` without a value is E301; `--strip N` (E104 when a path has no component left) | §3.1, §4, §5, §5.3, §5.5 | adds |
| 9 | Patch encoding: a document that is not valid UTF-8 or starts with a BOM is E310 (parsing continues on the decoded text); an empty document is W302; escapes in quoted paths decode to UTF-8 bytes | §1.3, §6.3.4, §10 | adds |
| 10 | Compatibility profile `--lite-diff 1.0`: one engine; implies `--auto-rename` and `--first-match`, never `--strict`, drops `#` lines inside bodies; v1.0 behavior only where v1.0 applied to a definite place (E404, E412 and scope headers stay); implied options never raise E305 | §5 | adds |

**Hunk bodies and matching** (§2.3, §5.1, §5.2, §7.1, §7.3, §8)

| # | Change | Sections | Effect |
|---|--------|----------|--------|
| 11 | A blank line inside a hunk body is the context of an empty line (E402 removed); a blank anchor also matches a whitespace-only file line | §3.1, §7.2, §10 | widens |
| 12 | Trailing whitespace is never significant in matching; `--ignore-space-at-eol` is accepted as a no-op; leading whitespace stays significant by default (rationale in §1.2) | §1.2, §1.3, §3.1, §5.1 | widens |
| 13 | Opt-in matching levels: `--indent-shift` (a uniform re-indentation `σ`, applied to the `+` lines, W415) and `--lenient` (per-hunk fallback to `--ignore-space-change`, W416; E307 together with `--strict`) | §5.2, §8.2 step 5, §8.6 | adds |
| 14 | `+` lines may precede the first anchor element (insertion before a line); §8.3 is the unified-diff output-sequence rule; E412 only for a hunk with no anchor element at all, including scope headers, and precedes E418 | §2.3, §7.1, §8.3 | widens |
| 15 | Ambiguity: candidates are counted overlapping; more than one match after the cursor is **E414** unless a qualifying unified header (both counts present and consistent with the body, omitted count = 1, trailing blanks stripped by §3.1 allowed) picks one (**W410**), or `--first-match` or `--apply-all-matches` is set; the header decides before `--first-match`; E414 and W410 report the neighboring lines | §1.1, §5.2, §7.1, §8.2, §8.4, §10 | **narrows** (silent wrong-place edit → error) |
| 16 | The search cursor advances in new-file coordinates with a line delta; **E413** (anchor found only before the cursor) is distinguished from E410 and from shared context; **W413** for a suspicious order; `@@ BOF` must be first and `@@ EOF` last (E417); `--apply-all-matches` skips the order checks | §3.1, §7.1, §8.2 | clarifies |
| 17 | **Scope header** `@@ <scope>` (§7.1 form 4): the search starts at the first line containing the text; E418 if none, W418 if several; the text may not start with whitespace; the scope line is reported in the result | §7.1, §8.2 step 2a, §8.4, §8.6 | adds / **narrows** (free text after `@@` is no longer ignored) |
| 18 | Boundary blocks: the anchor pattern is split into **segments** by `...`; each segment after the first is matched as a unit at its first full match, without backtracking; "either side" of a marker is the nearest anchor element; E511 precedes E512, E415 precedes E411/E412; **W511** is a mandatory check whose window extends to the end of file; E410 names the failing segment and the line it was compared with | §6.4.5, §7.3, §8.2 | clarifies |
| 19 | `--ignore-blank-lines` defined: blank and whitespace-only file lines are skipped, blank context is removed from the pattern, `-` lines are never skipped, skipped lines are emitted unchanged, an anchor block starts and ends on matched lines, the position of `+` lines relative to skipped blanks and the end of a run are defined | §5.1, §8.2, §8.3 | clarifies |
| 20 | **Already present** (W417): a pure-insertion hunk whose result is already at its match position, tested on the first anchor element, at the candidate's level, before the E413 search, for every occurrence under `--apply-all-matches`; error under `--strict`, skipped under `--skip-applied` (W414); an E410 must carry the "already applied" hint | §5.2, §8.2 | **narrows** (silent duplication → warning or error) |
| 21 | **`--strict`**: W401, W410, W412, W413, W417 and W511 become errors; recommended default for agent hosts; W410 is not escalated when the chosen candidate starts exactly at the header's line (ordinary `git diff` output) | §5.2 | adds |

**Line model and end of file** (§1.3, §6.4.5, §11)

| # | Change | Sections | Effect |
|---|--------|----------|--------|
| 22 | Target file model: bytes with per-line terminators; unchanged lines keep theirs (mixed EOL preserved); inserted lines receive the file's EOL convention, or the **default EOL**: LF unless `--eol crlf`; a UTF-8 BOM is preserved whatever happens to line 1 | §1.1, §1.3, §5.3, §11 | clarifies |
| 23 | **Final terminator follows `git apply`**: a hunk reaches the end of file when its anchor block includes the last line or it is `@@ EOF`; the new side of the last such hunk decides through the sentinel; otherwise the last line keeps its state; a created file follows the same new-side rule | §1.1, §1.3, §6.4.5, §9.2 | clarifies |
| 24 | Sentinel side defined once: after a `-` line or a non-final context line it asserts the old side (a mismatch with the file is W419); after a `+` line it decides the new side; after the final context line it is both; a sentinel in a hunk that does not reach the end of file, or in a misplaced position, is W419 and has no effect | §1.3, §3.1, §6.4.5 | clarifies |

**File operations and paths** (§2.4, §6)

| # | Change | Sections | Effect |
|---|--------|----------|--------|
| 25 | Rename requires explicit `rename from`/`rename to`; differing `---`/`+++` paths without them are **E608** (reported with the stripped paths); `--auto-rename` restores v1.0; `rename`/`copy` paths are never prefix-stripped; E209 when they disagree with `---`/`+++`; a duplicate `rename from` is E605, duplicate `copy` lines are E606 (the first repeating line is the offending one) | §2.4, §5.2, §6.3.2, §6.4.2, §10 | **narrows** (silent file move → error) |
| 26 | Source and target paths defined once, in one processing order (unquote → prefix → normalize → security); `/dev/null` on either side wins over `diff --git` and is exempt from E201/E202; E210 for a block with no path source; E200 for an unpaired path header; E604 uses `/dev/null` as an indicator | §6.3, §6.4.2 | clarifies / widens |
| 27 | Prefixes: git's six letters `a b c i o w` followed by `/` are stripped from `diff --git` and `---`/`+++` paths only; any other single letter is a directory; GNU `diff -r` output is supported when the paths are equal after prefix removal, `old/`/`new/` layouts are E608 | §1.1, §6.3.5 | widens |
| 28 | Path spelling: unquoted paths may contain spaces as git writes them (E204 only for an unsplittable `diff --git` line); trailing whitespace is removed from every unquoted path; quoted paths follow git's escapes | §1.1, §6.3.4, §9.2 | widens |
| 29 | The v1.0 `<prefix>:` root form is removed (E201 reserved); a colon is an ordinary character on POSIX; on Windows any `:` in a path is **E100** (drive-relative path or NTFS alternate data stream); a drive letter followed by a slash is E100 everywhere; named roots (`@root/`) exist only in a declared multi-root environment, and `--default-root` in a single-root environment is ignored with W301 | §5.3, §6.3.3, §6.3.5, §10 | **narrows** |
| 30 | Create blocks: zero or one `+`-only hunk under any header form, any other line or a second hunk is E415; delete blocks: hunk content is not required to match (W602, the file is deleted anyway), a binary delete is applied without W601; an edit block with mode lines and no hunks is a no-op; several blocks per path are allowed; symlink and submodule modes and `Subproject commit` updates are skipped (W603) | §2.4, §6.2, §6.4.1, §6.4.5, §7.2, §10 | clarifies |
| 31 | Validation order per block (W603 → header → path security → hunk structure → file system → matching); the parse phase reports every failure, the match phase stops at the first; E103 belongs to the match phase; the `operation` of a skipped block comes from its header; emptied directories SHOULD be removed and are not listed under `written` | §6.4.3, §6.4.4 | clarifies |

**Result and diagnostics** (§5.2, §8.1, §8.6, §10, Appendix B)

| # | Change | Sections | Effect |
|---|--------|----------|--------|
| 32 | Atomic application is mandatory (all or nothing per document; atomicity against a crash SHOULD); three phases: parse the whole document, match block by block stopping at the first failure, write; a failed document has no `applied` block | §5.2, §8.1, §8.6 | adds requirements |
| 33 | **`--check`** (dry run) continues past a failing block so that every hunk receives a status (`checked` or `failed`, never `matched`); `checkedWithSkips` is always present in the result | §5.2, §8.6, B | adds |
| 34 | Normative minimum of the result: block statuses (`applied`, `matched`, `checked`, `skipped`, `failed`, `not-attempted`), hunk statuses, `appliedRange`, matching `level`, scope line, `cursor`/`searchStart`, `written`, `writeError`; all numbers 1-based; positions of match-phase diagnostics refer to the file as it was when the hunk was matched; the offending line and the location are defined per code class; Appendix B gives the JSON Schema (SHOULD) | §8.6, §10, B | adds requirements |
| 35 | E410 diagnosis: the best candidate with a difference classification (indentation, tabs vs spaces, trailing whitespace, other) is always computed, `noLineMatched` is a separate flag; whitespace is rendered visibly and invisible code points as escapes (MUST); the `--ignore-all-space` and "already applied" hints are MUST | §8.2 step 5, §8.6 | adds requirements |
| 36 | Informative material: Appendix A for patch generators (rules on one screen, file-line-to-patch-line table, error-to-fix table, complete example); §9 conformance lists and interoperability table; the §7.2 table of file lines that start with special characters | §7.2, §9, Appendix A | informative |

### 12.3 Diagnostic codes

Added in v1.1: E104, E209, E210, E305, E306, E307, E308, E309, E310, E403, E404, E414, E415, E416, E417, E418, E608, W200, W300, W301, W302, W401, W410, W412, W413, W414, W415, W416, W417, W418, W419, W511, W602, W603.
Removed: E303 (comments inside bodies are E401), E402 (blank lines are context). Reserved, no longer raised: E201.

**Not addressed in this version.** Candidates for a later version, if implementations ask for them: per-block `strip`, a `--indent-shift` variant for tab/space conversion with `+` lines deeper than the anchor, and localized sentinel text beyond the `\ ` lexeme.

---

## Appendix A. Writing lite-diff (for patch generators)

This appendix restates, for the author of a patch (typically an LLM coding agent), the rules of the normative text that matter when **writing** a lite-diff document. It is derived from §1–§8; where it is less precise than the main text, the main text prevails. Hosts that drive an LLM with lite-diff SHOULD use §A.1 verbatim as prompt material instead of writing their own summary.

### A.1. Rules on one screen

```
LITE-DIFF v1.1 — RULES FOR WRITING A PATCH
Structure
 1 Output only the patch, no prose. If you use a ```diff fence, it is the very first line and the closing
   fence the very last; everything, including options, goes inside. First line of the patch: `--lite-diff 1.1`.
   Text before the first block is E306; text after the last hunk is read as hunk lines (E401) unless it
   follows the closing fence.
 2 Block header = `--- <path>` directly followed by `+++ <path>`, both at column 0, a space after the dashes.
   Paths are relative to the workspace, no leading `/` or `./`. A leading `a/` `b/` `c/` `i/` `o/` `w/` is
   stripped as a git prefix: a real top-level directory with one of those names is written `a/b/file`.
   Spaces in paths are fine unquoted.
 3 Edit: same path twice. Create: `--- /dev/null`. Delete: `+++ /dev/null` (no hunk needed).
   Rename: `rename from OLD` / `rename to NEW` (no `a/` `b/` here), then `--- OLD` / `+++ NEW`. Different
   paths without rename lines = E608. A blank line between blocks is fine; `diff --git` before a block is fine.
 4 Every block that changes content needs a hunk header: `@@`, `@@ BOF`, `@@ EOF`, or `@@ <scope>` where
   <scope> is a distinctive fragment of a line at or above the edit, usually the enclosing definition,
   e.g. `@@ def parse(`; the anchor is then searched only from the first line containing it. <scope> may
   not start with `-`, `+` or `@`. Never write `@@ -a,b +c,d @@` from memory. Body lines before any `@@` = E404.
Body lines (column 0; the prefix is exactly one character)
 5 ` `+line = context (must equal the file line, indentation included; trailing spaces never matter);
   `-`+line = delete; `+`+line = insert; an empty line = context of an empty or whitespace-only file line.
   Empty lines at the END of a hunk are dropped: end a hunk on a non-empty context line instead.
   Every hunk needs at least one `+` or `-` line; a context-only hunk is a no-op (W412).
 6 Always prefix, whatever the file line starts with: ` # x`  `-# x`  ` ---`  `--- note` (deletes `-- note`)
   `+++i;`  ` ...`  ` @@`  ` \section`  ` <tab>code`. A line is E401 when its first character is not space,
   `-`, `+`, or empty, and it is not `...` or `\ No newline at end of file` (so `#`, tab, letters, backticks).
   `\ No newline at end of file` after the last `+` line of a hunk that reaches the end of the file makes the
   file end without a newline, exactly as in git; anywhere else it is ignored with a warning.
 7 Create block: at most one hunk, `+` lines only (anything else E415). `@@ BOF` (first hunk only) /
   `@@ EOF` (last hunk only): `+` lines only; an empty line to insert is `+` alone — a bare blank there is E411.
 8 Insert before a line: `+` lines before the context line. After: after it. Replace: `-old` then `+new`.
   `+` lines with no context/deletion at all = E412 (use BOF/EOF or add a context line).
 9 Range delete: `-first line` / `...` / `-last line` [then `+replacement`]. `...` at column 0, nothing after
   it; the lines next to `...` must be `-` lines. The part after `...` is matched at its first occurrence
   AFTER the first part, so it must be unique to the end of the file or be followed by a context line
   (otherwise W511, and an early match deletes only part of the range).
10 Never end a hunk with `--- X` directly followed by `+++ Y` as body lines; add a context line after them.
11 `#` comments go in the preamble, between `+++` and `@@`, or directly before the next block (a run of `#`
   lines right before `---`/`+++`, `diff --git`, or the end of the patch). A `#` line followed by hunk lines is E401.
Matching
12 Position is found by content, searching forward from a cursor that moves past each applied hunk. Hunks in
   a block must be in file order and must not repeat the previous hunk's lines. Out of order = E413.
13 The anchor (context + `-` lines) must match exactly once from the cursor (or the scope line) to EOF.
   Twice or more = E414: add context or a `@@ <scope>`. Once after the cursor but also before it = W413:
   check the applied range (first line + count) reported per hunk.
14 Indentation is significant; tab-indented files need ` <tab>`. Avoid whitespace-only context lines (start
   the anchor below them). Options affect matching only: `+` lines are inserted exactly as written. Host
   options, one per line at the top: `--ignore-space-change` `--ignore-all-space` `--ignore-blank-lines`
   `--first-match` `--apply-all-matches` `--auto-rename` `--check` `--strict` `--indent-shift` `--lenient`
   `--skip-applied` `--strip N`. Assume `--strict`: W401/W410/W412/W413/W416/W418/W511 fail the patch.
15 `@@ EOF` lines are terminated; an unterminated last line gets a terminator first. `@@ BOF` inserts after
   a BOM.
Result
16 A document applies all-or-nothing: if any block fails, nothing is written. After an error, fix and
   resend the WHOLE document.
17 Errors give code + patch line (syntax) or block/hunk ordinal (matching), 1-based. E410 names the first
   anchor line that failed and the file line it was compared with, whitespace visible, and says whether the
   difference is indentation; E413 says "shared context" (merge hunks) or "wrong order" (reorder);
   E414 lists every candidate; W410/W413/W418 list all positions and the one chosen.
```

### A.2. File line → patch line

| File line starts with | Context | Delete | Insert | Note |
|-----------------------|---------|--------|--------|------|
| ordinary text | ` text` | `-text` | `+text` | |
| `#` | ` # x` | `-# x` | `+# x` | unprefixed `# x` is E401 |
| `-- note` | ` -- note` | `--- note` | `+-- note` | `--- note` alone is a body line (§7.2) |
| `++ x` | ` ++ x` | `-++ x` | `+++ x` | `+++ x` is a path-header lexeme; see rule 10 |
| `++i;` | ` ++i;` | `-++i;` | `+++i;` | no space after `+++`, so a body line |
| `---` (Markdown rule) | ` ---` | `----` | `+---` | |
| `- item` | ` - item` | `-- item` | `+- item` | |
| `...` | ` ...` | `-...` | `+...` | a bare `...` is the range marker |
| `@@` | ` @@` | `-@@` | `+@@` | a bare `@@` is a hunk header |
| `\section{…}` | ` \section{…}` | `-\section{…}` | `+\section{…}` | backslash followed by a space is the sentinel lexeme; `\s…` unprefixed is E401 |
| ```` ``` ```` (a fence inside a file) | ` ```` ```` ```` | `-```` ```` ```` | `+```` ```` ```` | an unprefixed fence closes the patch |
| *(empty)* | ` ` or blank | `-` | `+` | a blank as the last body line is dropped |
| *(4 spaces)* | ` ` + 4 spaces | `-` + 4 spaces | `+` + 4 spaces | |
| *(tab-indented)* | ` <tab>code` | `-<tab>code` | `+<tab>code` | a tab in column 0 is E401 |

### A.3. Error → what to change

| Code | Meaning | Fix |
|------|---------|-----|
| E306 | Text outside the patch | Remove prose; keep at most one fence pair |
| E100 / E101 | Absolute path, or `./` / `..` in a path | Remove the leading `/` or `./`; paths are workspace-relative |
| E200 / E202 / E209 | Path headers unpaired, or paths disagree between `diff --git`, `---`/`+++`, `rename from/to` | Make every path line of the block name the same file; no `a/` `b/` on rename lines |
| E204 | `diff --git` paths with spaces cannot be split | Quote both paths, or omit the `diff --git` line |
| E404 | Body lines before any `@@`, also when the first body line starts with `--` | Insert the `@@` line after `+++` |
| E608 | `---` and `+++` differ without `rename from/to` | Fix the typo, or add the rename lines |
| E403 | Bad hunk header | Use exactly `@@`, `@@ BOF`, or `@@ EOF` |
| E401 | Invalid body line | If it is a file line, add the missing prefix (space for context); if it is your explanation after the last hunk, delete it — everything after the last hunk is body |
| E306 | Text outside the patch | Remove prose before the patch or after the closing fence; put options inside the fence |
| E411 | Non-`+` line after `@@ BOF`/`@@ EOF` | Write inserted empty lines as `+`; move context edits to a `@@` hunk |
| E412 | `+` lines with no anchor | Add a context line, or use `@@ BOF`/`@@ EOF` |
| E415 | Create/delete block with the wrong body | Create: `+` lines only, one hunk; delete: no `+` lines |
| E416 | Empty hunk | Remove the `@@` or add body lines |
| E417 | `@@ BOF`/`@@ EOF` in the wrong place | BOF first, EOF last |
| E510 / E511 / E512 | `...` misplaced | `...` only between two `-` lines, never first or last |
| E410 | Anchor not found | Compare the reported anchor line with the reported file line; if the message says "leading whitespace" or "tabs versus spaces", re-read the region and fix the indentation of the whole hunk, `+` lines included; if it says "already applied", drop the hunk; for a range delete, check the segment named in the message |
| E413 | Anchor found only before the cursor | "Shared context": drop the lines repeated from the previous hunk or merge the hunks; "wrong order": reorder the hunks; "above the scope line": fix the scope text |
| E414 | Anchor matches several places | Add one or two distinctive context lines, or name the enclosing definition in a `@@ <scope>` header |
| E418 | Scope text not found from the cursor | Check the fragment's spelling and the hunk order; use a shorter fragment of the same line |
| E600 / E601 / E602 / E603 / E611 | File exists / missing for the operation | Check the path and the operation |
| W401 | A `---`/`+++` pair inside a hunk was read as body lines | If a block was intended there, add its `@@` line |
| W410 | Ambiguity resolved by the `@@` line numbers | Verify the applied range; prefer context over numbers |
| W413 | Anchor also matched before the cursor | Verify the applied range; check hunk order |
| W412 | Hunk has no `+`/`-` lines | You forgot the `-` or `+` prefixes; the hunk changed nothing |
| W415 / W416 | Hunk applied with corrected indentation / matched ignoring whitespace amount | Verify the applied range; your indentation differed from the file's |
| W418 | Scope text occurs more than once | Make the scope fragment longer |
| W511 | Range end also matches later in the file | Add a context line after the last `-` line of the range, or make the end lines unique |

### A.4. Do not

- Do not write prose around the patch, and do not nest fences.
- Do not write `@@ -a,m +b,n @@` from memory: wrong counts disable the hint, "right" counts steer an ambiguous anchor to the wrong place. Use `@@`.
- Do not anchor on a single short line (`}`, `end`, `return x`, an empty line); use two or three distinctive lines, or a `@@ <scope>` header naming the enclosing definition plus the short anchor.
- Do not write a context-only hunk: every hunk needs a `+` or `-` line.
- Do not repeat the previous hunk's last lines as the next hunk's first lines.
- Do not put `#` comments between the lines of a hunk; a comment directly before the next block or at the end of the patch is fine.
- Do not resend a patch that already applied: a pure insertion whose context still matches is reported as W417 (error under `--strict`) instead of being duplicated.
- Do not rely on trailing spaces: an empty context line is written as a blank line, an inserted empty line as `+`, and a hunk should end on a non-empty context line rather than a blank one.
- Do not put options outside the fence, and do not put a one-letter git prefix directory (`a/`, `b/`, `w/`…) in a path without doubling it.
- Do not rename by changing the path in `+++`; add `rename from`/`rename to`.
- Do not end a range delete with a `-` line that also occurs earlier inside the range without a context line after it.

### A.5. Complete example

Three blocks: an edit with two hunks (the second with a scope header), a rename with an edit, and a new file. The document is fenced as an LLM would emit it, with the version marker inside the fence.

````
```diff
--lite-diff 1.1
--- src/app.py
+++ src/app.py
@@
 import os
+import json
 import sys
@@ def main(
-    data = load()
+    data = json.loads(load())
     return data

rename from src/util.py
rename to src/utils.py
--- src/util.py
+++ src/utils.py
@@
-def load():
...
-    return raw
+def load():
+    return read_all()
 
 def save(data):

--- /dev/null
+++ src/read.py
@@
+def read_all():
+    return ""
```
````

Expected result: `app.py` gains an import and, inside `main`, a changed line; `util.py` is renamed to `utils.py` with its `load` function replaced from its `def` line through the `    return raw` line that is followed by a blank line and `def save(data):`. The two context lines after the last `-` line belong to the last segment (the interleaved `+` lines belong to no segment, §7.3), so the end of the range is unambiguous and W511 does not fire; by the output-sequence rule of §8.3 the new `load` is written **before** the kept blank line and `def save(data):`, i.e. in place of the old function. The blank context line is written as a single space so that it is not stripped as trailing. `read.py` is created with two lines and a trailing newline. The fence produces W300. If any of the three blocks fails, no file is changed and the whole document must be resent.

---

## Appendix B. Result Schema

This appendix gives the machine-readable form of the result defined in §8.6 as a JSON Schema (draft 2020-12). Implementations SHOULD produce a document valid against it; conformance test suites use the same shape for expected results. Field names are stable; implementations MAY add fields under `x-` prefixes.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://lite-diff.org/schema/result-1.1.json",
  "title": "lite-diff application result",
  "type": "object",
  "required": ["liteDiffVersion", "status", "blocks", "diagnostics"],
  "properties": {
    "liteDiffVersion": { "type": "string", "pattern": "^[0-9]+\\.[0-9]+$", "description": "Version the document was interpreted under" },
    "status": { "enum": ["applied", "checked", "failed"] },
    "options": { "type": "object", "additionalProperties": true, "description": "Effective global options" },
    "blocks": { "type": "array", "items": { "$ref": "#/$defs/block" } },
    "diagnostics": { "type": "array", "items": { "$ref": "#/$defs/diagnostic" } },
    "written": { "type": "array", "items": { "type": "string" }, "description": "File paths written, created, renamed or deleted (directories removed as emptied are not listed); empty unless status is applied" },
    "writeError": { "type": "string", "description": "Present only when the write phase failed after matching succeeded (§8.6); names the failing path and the files already written" },
    "checkedWithSkips": { "type": "boolean", "description": "Present in every check-mode result; true when a block failed in the match phase and the later statuses were computed with it skipped (§8.6)" }
  },
  "$defs": {
    "block": {
      "type": "object",
      "required": ["ordinal", "operation", "status", "hunks"],
      "properties": {
        "ordinal": { "type": "integer", "minimum": 1 },
        "source": { "type": ["string", "null"], "description": "Source path after processing, or /dev/null" },
        "target": { "type": ["string", "null"] },
        "operation": { "enum": ["edit", "create", "delete", "rename", "copy"] },
        "status": { "enum": ["applied", "checked", "matched", "skipped", "failed", "not-attempted"] },
        "options": { "type": "object", "additionalProperties": true, "description": "Effective block-level options" },
        "hunks": { "type": "array", "items": { "$ref": "#/$defs/hunk" } }
      }
    },
    "hunk": {
      "type": "object",
      "required": ["ordinal", "status"],
      "properties": {
        "ordinal": { "type": "integer", "minimum": 1 },
        "header": { "enum": ["plain", "bof", "eof", "unified", "scope"] },
        "status": { "enum": ["applied", "checked", "matched", "failed", "not-attempted", "skipped"] },
        "appliedRange": {
          "type": "object",
          "required": ["firstLine", "lineCount"],
          "properties": {
            "firstLine": { "type": "integer", "minimum": 1, "description": "1-based first line of the output sequence in the new file" },
            "lineCount": { "type": "integer", "minimum": 0 }
          }
        },
        "level": { "enum": ["exact", "indent-shift", "lenient"] },
        "scopeLine": { "type": "integer", "minimum": 1, "description": "1-based position of the scope line used (scope headers only)" }
      }
    },
    "diagnostic": {
      "type": "object",
      "required": ["code", "severity", "message"],
      "properties": {
        "code": { "type": "string", "pattern": "^[EW][0-9]{3}$" },
        "severity": { "enum": ["error", "warning"] },
        "escalated": { "type": "boolean", "description": "true when a warning was treated as an error under --strict" },
        "message": { "type": "string" },
        "patchLine": { "type": "integer", "minimum": 1, "description": "Parse-phase codes" },
        "patchText": { "type": "string", "description": "Offending patch line, whitespace made visible" },
        "block": { "type": "integer", "minimum": 1 },
        "hunk": { "type": "integer", "minimum": 1 },
        "searchStart": { "type": "integer", "minimum": 1, "description": "1-based search start S of §8.2 step 2a (E410, E413, E414, E418); equals the cursor unless a scope header moved it" },
        "cursor": { "type": "integer", "minimum": 1, "description": "1-based search cursor of §8.2 step 2" },
        "bestCandidate": {
          "type": "object",
          "description": "E410 only",
          "properties": {
            "line": { "type": "integer", "minimum": 1 },
            "failedElementIndex": { "type": "integer", "minimum": 1 },
            "anchorText": { "type": "string" },
            "fileText": { "type": "string" },
            "classification": { "enum": ["leading-whitespace", "tabs-vs-spaces", "internal-whitespace", "other"], "description": "§8.2 step 5; always one of the four classes" },
            "noLineMatched": { "type": "boolean", "description": "true when the first anchor element matched nowhere and the best candidate was chosen by edit distance" },
            "wouldMatchIgnoringAllSpace": { "type": "boolean" },
            "appearsAlreadyAppliedAt": { "type": ["integer", "null"], "minimum": 1 },
            "segment": { "type": ["integer", "null"], "minimum": 1, "description": "Boundary blocks: failing segment ordinal" },
            "context": { "type": "array", "items": { "type": "string" }, "description": "Neighboring file lines, whitespace made visible" }
          }
        },
        "candidates": {
          "type": "array",
          "description": "E414, W410, W413, W418, E413, W511: all positions involved",
          "items": {
            "type": "object",
            "required": ["line"],
            "properties": {
              "line": { "type": "integer", "minimum": 1 },
              "chosen": { "type": "boolean" },
              "before": { "type": "string" },
              "after": { "type": "string" }
            }
          }
        },
        "classification": { "enum": ["shared-context", "wrong-order", "above-scope"], "description": "E413" },
        "reindent": { "type": "array", "description": "W415: the σ table", "items": { "type": "object", "required": ["from", "to"], "properties": { "from": { "type": "string" }, "to": { "type": "string" } } } },
        "hint": { "type": "string" }
      }
    }
  }
}
```

A conformance test's `expected.json` is a subset of this document: `status`, and for each expected diagnostic at least `code`, `block`/`hunk` or `patchLine` as applicable, and any `candidates[].line`, `classification`, or `bestCandidate.line` the test asserts. Fields a test does not mention are not compared.

---

## Acknowledgments

This specification is inspired by the classic unified diff format, which has been a cornerstone of version control systems for decades. lite-diff is an independent format that extends and simplifies the original concept for modern use cases.
