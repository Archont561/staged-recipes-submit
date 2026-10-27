"""Write a Markdown summary of a submission into ``$GITHUB_STEP_SUMMARY``."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping


def render_summary(report: dict[str, object]) -> str:
    """Turn the JSON report into a short Markdown summary."""
    dry_run = bool(report.get("dry_run"))
    lines = ["## staged-recipes submission", ""]
    if dry_run:
        lines += ["> Dry run: no branch, commit or pull request was created.", ""]
    results = report.get("results", [])
    if isinstance(results, list) and results:
        lines += ["| Outcome | Packages | Branch / pull request |", "| --- | --- | --- |"]
        for result in results:
            if not isinstance(result, dict):
                continue
            packages = ", ".join(str(name) for name in result.get("packages", []))
            target = result.get("pull_request") or f"`{result.get('branch', '')}`"
            lines.append(f"| {result.get('outcome', '')} | {packages} | {target} |")
        lines.append("")
    issues = report.get("issues", [])
    if isinstance(issues, list) and issues:
        lines += ["### Findings", ""]
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            hint = issue.get("hint")
            suffix = f" — hint: {hint}" if hint else ""
            lines.append(f"- `{issue.get('code', '')}` {issue.get('message', '')}{suffix}")
        lines.append("")
    lines.append(
        "Final acceptance, builds and publication remain under conda-forge's normal review and CI process."
    )
    return "\n".join(lines) + "\n"


def main(environment: Mapping[str, str] | None = None) -> int:
    environment = os.environ if environment is None else environment
    raw = environment.get("REPORT_JSON", "").strip()
    if not raw:
        return 0
    summary_path = environment.get("GITHUB_STEP_SUMMARY")
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    text = render_summary(report) if isinstance(report, dict) else ""
    if summary_path and text:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
