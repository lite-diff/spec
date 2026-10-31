#!/usr/bin/env python3
"""Conformance runner for lite-diff v1.1.

Python 3 standard library only. See tests/README.md for the case format and the
runner contract.

    python tests/run.py --impl "<command>" [--only <glob>] [-v] [--keep]
    python tests/run.py --list [--only <glob>]

For each case the runner copies input/ into a fresh temporary workdir, copies
patch.diff next to it, runs `<command> <patch-path> <workdir>`, and compares the
workdir with expected/ and the printed result JSON (Appendix B) with
expected.json.
"""
import argparse
import fnmatch
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_DIR = os.path.join(HERE, "cases")

# Keys of expected.json that are instructions to the runner, not result fields.
RUNNER_KEYS = ("absent", "exactTree", "forbidDiagnostics", "diagnosticCounts")


# --------------------------------------------------------------------------
# case discovery
# --------------------------------------------------------------------------

def load_cases():
    cases = []
    if not os.path.isdir(CASES_DIR):
        return cases
    for group in sorted(os.listdir(CASES_DIR)):
        gdir = os.path.join(CASES_DIR, group)
        if not os.path.isdir(gdir):
            continue
        for name in sorted(os.listdir(gdir)):
            cdir = os.path.join(gdir, name)
            cj = os.path.join(cdir, "case.json")
            if not os.path.isfile(cj):
                continue
            with open(cj, encoding="utf-8") as f:
                meta = json.load(f)
            ej = os.path.join(cdir, "expected.json")
            if os.path.isfile(ej):
                with open(ej, encoding="utf-8") as f:
                    meta["_expected"] = json.load(f)
            else:
                meta["_expected"] = None
            meta["_dir"] = cdir
            meta["_group"] = group
            meta.setdefault("id", name)
            cases.append(meta)
    return cases


def selected(case, patterns):
    if not patterns:
        return True
    keys = (case["id"], "%s/%s" % (case["_group"], os.path.basename(case["_dir"])))
    return any(fnmatch.fnmatchcase(k, p) for p in patterns for k in keys)


# --------------------------------------------------------------------------
# subset comparison of result JSON
# --------------------------------------------------------------------------

def _tname(v):
    return type(v).__name__


def match(exp, act, path="$"):
    """Return a list of mismatch descriptions (empty when `act` satisfies `exp`).

    Objects: every key of `exp` must be present in `act` and match recursively;
    keys not mentioned in `exp` are ignored.
    Arrays: same length, elements matched one-to-one in any order.
    Scalars: equal (booleans never equal numbers).
    """
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            return ["%s: expected object, got %s" % (path, _tname(act))]
        errs = []
        for k, v in exp.items():
            if k not in act:
                errs.append("%s.%s: missing" % (path, k))
            else:
                errs.extend(match(v, act[k], "%s.%s" % (path, k)))
        return errs
    if isinstance(exp, list):
        if not isinstance(act, list):
            return ["%s: expected array, got %s" % (path, _tname(act))]
        if len(exp) != len(act):
            return ["%s: expected %d element(s), got %d" % (path, len(exp), len(act))]
        if _assign(exp, act, path) is None:
            # report the first element that cannot be matched at all, for readability
            for i, e in enumerate(exp):
                if not any(not match(e, a, path) for a in act):
                    best = min((match(e, a, "%s[%d]" % (path, i)) for a in act), key=len)
                    return best or ["%s[%d]: no matching element" % (path, i)]
            return ["%s: elements cannot be matched one-to-one" % path]
        return []
    if isinstance(exp, bool) or isinstance(act, bool):
        if not (isinstance(exp, bool) and isinstance(act, bool) and exp == act):
            return ["%s: expected %r, got %r" % (path, exp, act)]
        return []
    if exp != act:
        return ["%s: expected %r, got %r" % (path, exp, act)]
    return []


def _assign(exp, act, path):
    """One-to-one assignment of expected elements to distinct actual elements.

    Returns a list of actual indices or None. `act` may have more elements than
    `exp` (array lengths are checked by the caller where required)."""
    ok = [[j for j, a in enumerate(act) if not match(e, a, path)] for e in exp]
    order = sorted(range(len(exp)), key=lambda i: len(ok[i]))
    used, result = set(), [None] * len(exp)

    def bt(k):
        if k == len(order):
            return True
        i = order[k]
        for j in ok[i]:
            if j not in used:
                used.add(j)
                result[i] = j
                if bt(k + 1):
                    return True
                used.discard(j)
        return False

    return result if bt(0) else None


def compare_result(expected, actual):
    errs = []
    if not isinstance(actual, dict):
        return ["result is not a JSON object"]
    # status is always compared
    if "status" not in expected:
        errs.append("expected.json has no status")
    for k, v in expected.items():
        if k in RUNNER_KEYS or k == "diagnostics":
            continue
        if k not in actual:
            errs.append("$.%s: missing" % k)
        else:
            errs.extend(match(v, actual[k], "$.%s" % k))
    adiags = actual.get("diagnostics", [])
    if not isinstance(adiags, list):
        errs.append("$.diagnostics: expected array")
        adiags = []
    if "diagnostics" in expected:
        edi = expected["diagnostics"]
        if _assign(edi, adiags, "$.diagnostics") is None:
            derrs = []
            for e in edi:
                same = [a for a in adiags if isinstance(a, dict) and a.get("code") == e.get("code")]
                if not same:
                    derrs.append("$.diagnostics: no %s reported" % e.get("code"))
                elif not any(not match(e, a) for a in same):
                    best = min((match(e, a, "$.diagnostics[%s]" % e.get("code")) for a in same), key=len)
                    derrs.extend(best)
            errs.extend(derrs or ["$.diagnostics: expected diagnostics cannot be matched one-to-one"])
    codes = [a.get("code") for a in adiags if isinstance(a, dict)]
    for code in expected.get("forbidDiagnostics", []):
        if code in codes:
            errs.append("$.diagnostics: %s must not be reported" % code)
    for code, n in expected.get("diagnosticCounts", {}).items():
        if codes.count(code) != n:
            errs.append("$.diagnostics: expected %d x %s, got %d" % (n, code, codes.count(code)))
    return errs


# --------------------------------------------------------------------------
# workspace comparison
# --------------------------------------------------------------------------

def tree_files(base):
    out = set()
    if not os.path.isdir(base):
        return out
    for root, dirs, files in os.walk(base):
        for name in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            rel = os.path.relpath(os.path.join(root, name), base)
            out.add(rel.replace(os.sep, "/"))
    return out


def compare_tree(case_dir, work, expected):
    errs = []
    exp_dir = os.path.join(case_dir, "expected")
    exp_files = tree_files(exp_dir)
    for rel in sorted(exp_files):
        p = os.path.join(work, *rel.split("/"))
        if not os.path.isfile(p):
            errs.append("file %s: missing in workdir" % rel)
            continue
        with open(os.path.join(exp_dir, *rel.split("/")), "rb") as f:
            want = f.read()
        with open(p, "rb") as f:
            got = f.read()
        if want != got:
            errs.append("file %s: content differs (expected %r, got %r)" % (rel, want[:120], got[:120]))
    for rel in expected.get("absent", []):
        if os.path.lexists(os.path.join(work, *rel.split("/"))):
            errs.append("file %s: must not exist" % rel)
    if expected.get("exactTree"):
        extra = tree_files(work) - exp_files
        for rel in sorted(extra):
            errs.append("file %s: unexpected file in workdir" % rel)
    return errs


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------

class Skip(Exception):
    pass


def current_platform():
    return "windows" if os.name == "nt" else "posix"


def setup_workdir(case, tmp):
    platforms = case.get("platforms")
    if platforms and current_platform() not in platforms:
        raise Skip("case is for %s only (this is %s)" % ("/".join(platforms), current_platform()))
    work = os.path.join(tmp, "work")
    src = os.path.join(case["_dir"], "input")
    if os.path.isdir(src):
        shutil.copytree(src, work, symlinks=True)
    else:
        os.makedirs(work)
    for link, target in case.get("setup", {}).get("symlinks", {}).items():
        lp = os.path.join(work, *link.split("/"))
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        try:
            os.symlink(target, lp)
        except (OSError, NotImplementedError) as e:
            raise Skip("cannot create symlink %s: %s" % (link, e))
    patch = os.path.join(tmp, "patch.diff")
    shutil.copyfile(os.path.join(case["_dir"], "patch.diff"), patch)
    return patch, work


def build_command(impl, patch, work):
    if os.name == "nt":
        return "%s %s" % (impl, subprocess.list2cmdline([patch, work]))
    return "%s %s %s" % (impl, shlex.quote(patch), shlex.quote(work))


def run_case(case, impl, timeout, keep):
    expected = case["_expected"]
    if expected is None:
        return "FAIL", ["expected.json missing"], None
    tmp = tempfile.mkdtemp(prefix="litediff-")
    try:
        patch, work = setup_workdir(case, tmp)
        try:
            proc = subprocess.run(build_command(impl, patch, work), shell=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except subprocess.TimeoutExpired:
            return "FAIL", ["timeout after %ss" % timeout], tmp
        out = proc.stdout.decode("utf-8", "replace").strip()
        try:
            actual = json.loads(out)
        except ValueError:
            err = proc.stderr.decode("utf-8", "replace").strip()
            return "FAIL", ["stdout is not a JSON document (exit %d): %r; stderr: %r"
                            % (proc.returncode, out[:200], err[:200])], tmp
        errs = compare_result(expected, actual)
        if isinstance(actual, dict) and actual.get("status") in ("applied", "checked") and proc.returncode != 0:
            errs.append("non-zero exit status %d for status %r" % (proc.returncode, actual.get("status")))
        errs.extend(compare_tree(case["_dir"], work, expected))
        return ("PASS" if not errs else "FAIL"), errs, tmp
    except Skip as e:
        return "SKIP", [str(e)], tmp
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="lite-diff v1.1 conformance runner")
    ap.add_argument("--impl", help="command that applies a patch: <command> <patch-path> <workdir>")
    ap.add_argument("--only", action="append", default=[], metavar="GLOB",
                    help="run only cases whose id or group/id matches GLOB (repeatable)")
    ap.add_argument("--list", action="store_true", help="list case ids with their spec references")
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds per case (default 60)")
    ap.add_argument("--keep", action="store_true", help="keep temporary workdirs")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every mismatch of failing cases")
    args = ap.parse_args(argv)

    cases = [c for c in load_cases() if selected(c, args.only)]
    if args.list:
        width = max([len(c["id"]) for c in cases] + [2])
        for c in cases:
            flag = " (uncertain)" if c.get("uncertain") else ""
            print("%-*s  %s%s" % (width, c["id"], ", ".join(c.get("spec", [])), flag))
        print("%d case(s)" % len(cases))
        return 0
    if not args.impl:
        ap.error("--impl is required unless --list is given")
    if not cases:
        print("no cases selected")
        return 1

    width = max(len(c["id"]) for c in cases)
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    failed = []
    print("%-*s  RESULT  DETAIL" % (width, "CASE"))
    for c in cases:
        res, errs, tmp = run_case(c, args.impl, args.timeout, args.keep)
        counts[res] += 1
        detail = errs[0] if errs else ""
        if args.keep and tmp:
            detail = (detail + "  [workdir %s]" % tmp).strip()
        print("%-*s  %-6s  %s" % (width, c["id"], res, detail))
        if res == "FAIL":
            failed.append((c, errs))
            if args.verbose:
                for e in errs[1:]:
                    print("%-*s          %s" % (width, "", e))
    print()
    print("summary: %d passed, %d failed, %d skipped, %d total"
          % (counts["PASS"], counts["FAIL"], counts["SKIP"], len(cases)))
    unc = [c["id"] for c, _ in failed if c.get("uncertain")]
    if unc:
        print("failing cases marked uncertain (see AMBIGUITIES.md): %s" % ", ".join(unc))
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
