# Lite-diff Specification (v1.0, December 2025)

> **lite-diff** is an independent text format for describing file changes, inspired by the classic unified diff format. This specification defines the syntax and semantics of the format.

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
- [5. Global Options (Extensions)](#5-global-options-extensions)
  - [5.1. Whitespace Matching Options](#51-whitespace-matching-options)
  - [5.2. Application Modes](#52-application-modes)
  - [5.3. Named Roots (Multi-root Support)](#53-named-roots-multi-root-support)
  - [5.4. Restrictions and Errors](#54-restrictions-and-errors)
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
- [9. Conformance](#9-conformance)
  - [9.1. Conformance Levels](#91-conformance-levels)
  - [9.2. Interoperability Notes](#92-interoperability-notes)
- [10. Errors and Warnings (Reference)](#10-errors-and-warnings-reference)
- [11. Compatibility and Edge Cases](#11-compatibility-and-edge-cases)
- [Acknowledgments](#acknowledgments)

---

## 1. Introduction

**lite-diff** is a simplified text format for describing file changes. The goal is to provide a predictable, easy-to-read, and easy-to-implement specification covering common editing scenarios (point edits, insertions at the beginning/end, file creation/deletion/renaming/copying) with minimal rules.

### 1.1. Compatibility with Unified Diff

- Standard header forms are accepted: `diff --git`, `---` / `+++`, as well as extended Git headers (some are ignored).
- Hunk headers in the format `@@ -a[,m] +b[,n] @@ [section]` are supported; numeric ranges and "section" are used only as hints and do not participate in matching.
- The **first position rule** is observed for all structural elements (see §3).
- Binary indicators (`Binary files ... differ`, `GIT binary patch`) cause the file to be skipped with a warning.
- The sentinel `\ No newline at end of file` is ignored.
- Additional simplifications and capabilities (e.g., `@@`, `@@ BOF`, `@@ EOF`, `boundary blocks`, `global options`, and `comments`) are defined as **extensions**.

### 1.2. Out of Scope

1. Conditional application constructs (`if-exists`, `if-not-exists`).
2. Variables and templates (`$VAR`, `${VAR}`).
3. Regular expressions and fuzzy search — only exact matching considering `--ignore-*`.
4. Any work with binary data — always skipped with a warning.
5. Special limits on file/line sizes — not imposed by the specification.

### 1.3. Encoding and Line Endings

**Patch file encoding:**
- lite-diff files **MUST** be encoded in **UTF-8** without BOM.

**Line splitting:**
- Lines are split by `LF` (U+000A) or `CRLF` (U+000D U+000A).
- The internal line model uses `LF`; `CR` before `LF` is stripped during parsing.
- When applying patches, line endings in inserted content follow the target file's existing convention or the environment's default policy.

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

### 2.4. Create, Delete, Rename

**Create:**
```diff
--- /dev/null
+++ new.txt
@@
+First line
+Second line
```

**Delete:**
```diff
--- old.txt
+++ /dev/null
```

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

- **Diff block** — a section from the header `diff --git` (or `---/+++` if `diff --git` is absent) to the next `diff` or end of file.

- **Global option** — a line located **before the first** diff block, starting with the prefix `--`. Affects parser/applicator behavior for the entire document.

- **Header** — the part of a diff block from its beginning to the first `@@` line. If no `@@` exists, the header extends to the next diff block or end of file.

- **Hunk** — a unit of changes: `@@` header + body.

- **Body lines:** ` ` (context), `-` (deletion), `+` (insertion), `#` (comment), and the `...` marker inside boundary blocks.

- **Anchor pattern** — a template for finding a position in the file:
  1. **Formation:** all body elements except lines with `+` or `#` prefix
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

- **Search cursor** — current position in the file from which anchor pattern search begins for the next hunk:
  - Initialized to 0 (file beginning) before processing the first hunk of a diff block
  - After applying a hunk, moves to the line following the last line of the found anchor block
  - Guarantees that hunks are applied strictly top-to-bottom through the file

- **Comment** — a line where the **first character** is `#` (mandatory condition). Comments are **completely ignored** by the parser anywhere in the document (including inside hunk body) and are **not preserved** in parsing results.

- **Blank line** — a line without any characters (only line feed). Inside the hunk body, a blank line is a line **without** any valid prefix (` ` / `-` / `+` / `#`) and not the `...` marker.
  - **Outside hunk body** (global area, header): **allowed** and **ignored**.
  - **Inside hunk body:** blank lines are **prohibited** → **E402**. See §7.2.
  - **Note:** Lines with `+`/`-`/` ` prefix **without content after the prefix** are valid lines representing insertion/deletion/context of an *empty line*; **E402 does not apply** to them.

### 3.2. First Position Rule

All structural elements of lite-diff must start from the **FIRST POSITION** of the line without any indentation:

| Element | Error Code |
|---------|------------|
| Global options `--` | **E302** |
| Comments `#` | **E303** |
| Header `diff --git` | **E205** |
| Path headers `---`/`+++` | **E206** |
| Hunk headers `@@` | **E400** |
| Metadata (index, mode, rename, copy) | **E207** |
| Body line prefixes (` `/`-`/`+`/`#`/`...`) | **E401** |

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
[Comments (# from first position)]      ◆ EXTENSION
─────────────────────────────────────────────────────────────────────
diff --git <prefix>:<path> <prefix>:<path>  ✓ PARSED (paths extracted)
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
  # comments                            ○ IGNORED
--- <prefix>:<path> [\t timestamp]      ✓ path PARSED / timestamp IGNORED
+++ <prefix>:<path> [\t timestamp]      ✓ path PARSED / timestamp IGNORED
Binary files ... differ                 ⚠ FILE SKIPPED (W601)
GIT binary patch                        ⚠ FILE SKIPPED (W601)
\ No newline at end of file             ○ IGNORED
─────────────────────────────────────────────────────────────────────
@@ -<start>[,<count>] +<start>[,<count>] @@ [section]  ✓ marker PARSED / numbers and section IGNORED
@@                                      ◆ EXTENSION (simplified format)
@@ BOF                                  ◆ EXTENSION (insert at beginning)
@@ EOF                                  ◆ EXTENSION (insert at end)
 <context line>                         ✓ USED
-<deleted line>                         ✓ USED
+<added line>                           ✓ USED
-<boundary> ... -<boundary>             ◆ EXTENSION (boundary block)
# comments (from first position)        ○ IGNORED (not saved in AST)
─────────────────────────────────────────────────────────────────────
```

> **Note:** Indentation, pseudo-lists, and alignment within the diagram are for clarity only. In a real document, **all** structural elements and lines with prefixes must start from the **FIRST POSITION** (see §3.2).

---

## 5. Global Options (Extensions)

> Applicable **only before the first** diff block. Each option on a separate line with `--` prefix, starting from the FIRST POSITION (no indentation). Duplicates are ignored.

### 5.1. Whitespace Matching Options

These options affect **matching only** — they do not modify the actual content being inserted or deleted. Line prefixes (` `, `-`, `+`, `#`, `...`) are structural markers and are **never** affected by these options.

- `--ignore-space-at-eol` — ignore trailing whitespace (SP, TAB) at end of line during matching.
- `--ignore-space-change` — ignore changes in whitespace amount (SP, TAB) in the middle of line during matching.
- `--ignore-blank-lines` — ignore blank lines during matching.
- `--ignore-all-space` — ignore all whitespace (SP, TAB) during matching (overrides others).

### 5.2. Application Modes

- `--apply-all-matches` — apply hunk to **all** occurrences of the corresponding **anchor block** in the target file. **Restriction:** allowed only for diff blocks with a single hunk → **E304**.

### 5.3. Named Roots (Multi-root Support)

For environments with multiple project roots (e.g., monorepos, multi-folder workspaces):

- `--default-root @<root-name>` — set default root for paths without explicit `@root` prefix
  - `<root-name>` must correspond to an existing root name → **E215**
  - In single-root environments, ignored with warning
  - Without `--default-root` in multi-root: paths without prefix → **E214**
  - First occurrence is used for duplicates

**Path prefix format:**
- Syntax: `@<root-name>/path/to/file`
- Prefix is part of the path and is removed during resolution

**Resolution priority (highest to lowest):**
1. Explicit prefix in path (`@frontend/src/app.js`)
2. Value from `--default-root` for paths without prefix
3. Single root in single-root environment

> **Note:** The dictionary of available roots and detection of multi-root environment are the responsibility of the host tool/environment, not the lite-diff format itself.

### 5.4. Restrictions and Errors

- Any global option format text **after** the first `diff` → **E300**.
- `--ignore-*` affects context and boundary search but **does not change** the inserted/deleted lines themselves.
- **Line prefixes are structural markers:** `--ignore-*` options apply only to line CONTENT (after prefix), not to the prefixes themselves.

---

## 6. Block Header

### 6.1. Header Boundaries

**Start:**
- If `diff --git` exists — from this line
- Otherwise — from the first metadata line before `---/+++` (rename/copy/new/deleted)
- If no metadata — from the first `---` line

**End:**
- First `@@` line
- If no `@@` exists, header extends to the start of the next diff block or end of file

### 6.2. Header Content

| Category | Elements | Processing |
|----------|----------|------------|
| **Paths** | `diff --git a/<path> b/<path>`, `--- <path>` (or `/dev/null`), `+++ <path>` (or `/dev/null`) | ✓ Extracted |
| **Operations** | `new file mode`, `deleted file mode`, `rename from/to`, `copy from/to` | ✓ Type determined |
| **Metadata** | `index`, `old/new mode`, `similarity/dissimilarity index` | ○ Ignored |
| **Binary** | `Binary files ... differ`, `GIT binary patch` | ⚠ W601 |

### 6.3. Path Extraction

#### 6.3.1. Required Elements and Path Extraction

- **Path sources:** `diff --git <src> <dst>` **AND/OR** `---/+++` pair
- **Extraction priority:**
  - If `diff --git` exists — paths extracted from it
  - If no `diff --git` — paths extracted from `---/+++`
  - Both sources present — must be consistent (see 6.3.2)
- **Special path `/dev/null`:**
  - In `---` means file creation
  - In `+++` means file deletion

#### 6.3.2. Path Consistency

- `a/<path>` from `diff --git` must match path from `---`
- `b/<path>` from `diff --git` must match path from `+++`
- With `rename/copy`: operation paths must match `---/+++`
- **Validation errors:**
  - Path mismatch → **E202**
  - Multiple `---/+++` → **E200**

#### 6.3.3. Allowed / Prohibited

- **Allowed:** relative workspace paths; slashes `/` and `\` (normalized); dots in names (`.env`, `config.local.json`).
- **Prohibited:**
  - absolute paths (**E100**)
  - path traversal (`..`, `.`) — **E101**
  - glob patterns (`*`, `**`, `?`) — **E102**
  - symbolic links — **E103** (path validation checks file type in filesystem; symlinks are rejected)

#### 6.3.4. Quoting and Escape Sequences

- C-style escapes allowed: `\"`, `\\`, `\n`, `\r`, `\t`, `\xHH`, `\NNN`.
  - Octal escape sequences `\NNN` valid only in range `\000`-`\377` (0-255 decimal).
  - Values `\400`-`\777` are invalid → **E203**.
- Paths with spaces **MUST** be quoted; escapes are **decoded** inside quotes.
- Path with spaces without quotes → **E204**.

#### 6.3.5. Prefixes `a/` `b/` and `<prefix>:`

- Standard `a/` and `b/`, general form `<prefix>:` (everything before `:`), and without prefixes are supported.
- Prefixes are removed during path extraction.
- Mixing prefix schemes in one header is prohibited → **E201**.

#### 6.3.6. Normalization

- Slashes normalized to OS format (`/` on Unix, `\` on Windows)
- Unicode normalized to **NFC** (e.g., é as U+00E9, not e + U+0301)
- Paths always relative to workspace root

### 6.4. Operation Definition

#### 6.4.1. Operation Types

| Operation | Indicators | Checks | Errors |
|-----------|------------|--------|--------|
| **Create** | `new file mode` or `--- /dev/null` | File does not exist | **E600** (if file EXISTS) |
| **Delete** | `deleted file mode` or `+++ /dev/null` | File exists and is regular | **E601** (if not found or not regular file) |
| **Rename** | `rename from/to` or different paths in `---/+++` | Source exists, target does not | **E603** (source NOT exists) / **E602** (target EXISTS) |
| **Copy** | `copy from/to` | Source exists, target does not | **E603** (source NOT exists) / **E602** (target EXISTS) |
| **Edit** | Other cases | File exists | **E611** (file NOT exists) |

#### 6.4.2. Operation Validation Rules

- **Mutual exclusion:** only one operation per header → **E604**
- **Incomplete operations:** `from` without `to` → **E605** (rename) / **E606** (copy)
- **Auto-detect rename:** if no explicit operations but paths in `---/+++` differ (and neither is `/dev/null`) → treat as rename

#### 6.4.3. Application Order for Rename/Copy with Hunks

For `rename` and `copy` operations that include hunks:

1. Hunks are matched against the **source** file content as it exists **before** the operation.
2. After all hunks are applied to the source content in memory, the resulting content is written to the **target** path.
3. For `rename`: source file is removed after successful write to target.
4. For `copy`: source file remains unchanged.
5. If source does not exist → **E603**; if target already exists → **E602**.
6. EOL/BOM handling follows §1.3 and §11 (inherited from source).

---

## 7. Hunks (Core + Extensions)

### 7.1. Hunk Headers

- **Unified:** `@@ -<start>[,<count>] +<start>[,<count>] @@ [section]` — numbers and `section` are ignored during matching.
- **Simplified** (Extension): `@@`.
- **BOF/EOF** (Extension): `@@ BOF` (insert at beginning) / `@@ EOF` (insert at end). After such headers, only `+` lines and `#` comments are allowed. Any other line → **E411**.

**Note:** All hunk headers must start from the FIRST POSITION (no indentation), otherwise error **E400**.

### 7.2. Hunk Body

**Hunk body boundaries:**
- Start: line immediately after `@@` header
- End: line before next `@@` or end of diff block
- Blank lines after the last prefixed line are NOT part of hunk body

| Prefix | Role | In anchor pattern | Notes |
|--------|------|-------------------|-------|
| ` ` | Context | **Yes** | Not changed |
| `-` | Deletion | **Yes** | Deleted on application |
| `+` | Insertion | **No** | Inserted at position determined by context/deletion/BOF/EOF |
| `#` | Comment | **No** | Completely ignored, not saved in AST |
| `...` | Boundary marker | **Yes** | Not a line, but a "seam" between boundaries |

**Clarification on line prefixes:**
Line prefix in hunk body is **exactly one character** in the first position (` `, `-`, `+`, `#`), defining line type; everything after this character is line content. Boundary marker `...` is a special case: three dots **from the first position**, recognized as a single unit for designating deleted block boundary.

**Comments in hunk body:**
Lines with `#` in first position in hunk body are comments and are completely ignored by the parser. They do not participate in anchor pattern formation and do not affect change application.

Examples:
- `-- text` = prefix `-` (deletion) + content `- text`
- `++ code` = prefix `+` (insertion) + content `+ code`
- `  data` = prefix ` ` (context) + content ` data`
- `# note` = comment, completely ignored

**Prohibited:**
- Leading spaces or tabs before prefix → **E401**
- Blank lines (lines without valid prefix) → **E402**
- Lines starting with characters other than ` `, `-`, `+`, `#`, or `...` → **E401**

### 7.3. Boundary Blocks (Extension)

Boundary blocks allow deleting a range of lines between two markers:

**Syntax:** `-boundary1` `...` `-boundary2` [`...` `-boundary3`...]

**Rules:**
- Each boundary must be a `-` line
- `...` marker designates "everything between"
- Each next boundary is searched starting from the position AFTER the end of the previous found boundary
- First found match is used (non-greedy)
- Everything from the start of the first boundary to the end of the last is deleted (inclusive)
- New lines are inserted at the position of the first deleted line

**Prohibited:**
- `...` at the beginning or end of block → **E511**
- Two `...` in a row without `-` line between them → **E510**
- Absence of `-` lines on either side of `...` → **E512**

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

1. Parse global options (if any)
2. Split into blocks by `diff` headers
3. For each block:
   - Parse header
   - Determine operation (create/delete/edit/rename/copy)
   - Parse and apply hunks

### 8.2. Position Search

1. For **each** hunk, an `anchor pattern` is formed.

2. **Search cursor:**
   - Initialized to position 0 (file start) before the first hunk of diff block
   - Anchor pattern search starts from current cursor position
   - After successful hunk application, cursor moves to line following the last line of found anchor block
   - Between diff blocks, cursor resets to 0

3. **Special cases:**
   - `@@ BOF`: anchor block absent; cursor after application = number of inserted lines
   - `@@ EOF`: anchor block = end of file; cursor after application = end of file
   - **Boundary blocks**: anchor block end — position after the last line matching the last anchor pattern element (including all lines captured by boundary wildcard `...`)

4. When matching anchor pattern with file content:
   - **Regular lines** — require exact sequential match (considering active `--ignore-*` options)
   - **Boundary markers** `...` — special wildcard elements:
     * Match **any number of lines (including zero)** between boundaries
     * First boundary (line before `...`) must be found in file
     * Next boundary is searched starting from position AFTER the previous boundary end
     * On application, everything between boundaries is deleted (inclusive)
     * `--ignore-*` options apply to boundary search itself, not to wildcard

5. **Complete** sequential match of entire `anchor pattern` is required. If no match — **E410**.

6. **Hunk order:** If anchor pattern is found before cursor position (i.e., above already processed hunks) — **E413**.

### 8.3. Change Application in Anchor Block

Changes are processed sequentially top-to-bottom.

**a) Processing deletion blocks:**
  - **Simple deletion:** specified lines are deleted
  - **Boundary deletion:** everything between boundaries is deleted (inclusive)

**b) Processing insertion blocks:**
  Insertion block can exist ONLY under one of these conditions:
  - After deletion block → inserted at position of first deleted line
  - After context lines → inserted after last context line
  - With `@@ BOF` marker → inserted at file beginning
  - With `@@ EOF` marker → inserted at file end

  **Error E412:** if insertion block is not bound to any of the above conditions

**c) Context lines:**
  - Remain unchanged, serve only for positioning

### 8.4. `--apply-all-matches`

**Restriction:** option is allowed only for diff blocks containing **exactly one hunk**. With multiple hunks — error **E304**.

**Algorithm:**
1. Search for the first anchor pattern occurrence starts from position 0
2. After applying changes, cursor moves to line immediately after processed anchor block
3. Search for next occurrence of same anchor pattern continues from new cursor position
4. Process repeats until end of file

**Example:**
```
File: A B C A B D
Hunk: -A B / +X
Result: X C X D (both occurrences replaced)
```

**Rationale:** With multiple hunks, ambiguity arises — where should the cursor be for the second hunk after multiple applications of the first? Separation into individual diff blocks eliminates ambiguity.

### 8.5. Sequential Application Rule

1. Between **diff blocks** — strictly in document order.
2. Between **hunks** — strictly top-to-bottom within block.
3. **Within file** — search is conducted from current cursor position to end; hunks **must** be arranged in ascending position order in file.

---

## 9. Conformance

### 9.1. Conformance Levels

**Minimal conformant parser** MUST:
- Parse `diff --git`, `---/+++` headers
- Parse unified hunk headers `@@`
- Recognize ` `, `-`, `+` prefixes in hunk body
- Implement the search cursor mechanism
- Report errors E100-E103, E200-E207, E400-E413, E600-E611

**Minimal conformant applicator** MUST:
- Apply changes according to §8 algorithm
- Respect hunk ordering (E413)
- Handle create/delete/rename/copy operations

**Full conformance** additionally requires support for:
- Extensions: `@@`, `@@ BOF`, `@@ EOF` (SHOULD)
- Extensions: boundary blocks with `...` (SHOULD)
- Extensions: global options `--ignore-*`, `--apply-all-matches` (MAY)
- Extensions: comments `#` (SHOULD)
- Extensions: named roots `@root` (MAY)

### 9.2. Interoperability Notes

| Feature | lite-diff | git apply | Notes |
|---------|-----------|-----------|-------|
| Numeric ranges in `@@` | Ignored | Used for validation | lite-diff finds position by content, not line numbers |
| `@@ BOF` / `@@ EOF` | Supported | Not recognized | lite-diff extension |
| Boundary `...` | Supported | Not recognized | lite-diff extension |
| Comments `#` | Ignored | May cause errors | lite-diff extension |
| `--ignore-*` in file | Supported | Not recognized | lite-diff extension |

---

## 10. Errors and Warnings (Reference)

Codes are organized by logical ranges for diagnostic convenience.

**Domain by hundreds:** 1xx PATH, 2xx HEADER, 3xx GLOBAL, 4xx HUNK, 5xx BOUNDARY, 6xx FILE_OP.

**Phase by tens:** x0x parse (syntax/format), x1x applicability (matching semantics).

### Range E1xx: Path Security (PATH)

| Code | Description |
|------|-------------|
| **E100** | Absolute path prohibited |
| **E101** | Traversal detected (`..`, `.`) |
| **E102** | Glob pattern detected in path |
| **E103** | Path leads to symbolic link |

### Range E2xx: Header Parsing (HEADER)

| Code | Description |
|------|-------------|
| **E200** | Multiple `---`/`+++` in header |
| **E201** | Mixed prefix schemes (`a/`/`b/` and `<prefix>:`) |
| **E202** | Path conflict between sources (`diff --git` vs `---/+++`) |
| **E203** | Invalid escape sequence |
| **E204** | Path contains spaces without quotes |
| **E205** | Header `diff --git` not from first position |
| **E206** | Header `---` or `+++` not from first position |
| **E207** | Header metadata (index, mode, rename, copy, etc.) not from first position |
| **E214** | Missing workspace indication in multi-root without `--default-root` |
| **E215** | Unknown workspace root in multi-root workspace |

### Range E3xx: Global Options (GLOBAL)

| Code | Description |
|------|-------------|
| **E300** | Global options after first `diff` |
| **E301** | Unknown global option |
| **E302** | Global option `--` not from first position |
| **E303** | Comment `#` not from first position |
| **E304** | `--apply-all-matches` used for diff block with multiple hunks |

### Range E4xx: Hunks and Context (HUNK)

| Code | Description |
|------|-------------|
| **E400** | Hunk header `@@` not from first position |
| **E401** | Invalid line prefix in hunk body (must be ` `, `-`, `+`, `#`, `...`) |
| **E402** | Blank line inside hunk body |
| **E410** | No `anchor pattern` match found |
| **E411** | Invalid content after `@@ BOF/EOF` (only `+` allowed) |
| **E412** | Insertion not bound to deletion/context/BOF/EOF |
| **E413** | Anchor pattern found before cursor position (hunk order violated) |

### Range E5xx: Boundary Blocks (BOUNDARY)

| Code | Description |
|------|-------------|
| **E510** | Multiple `...` in a row in boundary block |
| **E511** | `...` at beginning or end of boundary block |
| **E512** | Missing `-` lines on either side of `...` |

### Range E6xx: File Operations (FILE_OP)

| Code | Description |
|------|-------------|
| **E600** | Creating file, but target already exists |
| **E601** | Cannot delete: file not found or not a regular file |
| **E602** | Target path already exists for `rename/copy` |
| **E603** | Source file missing for `rename/copy` |
| **E604** | Multiple mutually exclusive operations detected in header |
| **E605** | `rename from` without `rename to` |
| **E606** | `copy from` without `copy to` |
| **E611** | File not found for regular edit |

### Warnings

| Code | Description |
|------|-------------|
| **W601** | Binary file skipped (`Binary files differ`/`GIT binary patch`) |

---

## 11. Compatibility and Edge Cases

- Some git metadata is intentionally ignored (`index`, `old/new mode`, `similarity/dissimilarity index`).
- Timestamps in `---/+++` are ignored; only the path part matters.
- In `rename/copy`, EOL and BOM are inherited from source; for "create", EOL is chosen by editor/environment policy.
- Code points, Unicode escaping, and slashes are normalized.

---

## Acknowledgments

This specification is inspired by the classic unified diff format, which has been a cornerstone of version control systems for decades. lite-diff is an independent format that extends and simplifies the original concept for modern use cases.
