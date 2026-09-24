"""Human approval gate for agent reports."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from oncocs.agents.graph import UNAPPROVED_BANNER


def approve(agent_run_path: Path, by: str, note: str = "") -> Path:
    agent_run_path = Path(agent_run_path)
    record = json.loads(agent_run_path.read_text(encoding="utf-8"))
    if record.get("status") != "draft_pending_approval":
        raise ValueError(f"Cannot approve run with status {record.get('status')!r}")
    if record.get("approval"):
        raise ValueError("Run already approved")
    if record.get("human_review"):
        raise ValueError(f"Run already has a human decision: "
                         f"{record['human_review']['decision']!r}")

    report_path = agent_run_path.parent / "report.md"
    report = report_path.read_text(encoding="utf-8")
    m = re.search(r"<!-- agent_run_sha256: ([0-9a-f]+) -->", report)
    if not m:
        raise ValueError("report.md missing recorded agent_run hash")
    from oncocs.agents.graph import agent_run_sha
    if agent_run_sha(record) != m.group(1):
        raise ValueError("agent_run.json changed since report was rendered; refusing approval")

    approval = {"by": by, "timestamp": datetime.now(UTC).isoformat(),
                "agent_run_sha256": m.group(1)}
    if note:
        approval["note"] = note
    record["approval"] = approval
    agent_run_path.write_text(json.dumps(record, indent=2, default=str) + "\n",
                            encoding="utf-8")

    banner = f"> Approved by {by} on {approval['timestamp'][:10]}"
    if UNAPPROVED_BANNER in report:
        report = report.replace(UNAPPROVED_BANNER, banner, 1)
    else:
        report = re.sub(r"^> .*\n", banner + "\n", report, count=1)
    report_path.write_text(report, encoding="utf-8")
    return report_path


def reject(agent_run_path: Path, by: str, reason: str) -> Path:
    agent_run_path = Path(agent_run_path)
    record = json.loads(agent_run_path.read_text(encoding="utf-8"))
    if record.get("approval"):
        raise ValueError("Run already approved; cannot reject")
    if record.get("human_review"):
        raise ValueError(f"Run already has a human decision: "
                         f"{record['human_review']['decision']!r}")
    report_path = agent_run_path.parent / "report.md"
    report = report_path.read_text(encoding="utf-8")
    m = re.search(r"<!-- agent_run_sha256: ([0-9a-f]+) -->", report)
    if not m:
        raise ValueError("report.md missing recorded agent_run hash")
    from oncocs.agents.graph import agent_run_sha
    if agent_run_sha(record) != m.group(1):
        raise ValueError("agent_run.json changed since report was rendered; refusing rejection")

    record["human_review"] = {"decision": "rejected", "by": by,
                              "timestamp": datetime.now(UTC).isoformat(),
                              "reason": reason,
                              "agent_run_sha256": m.group(1)}
    agent_run_path.write_text(json.dumps(record, indent=2, default=str) + "\n",
                            encoding="utf-8")

    banner = f"> **REJECTED BY HUMAN REVIEWER ({by})** - {reason}"
    if UNAPPROVED_BANNER in report:
        report = report.replace(UNAPPROVED_BANNER, banner, 1)
    else:
        report = re.sub(r"^> .*\n", banner + "\n", report, count=1)
    report_path.write_text(report, encoding="utf-8")
    return report_path
