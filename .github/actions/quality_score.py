"""
Aggregates static-analysis outputs (flake8, mypy, bandit, radon, checkov)
into a single JSON + Markdown summary and exposes pass/fail to GitHub Actions.
"""

from __future__ import annotations
import json
import os
import glob
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def main() -> int:
    threshold = getenv_int("QUALITY_THRESHOLD", "80")
    fail_on_syntax = getenv_bool("FAIL_ON_SYNTAX_ERROR", "true")
    chk_high_w = getenv_float("CHECKOV_HIGH_WEIGHT", "8")
    chk_med_w = getenv_float("CHECKOV_MED_WEIGHT", "3")

    out_dir = Path("outputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    flake8_p = first_match(["artifacts/python/**/flake8.json"])
    mypy_p = first_match(["artifacts/python/**/mypy.json"])
    bandit_p = first_match(["artifacts/python/**/bandit.json"])
    radon_p = first_match(["artifacts/python/**/radon_cc.json"])
    syntax_p = first_match(["artifacts/python/**/syntax.json"])

    checkov_p = first_match([
        "artifacts/checkov/**/checkov.json",
        "artifacts/checkov/**/results_json.json",
        "artifacts/checkov/**/checkov*.json",
    ])

    # --- Parse metrics ---

    flake8_issues = 0
    if flake8_p:
        fj = read_json(flake8_p)
        if isinstance(fj, dict):
            flake8_issues = sum(len(v or []) for v in fj.values())

    mypy_errors = 0
    if mypy_p:
        mj = read_json(mypy_p)
        if isinstance(mj, dict):
            if isinstance(mj.get("messages"), list):
                mypy_errors = sum(
                    1 for m in mj["messages"]
                    if str(m.get("severity", "")).lower() == "error" or "message" in m
                )
            elif isinstance(mj.get("errors"), int):
                mypy_errors = mj["errors"]
        elif isinstance(mj, list):
            mypy_errors = len(mj)

    bandit_high = bandit_med = 0
    if bandit_p:
        bj = read_json(bandit_p)
        if isinstance(bj, dict) and isinstance(bj.get("results"), list):
            for r in bj["results"]:
                sev = str(r.get("issue_severity", "")).upper()
                if sev == "HIGH":
                    bandit_high += 1
                elif sev == "MEDIUM":
                    bandit_med += 1

    radon_viol = 0
    max_cc = 0
    if radon_p:
        rj = read_json(radon_p) or {}
        if isinstance(rj, dict):
            for entries in rj.values():
                for e in entries or []:
                    try:
                        c = int(e.get("complexity", 0))
                    except Exception:
                        c = 0
                    if c > 15:
                        radon_viol += 1
                    if c > max_cc:
                        max_cc = c

    syntax_passed = True
    if syntax_p:
        sj = read_json(syntax_p) or {}
        syntax_passed = bool(sj.get("passed", True))

    chk_high = chk_med = 0
    if checkov_p:
        cj = read_json(checkov_p)
        if isinstance(cj, dict):
            res = cj.get("results") or {}
            failed = res.get("failed_checks") or []
            if isinstance(failed, list):
                for fc in failed:
                    sev = str(fc.get("severity", "")).upper()
                    if sev == "HIGH":
                        chk_high += 1
                    elif sev == "MEDIUM":
                        chk_med += 1

    score = 100.0
    # hard_fail_reasons: List[str] = []

    # if not syntax_passed and fail_on_syntax:
    #     hard_fail_reasons.append("Syntax compile failed")

    # Deduct points (caps prevent domination by one tool)
    # Style (flake8)
    score -= min(30.0, 0.5 * flake8_issues)

    # Typing (mypy)
    score -= min(30.0, 1.0 * mypy_errors)

    # Python security (bandit)
    score -= min(30.0, 10.0 * bandit_high + 5.0 * bandit_med)

    # Complexity (radon)
    score -= min(20.0, 5.0 * radon_viol)

    # IaC security (Checkov)
    score -= min(30.0, chk_high_w * chk_high + chk_med_w * chk_med)

    # Hard fail: zero score for clarity if syntax failed and switch is on
    # if hard_fail_reasons:
    #     score = 0.0

    score = round(max(0.0, score), 2)
    passed = (score >= threshold)

    summary = {
        "threshold": threshold,
        "score": score,
        "passed": passed,
        # "hard_fail_reasons": hard_fail_reasons,
        "metrics": {
            "flake8_issues": flake8_issues,
            "mypy_errors": mypy_errors,
            "bandit_high": bandit_high,
            "bandit_med": bandit_med,
            "radon_violations_over_15": radon_viol,
            "radon_max_complexity": max_cc,
            "checkov_high": chk_high,
            "checkov_medium": chk_med,
        },
        "files": {
            "flake8": str(flake8_p) if flake8_p else None,
            "mypy": str(mypy_p) if mypy_p else None,
            "bandit": str(bandit_p) if bandit_p else None,
            "radon_cc": str(radon_p) if radon_p else None,
            "syntax": str(syntax_p) if syntax_p else None,
            "checkov": str(checkov_p) if checkov_p else None,
        },
    }

    (out_dir / "quality_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    lines: List[str] = []
    lines.append("# Code Quality Summary\n")
    if summary["passed"]:
        lines.append(f"* PASSED** — Score: **{score}** / {threshold} required")
    else:
        lines.append(f"**FAILED** — Score: **{score}** / {threshold} required")

    # if hard_fail_reasons:
    #     lines.append("\n**Hard fail reasons:**")
    #     lines.extend(f"- {r}" for r in hard_fail_reasons)

    m = summary["metrics"]
    lines.append("\n## Metrics")
    lines.append(f"- Flake8 issues: **{m['flake8_issues']}**")
    lines.append(f"- Mypy errors: **{m['mypy_errors']}**")
    lines.append(f"- Bandit: **{m['bandit_high']} HIGH**, **{m['bandit_med']} MEDIUM**")
    lines.append(
        f"- Radon: **{m['radon_violations_over_15']}** functions/methods over CC>15 "
        f"(max CC: {m['radon_max_complexity']})"
    )
    lines.append(f"- Checkov: **{m['checkov_high']} HIGH**, **{m['checkov_medium']} MEDIUM**")
    lines.append(
        "\n> See run artifacts for detailed JSON reports (flake8, mypy, bandit, radon, checkov) "
        "and SARIF in code scanning."
    )

    (out_dir / "quality_summary.md").write_text("\n".join(lines), encoding="utf-8")

    print("::group::Quality Summary")
    print("\n".join(lines))
    print("::endgroup::")

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