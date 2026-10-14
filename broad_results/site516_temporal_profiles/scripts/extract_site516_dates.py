#!/usr/bin/env python3
"""Resumably extract site 516 pedestrian events for temporal profiles."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "broad_results" / "site516_temporal_profiles"
EXTRACT = RESULTS / "extract"
STATE = RESULTS / "extract_state.json"
LOG = RESULTS / "extract.log"
SITE_FILE = ROOT / "broad_results" / "site516_multiday" / "site516.csv"
HST_ROOT = ROOT / "Data Dump" / "History (HST) files"

SEASON_START = date(2017, 9, 1)
SEASON_END = date(2018, 8, 31)
WEEK_START = date(2018, 9, 14)
WEEK_END = date(2018, 9, 20)


def date_range(start: date, end: date) -> list[str]:
    values = []
    current = start
    while current <= end:
        values.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return values


def requested_dates() -> list[str]:
    return sorted(set(date_range(SEASON_START, SEASON_END) + date_range(WEEK_START, WEEK_END)))


def resolve_java() -> str:
    candidates = [
        os.environ.get("SCATS_JAVA", ""),
        shutil.which("java") or "",
        "/opt/homebrew/opt/openjdk/bin/java",
        "/usr/local/opt/openjdk/bin/java",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("No Java runtime found; set SCATS_JAVA to a working java executable")


def paths_for(day: str) -> dict[str, Path]:
    folder = EXTRACT / day
    return {
        "folder": folder,
        "observations": folder / f"walk_delay_observations_{day}.csv",
        "censored": folder / f"walk_censored_intervals_{day}.csv",
        "status": folder / f"site_processing_status_{day}.csv",
    }


def validated(day: str) -> bool:
    paths = paths_for(day)
    if not all(paths[key].is_file() and paths[key].stat().st_size > 100 for key in ("observations", "censored", "status")):
        return False
    try:
        with paths["status"].open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        return len(rows) == 1 and rows[0].get("site") == "516" and rows[0].get("status") == "ok"
    except (OSError, csv.Error):
        return False


def write_state(payload: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE)


def run() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    EXTRACT.mkdir(parents=True, exist_ok=True)
    java = resolve_java()
    classpath = os.pathsep.join(
        [
            str(ROOT / "converted_samples"),
            str(ROOT / "converted_samples" / "ScatsHistoryViewer_payload.jar"),
            str(ROOT / "converted_samples" / "scats_viewer_extracted" / "*"),
        ]
    )
    days = requested_dates()
    completed = [day for day in days if validated(day)]
    errors: dict[str, str] = {}
    write_state(
        {
            "status": "running",
            "completed": len(completed),
            "expected": len(days),
            "current_date": "",
            "errors": errors,
        }
    )

    with LOG.open("a", encoding="utf-8") as log:
        for index, day in enumerate(days, start=1):
            if validated(day):
                continue
            raw = HST_ROOT / "WILL" / f"WILL_{day}.hst"
            if not raw.is_file():
                errors[day] = f"missing raw file: {raw}"
                write_state(
                    {
                        "status": "running_with_errors",
                        "completed": len([value for value in days if validated(value)]),
                        "expected": len(days),
                        "current_date": day,
                        "errors": errors,
                    }
                )
                continue
            paths = paths_for(day)
            paths["folder"].mkdir(parents=True, exist_ok=True)
            command = [
                java,
                "-Xmx2g",
                "-cp",
                classpath,
                "BroadWalkExtractor",
                str(SITE_FILE),
                str(HST_ROOT),
                day,
                str(paths["folder"]),
            ]
            log.write(f"START {day}\n")
            log.flush()
            result = subprocess.run(command, stdout=log, stderr=log, text=True, check=False)
            if result.returncode != 0 or not validated(day):
                errors[day] = f"extractor exit={result.returncode}; output validation failed"
            else:
                errors.pop(day, None)
            completed_count = len([value for value in days if validated(value)])
            write_state(
                {
                    "status": "running" if not errors else "running_with_errors",
                    "completed": completed_count,
                    "expected": len(days),
                    "current_date": day,
                    "errors": errors,
                }
            )
            print(f"date={day} completed={completed_count}/{len(days)} errors={len(errors)}", flush=True)

    completed_count = len([value for value in days if validated(value)])
    terminal = "complete" if completed_count == len(days) and not errors else "failed"
    write_state(
        {
            "status": terminal,
            "completed": completed_count,
            "expected": len(days),
            "current_date": days[-1],
            "errors": errors,
        }
    )
    return 0 if terminal == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(run())
