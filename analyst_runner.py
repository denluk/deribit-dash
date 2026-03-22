"""
Analyst runner — builds the 10-phase prompt and streams claude --print output.
Called from 8_Analyst.py after data extraction (phases 0-2) is done.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import os
from pathlib import Path

ROOT         = Path(__file__).parent
ACCURACY     = ROOT / "accuracy"
SIGNAL_STATS = ACCURACY / "signal_stats.json"
LOGS         = ROOT / "logs"
SKILL_V2     = Path("/opt/workspace/infralearn/skills/deribit-analyst/SKILL_v2.md")

# ── load SKILL_v2.md as single source of truth ───────────────────────────

def _load_skill_v2() -> tuple[str, str]:
    """Return (preamble, phases_3_to_10) extracted from SKILL_v2.md."""
    raw = SKILL_V2.read_text()
    # Strip YAML frontmatter
    if raw.startswith("---"):
        raw = raw[raw.index("---", 3) + 3:].lstrip()
    phase0_idx = raw.index("## PHASE 0")
    phase3_idx = raw.index("## PHASE 3")
    preamble    = raw[:phase0_idx].strip()
    phases_3_10 = raw[phase3_idx:].strip()
    return preamble, phases_3_10

def _load_signal_stats() -> dict:
    if SIGNAL_STATS.exists():
        try:
            return json.loads(SIGNAL_STATS.read_text())
        except Exception:
            pass
    return {}


def build_prompt(sv: dict, grade_data: dict | None = None) -> str:
    """Build the full analytical prompt from SKILL_v2.md (single source of truth)."""
    from datetime import date

    signal_stats  = _load_signal_stats()
    preamble, phases_3_10 = _load_skill_v2()

    grade_block = ""
    if grade_data and not grade_data.get("grade_skipped"):
        running     = grade_data.get("running_stats", {})
        recal_active = running.get("recalibration_active", False)
        recal_warn  = (
            "\n🔴 **RECALIBRATION ACTIVE** — "
            "multiply ALL conviction scores by 0.70. Hedge only. 0.25× sizing max.\n"
            if recal_active else ""
        )
        grade_block = f"""
## PHASE 0 — GRADING CONTEXT (pre-computed by dashboard)
```json
{json.dumps(grade_data, indent=2, default=str)}
```{recal_warn}
"""

    return f"""{preamble}

Phases 0-2 (grading, audit, data extraction) were already executed by the dashboard pipeline.
Your task: Execute **Phases 3-10** using the pre-extracted state vector and signal stats below.
Today's date: {date.today().isoformat()}
{grade_block}
---

## EXTRACTED STATE VECTOR (from in-house Deribit parquet artifacts)
```json
{json.dumps(sv, indent=2, default=str)}
```

## SIGNAL WEIGHTS (adaptive, from accuracy/signal_stats.json)
```json
{json.dumps(signal_stats, indent=2)}
```

---
{phases_3_10}
"""


def stream_analysis(sv: dict, grade_data: dict | None = None):
    """
    Generator that yields text chunks from claude --print.
    Writes the complete prompt to a temp file to avoid shell arg limits.
    """
    prompt = build_prompt(sv, grade_data)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="deribit_analyst_"
    ) as f:
        f.write(prompt)
        tmp_path = f.name

    try:
        cmd = ["claude", "--print", "--dangerously-skip-permissions", f"$(cat {tmp_path})"]
        # Use shell=True to allow $(...) expansion
        process = subprocess.Popen(
            f'claude --print --dangerously-skip-permissions "$(cat {tmp_path})"',
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ROOT),
        )
        for line in iter(process.stdout.readline, ""):
            yield line
        process.wait()
        if process.returncode != 0:
            err = process.stderr.read()
            if err:
                yield f"\n\n⚠️ stderr: {err[:500]}\n"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def extract_log_json(full_text: str) -> dict | None:
    """
    Extract the Phase 10 JSON block from the full analysis text.
    Returns parsed dict or None if not found.
    """
    # Find last ```json ... ``` block in the output
    pattern = r"```json\s*(\{[\s\S]*?\})\s*```"
    matches = re.findall(pattern, full_text)
    if not matches:
        return None
    # Take the last (largest) JSON block — that's the log
    for candidate in reversed(matches):
        try:
            data = json.loads(candidate)
            # Must have prediction fields to qualify as the log
            if "prediction_24h" in data or "scenario_tree" in data:
                return data
        except json.JSONDecodeError:
            continue
    return None


def save_log(log_data: dict) -> str | None:
    """
    Call analyst_agent.py write-log with the parsed log data.
    Returns the written file path or None on failure.
    """
    import sys

    venv_py = ROOT / "venv" / "bin" / "python"
    python  = str(venv_py) if venv_py.exists() else sys.executable
    agent   = ROOT / "analyst_agent.py"

    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [python, str(agent), "write-log", "--data", json.dumps(log_data, default=str)],
        capture_output=True, text=True, cwd=str(ROOT), env=env,
    )
    if result.returncode == 0:
        try:
            out = json.loads(result.stdout)
            return out.get("written")
        except Exception:
            pass
    return None
