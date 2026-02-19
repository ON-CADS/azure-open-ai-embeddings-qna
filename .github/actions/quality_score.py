"""
Aggregates static-analysis outputs (flake8, mypy, bandit, radon, Trivy)
into a single JSON + Markdown summary and exposes pass/fail to GitHub Actions.
"""

from __future__ import annotations
import json
import os
import glob
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def getenv_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() == "true"


def getenv_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)


def getenv_int(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return int(default)


def read_json(path: Path) -> Optional[Any]:
    try:
        txt = path.read_text(encoding="utf-8").strip()
        return json.loads(txt) if txt else None
    except Exception:
        return None


def first_match(patterns: List[str]) -> Optional[Path]:
    for pat in patterns:
        matches = glob.glob(pat, recursive=True)
        if matches:
            return Path(matches[0])
    return None


# ---------------------------
# Tool-specific parsers
# ---------------------------

def parse_flake8(path: Optional[Path]) -> Tuple[int, Dict[str, List[Dict[str, Any]]]]:
    """
    flake8-json output: dict keyed by file -> list of issues with:
      code, text, line_number, column_number.
    Returns (count, grouped_by_code)
    """
    total = 0
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    if not path:
        return total, grouped

    data = read_json(path)
    if not isinstance(data, dict):
        return total, grouped

    for file_path, issues in data.items():
        for it in (issues or []):
            code = str(it.get("code") or "F000")
            entry = {
                "file": file_path,
                "line": int(it.get("line_number") or 0),
                "col": int(it.get("column_number") or 0),
                "msg": str(it.get("text") or "").strip(),
                "code": code,
            }
            grouped.setdefault(code, []).append(entry)
            total += 1
    return total, grouped


def parse_mypy(path: Optional[Path]) -> Tuple[int, List[Dict[str, Any]]]:
    """
    mypy --error-format=json:
      Can be a JSON object with "messages" OR line-delimited JSON records.
      We collect only severity=="error".
    Returns (error_count, list[ {file,line,col,msg,code} ])
    """
    results: List[Dict[str, Any]] = []
    if not path:
        return 0, results

    raw = None
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return 0, results

    # Try object first
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and isinstance(obj.get("messages"), list):
            for m in obj["messages"]:
                sev = str(m.get("severity", "")).lower()
                if sev == "error" or "message" in m:
                    results.append({
                        "file": m.get("path") or m.get("filename"),
                        "line": int(m.get("line", 0) or 0),
                        "col": int(m.get("column", 0) or 0),
                        "msg": m.get("message") or "",
                        "code": (m.get("code") or {}).get("id") if isinstance(m.get("code"), dict) else m.get("code"),
                    })
            return len(results), results
        elif isinstance(obj, list):
            for m in obj:
                if not isinstance(m, dict):
                    continue
                sev = str(m.get("severity", "")).lower()
                if sev == "error" or "message" in m:
                    results.append({
                        "file": m.get("path") or m.get("filename"),
                        "line": int(m.get("line", 0) or 0),
                        "col": int(m.get("column", 0) or 0),
                        "msg": m.get("message") or "",
                        "code": (m.get("code") or {}).get("id") if isinstance(m.get("code"), dict) else m.get("code"),
                    })
            return len(results), results
    except Exception:
        pass

    # Fallback: line-delimited JSON
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if not isinstance(m, dict):
            continue
        sev = str(m.get("severity", "")).lower()
        if sev == "error" or "message" in m:
            results.append({
                "file": m.get("path") or m.get("filename"),
                "line": int(m.get("line", 0) or 0),
                "col": int(m.get("column", 0) or 0),
                "msg": m.get("message") or "",
                "code": (m.get("code") or {}).get("id") if isinstance(m.get("code"), dict) else m.get("code"),
            })
    return len(results), results


def parse_bandit(path: Optional[Path]) -> Tuple[int, int, Dict[str, List[Dict[str, Any]]]]:
    """
    Bandit JSON: dict with "results": [
      { "issue_severity": "HIGH"/"MEDIUM"/..., "test_id": "Bxxx",
        "issue_text": str, "filename": str, "line_number": int }
    ]
    Returns (high_count, med_count, grouped_by_test_id)
    """
    high = med = 0
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    if not path:
        return high, med, grouped

    data = read_json(path)
    if not (isinstance(data, dict) and isinstance(data.get("results"), list)):
        return high, med, grouped

    for r in data["results"]:
        sev = str(r.get("issue_severity", "")).upper()
        test = str(r.get("test_id") or "B000")
        if sev == "HIGH":
            high += 1
        elif sev == "MEDIUM":
            med += 1
        grouped.setdefault(test, []).append({
            "file": r.get("filename"),
            "line": int(r.get("line_number") or 0),
            "msg": r.get("issue_text"),
            "severity": sev,
            "test_id": test,
        })
    return high, med, grouped


def parse_radon(path: Optional[Path], threshold: int = 15) -> Tuple[int, int, List[Dict[str, Any]]]:
    """
    radon cc -j: dict mapping "file.py" -> [ { "name", "complexity", "lineno", ... } ]
    We count violations where complexity > threshold.
    Returns (violations_count, max_cc, list[ {file,line,name,complexity} ])
    """
    viol = 0
    max_cc = 0
    items: List[Dict[str, Any]] = []
    if not path:
        return viol, max_cc, items

    data = read_json(path) or {}
    if not isinstance(data, dict):
        return viol, max_cc, items

    for file_path, entries in data.items():
        for e in (entries or []):
            try:
                c = int(e.get("complexity", 0))
            except Exception:
                c = 0
            if c > threshold:
                viol += 1
                items.append({
                    "file": file_path,
                    "line": int(e.get("lineno") or 0),
                    "name": e.get("name"),
                    "complexity": c,
                })
            if c > max_cc:
                max_cc = c
    return viol, max_cc, items


def parse_trivy(path: Optional[Path]) -> Tuple[int, Dict[str, Dict[str, Any]]]:
    """
    Parse Trivy JSON for IaC misconfigurations:
      data["Results"][*]["Misconfigurations"] is a list of findings with fields like:
      ID, Title, Severity, PrimaryURL, CauseMetadata(StartLine, EndLine, Resource, ...)

    Returns:
      (failed_count, by_id)
      where by_id = {
        "AVD-.../KSV.../DS...": {
            "name": str,
            "severity": str,
            "occurrences": set( (target, line_start, line_end, resource, primary_url) )
        }, ...
      }
    """
    total_failed = 0
    by_id: Dict[str, Dict[str, Any]] = {}
    if not path:
        return total_failed, by_id

    data = read_json(path) or {}
    results = []
    if isinstance(data, dict):
        results = data.get("Results") or []
    if not isinstance(results, list):
        results = []

    for r in results:
        if not isinstance(r, dict):
            continue
        target = str(r.get("Target") or r.get("ArtifactName") or "").lstrip("./")
        miscs = r.get("Misconfigurations") or []
        if not isinstance(miscs, list):
            miscs = []

        for mc in miscs:
            if not isinstance(mc, dict):
                continue
            total_failed += 1
            mid = str(mc.get("ID") or "TRIVY_UNKNOWN")
            title = str(mc.get("Title") or mid)
            severity = str(mc.get("Severity") or "UNKNOWN").upper()
            primary = str(mc.get("PrimaryURL") or "")
            cause = mc.get("CauseMetadata") or {}
            if not isinstance(cause, dict):
                cause = {}
            resource = str(cause.get("Resource") or cause.get("resource") or "")
            line_start = cause.get("StartLine")
            line_end = cause.get("EndLine")

            try:
                line_start = int(line_start) if line_start is not None else None
            except Exception:
                line_start = None
            try:
                line_end = int(line_end) if line_end is not None else None
            except Exception:
                line_end = None

            bucket = by_id.setdefault(mid, {
                "name": title,
                "severity": severity,
                "occurrences": set(),
            })
            # keep last non-empty severity/title
            if title:
                bucket["name"] = title
            if severity:
                bucket["severity"] = severity

            bucket["occurrences"].add((target, line_start, line_end, resource, primary))

    return total_failed, by_id


def main() -> int:
    threshold = getenv_int("QUALITY_THRESHOLD", "35")

    # Backward compatible: prefer TRIVY_WEIGHT; fallback to CHECKOV_WEIGHT; then default "3"
    trivy_w = getenv_float("TRIVY_WEIGHT", os.getenv("CHECKOV_WEIGHT", "3"))

    out_dir = Path("outputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Locate artifacts saved by earlier jobs
    flake8_p = first_match(["artifacts/python/**/flake8.json"])
    mypy_p = first_match(["artifacts/python/**/mypy.json"])
    bandit_p = first_match(["artifacts/python/**/bandit.json"])
    radon_p = first_match(["artifacts/python/**/radon_cc.json"])
    syntax_p = first_match(["artifacts/python/**/syntax.json"])

    trivy_p = first_match([
        "artifacts/trivy/**/trivy.json",
        "artifacts/trivy/**/results.json",
        "artifacts/trivy/**/trivy*.json",
    ])

    # ---- Parse metrics & details ----
    flake8_total, flake8_by_code = parse_flake8(flake8_p)
    mypy_errors, mypy_list = parse_mypy(mypy_p)
    bandit_high, bandit_med, bandit_by_test = parse_bandit(bandit_p)
    radon_viol, radon_max_cc, radon_list = parse_radon(radon_p, threshold=15)

    syntax_passed = True
    if syntax_p:
        sj = read_json(syntax_p) or {}
        syntax_passed = bool(sj.get("passed", True))

    trivy_failed, trivy_by_id = parse_trivy(trivy_p)

    # ---- Score (same scales you used) ----
    score = 100.0
    score -= min(30.0, 0.5 * flake8_total)
    score -= min(30.0, 0.5 * mypy_errors)
    score -= min(30.0, 5.0 * bandit_high + 3.0 * bandit_med)
    score -= min(20.0, 2.0 * radon_viol)
    score -= min(30.0, trivy_w * trivy_failed)

    score = round(max(0.0, score), 2)
    passed = (score >= threshold)

    # ---- JSON summary payload ----
    summary = {
        "threshold": threshold,
        "score": score,
        "passed": passed,
        "metrics": {
            "flake8_issues": flake8_total,
            "mypy_errors": mypy_errors,
            "bandit_high": bandit_high,
            "bandit_med": bandit_med,
            "radon_violations_over_15": radon_viol,
            "radon_max_complexity": radon_max_cc,
            "trivy_failed": trivy_failed
        },
        "files": {
            "flake8": str(flake8_p) if flake8_p else None,
            "mypy": str(mypy_p) if mypy_p else None,
            "bandit": str(bandit_p) if bandit_p else None,
            "radon_cc": str(radon_p) if radon_p else None,
            "syntax": str(syntax_p) if syntax_p else None,
            "trivy": str(trivy_p) if trivy_p else None,
        },
        "details": {
            "flake8_by_code": flake8_by_code,
            "mypy": mypy_list,
            "bandit_by_test": bandit_by_test,
            "radon": radon_list,
            "trivy_by_id": {
                tid: {
                    "name": d.get("name"),
                    "severity": d.get("severity"),
                    "occurrences": sorted(
                        list(d.get("occurrences", set())),
                        key=lambda t: (t[0] or "", (t[1] if t[1] is not None else -1))
                    )
                }
                for tid, d in trivy_by_id.items()
            }
        }
    }

    Path("outputs/quality_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # ---- Markdown summary ----
    lines: List[str] = []
    lines.append("# Code Quality Summary\n")
    lines.append(f"**{'PASSED' if passed else 'FAILED'}** — Score: **{score}** / {threshold} required")

    # Metrics
    m = summary["metrics"]
    lines.append("\n## Metrics")
    lines.append(f"- Flake8 issues: **{m['flake8_issues']}**")
    lines.append(f"- Mypy errors: **{m['mypy_errors']}**")
    lines.append(f"- Bandit: **{m['bandit_high']} HIGH**, **{m['bandit_med']} MEDIUM**")
    lines.append(
        f"- Radon: **{m['radon_violations_over_15']}** functions/methods over CC>15 (max CC: {m['radon_max_complexity']})"
    )
    lines.append(f"- Trivy (IaC misconfig): **{m['trivy_failed']} failed**")

    lines.append("\n## Failed issues (structured, all tools)")

    # Syntax
    if not syntax_passed:
        lines.append("\n### Python syntax (compile)")
        lines.append("- **Compile failed** — see `outputs/syntax.json` for the overall status")

    # Flake8
    if flake8_total > 0:
        lines.append("\n### Flake8")
        for code in sorted(flake8_by_code.keys()):
            items = flake8_by_code[code]
            lines.append(f"**{code}** — {len(items)} occurrence(s)")
            for it in sorted(items, key=lambda x: (x['file'] or '', x['line'], x['col'])):
                lines.append(f"- `{it['file']}:{it['line']}:{it['col']}` — {it['msg']}")

    # Mypy
    if mypy_errors > 0:
        lines.append("\n### Mypy")
        lines.append(f"**error** — {mypy_errors} occurrence(s)")
        for it in sorted(mypy_list, key=lambda x: (x['file'] or '', x['line'], x['col'])):
            code = f" [{it['code']}]" if it.get("code") else ""
            lines.append(f"- `{it['file']}:{it['line']}:{it['col']}` — {it['msg']}{code}")

    # Bandit
    if bandit_high + bandit_med > 0:
        lines.append("\n### Bandit")
        for test_id in sorted(bandit_by_test.keys()):
            items = bandit_by_test[test_id]
            lines.append(f"**{test_id}** — {len(items)} occurrence(s)")
            for it in sorted(items, key=lambda x: (x['file'] or '', x['line'])):
                lines.append(f"- `{it['file']}:{it['line']}` — {it['msg']} ({it['severity']})")

    # Radon
    if radon_viol > 0:
        lines.append("\n### Radon (complexity > 15)")
        lines.append(f"**Violation** — {radon_viol} occurrence(s)")
        for it in sorted(radon_list, key=lambda x: (x['file'] or '', x['line'])):
            nm = f"{it['name']}".strip() if it.get("name") else "unknown"
            lines.append(f"- `{it['file']}:{it['line']}` — `{nm}` (CC={it['complexity']})")

    # Trivy
    if trivy_failed > 0:
        lines.append("\n### Trivy (IaC misconfigurations)")
        def sev_rank(val: str) -> int:
            return {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}.get((val or "UNKNOWN").upper(), 5)

        for tid, data in sorted(summary["details"]["trivy_by_id"].items(),
                                key=lambda kv: (sev_rank((kv[1].get("severity") or "").upper()), kv[0])):
            name = data.get("name") or tid
            sev = (data.get("severity") or "").upper() or "UNKNOWN"
            occs = data.get("occurrences") or []
            lines.append(f"**{tid} — {name}** (Severity: **{sev}**) — {len(occs)} occurrence(s)")
            for (target, ls, le, res, primary) in occs:
                loc = ""
                if ls is not None and le is not None:
                    loc = f":{ls}-{le}"
                elif ls is not None:
                    loc = f":{ls}"
                res_txt = f" — resource: `{res}`" if res else ""
                url_txt = f" — {primary}" if primary else ""
                lines.append(f"- `{target}{loc}`{res_txt}{url_txt}")

    lines.append("\n> All raw reports are saved as JSON artifacts (flake8, mypy, bandit, radon, trivy).")

    Path("outputs/quality_summary.md").write_text("\n".join(lines), encoding="utf-8")

    # Grouped log
    print("::group::Quality Summary")
    print("\n".join(lines))
    print("::endgroup::")

    # Expose outputs
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        Path(gh_out).write_text(
            "\n".join(
                [
                    f"score={score}",
                    f"threshold={threshold}",
                    f"passed={'true' if passed else 'false'}",
                ]
            ),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())