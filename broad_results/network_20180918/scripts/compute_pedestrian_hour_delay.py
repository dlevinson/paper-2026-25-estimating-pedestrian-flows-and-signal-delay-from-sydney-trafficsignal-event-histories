#!/usr/bin/env python3
"""Compute MCAV-calibrated pedestrian arrivals and delay by movement-hour."""

from __future__ import annotations

import bisect
import csv
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = ROOT / "broad_results" / "network_20180918"
DATE = "20180918"

ESTIMATES_IN = RESULTS_DIR / f"movement_hour_estimates_calibrated_mcav_{DATE}.csv"
WINDOWS_IN = RESULTS_DIR / f"ped_walk_windows_{DATE}.csv"
OBSERVATIONS_IN = RESULTS_DIR / f"walk_delay_observations_{DATE}.csv"
CYCLE_IN = RESULTS_DIR / f"cycle_first_actuation_estimates_{DATE}.csv"
DELAY_ALPHA_IN = (
    ROOT
    / "broad_results/validation/mcav_validation"
    / "mcav_compliance_scenario_summary.csv"
)
VIDEO_DELAY_ALPHA_IN = (
    ROOT
    / "broad_results/validation/video_noncompliance_validation"
    / "video_upstream_peer_summary.csv"
)
MOVEMENT_HOUR_OUT = RESULTS_DIR / f"pedestrian_movement_hour_delay_{DATE}.csv"
SITE_HOUR_OUT = RESULTS_DIR / f"pedestrian_site_hour_delay_{DATE}.csv"
README_OUT = RESULTS_DIR / f"pedestrian_hour_delay_summary_{DATE}.md"


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: format_value(row.get(key, "")) for key in fields})


def format_value(value):
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.6f}"
    return value


def load_delay_multipliers() -> dict[str, float]:
    metrics = {
        row["metric"]: float(row["value"])
        for row in read_csv(DELAY_ALPHA_IN)
        if row.get("value", "") not in ("", None)
    }
    video_metrics = {
        row["metric"]: float(row["value"])
        for row in read_csv(VIDEO_DELAY_ALPHA_IN)
        if row.get("value", "") not in ("", None)
        and row.get("metric") == "realised_delay_alpha_mean_case"
    }
    required = {
        "delay_alpha_observed_actuation_mean_case",
        "delay_alpha_observed_compliance_mean_case",
    }
    if not required.issubset(metrics):
        raise RuntimeError("MCAV compliance-scenario delay alphas not found")
    if "realised_delay_alpha_mean_case" not in video_metrics:
        raise RuntimeError("Video realised-delay alpha not found")
    return {
        "full_compliance": metrics[
            "delay_alpha_observed_actuation_mean_case"
        ],
        "observed_compliance": metrics[
            "delay_alpha_observed_compliance_mean_case"
        ],
        "video_observed_behaviour": video_metrics[
            "realised_delay_alpha_mean_case"
        ],
    }
def load_windows() -> tuple[dict[tuple[str, str], list[float]], dict[tuple[str, str, int], float]]:
    green_starts = defaultdict(list)
    walk_seconds = defaultdict(float)
    for row in read_csv(WINDOWS_IN):
        if row.get("state_desc") != "Green":
            continue
        key = (row["site"], row["movement"])
        start = float(row["start_s"])
        end = float(row["end_s"])
        green_starts[key].append(start)
        first_hour = max(0, min(int(start // 3600), 23))
        last_hour = max(0, min(int(max(start, end - 1) // 3600), 23))
        for hour in range(first_hour, last_hour + 1):
            lower = hour * 3600
            upper = lower + 3600
            walk_seconds[(row["site"], row["movement"], hour)] += max(0.0, min(end, upper) - max(start, lower))
    for starts in green_starts.values():
        starts.sort()
    return green_starts, walk_seconds


def load_service_lags(green_starts: dict) -> tuple[dict[tuple[str, str, int], list[float]], int]:
    lags = defaultdict(list)
    unmatched = 0
    for row in read_csv(OBSERVATIONS_IN):
        key = (row["site"], row["movement"])
        starts = green_starts.get(key, [])
        demand = float(row["demand_on_s"])
        index = bisect.bisect_left(starts, demand)
        if index >= len(starts):
            unmatched += 1
            continue
        lag = starts[index] - demand
        if lag < 0:
            unmatched += 1
            continue
        hour = int(row["hour"])
        lags[(row["site"], row["movement"], hour)].append(lag)
    return lags, unmatched


def movement_hour_rows(delay_multipliers: dict[str, float]) -> tuple[list[dict], int]:
    _, walk_seconds = load_windows()
    cycles = defaultdict(list)
    unmatched = 0
    for cycle in read_csv(CYCLE_IN):
        key = (cycle["site"], cycle["movement"], int(float(cycle["hour"])))
        cycles[key].append(cycle)
        if cycle.get("next_walk_s", "") == "":
            unmatched += 1
    rows = []
    for source in read_csv(ESTIMATES_IN):
        hour = int(float(source["hour"]))
        key = (source["site"], source["movement"], hour)
        hour_cycles = cycles.get(key, [])
        count_multiplier = float(source.get("mcav_multiplier_point") or 0)
        count_multiplier_low = float(source.get("mcav_multiplier_low") or 0)
        count_multiplier_high = float(source.get("mcav_multiplier_high") or 0)
        delay_multiplier_low = float(source.get("mcav_delay_multiplier_low") or 0)
        delay_multiplier_high = float(source.get("mcav_delay_multiplier_high") or 0)
        walk_s = walk_seconds.get(key, 0.0)
        # The movement-hour MLE already contains first-actuation event exposure
        # plus right-censored no-actuation intervals.  Its rate is applied to
        # the complete one-hour count exposure.  Delay is accumulated only for
        # observed first-actuation cycles because a no-actuation cycle has no
        # actuation-conditioned waiting population.
        effective_arrivals = float(source.get("mle_effective_arrivals_per_hour") or 0)
        lambda_per_second = effective_arrivals / 3600.0
        service_lags = [
            float(cycle["first_actuation_to_walk_s"])
            for cycle in hour_cycles
            if cycle.get("first_actuation_to_walk_s", "") != ""
        ]
        effective_delay_s = sum(
            lag + lambda_per_second * lag**2 / 2.0 for lag in service_lags
        )
        extra_arrivals = sum(lambda_per_second * lag for lag in service_lags)
        person_arrivals = effective_arrivals * count_multiplier
        person_arrivals_low = effective_arrivals * count_multiplier_low
        person_arrivals_high = effective_arrivals * count_multiplier_high
        delay_multiplier = delay_multipliers["full_compliance"]
        person_delay_h = effective_delay_s * delay_multiplier / 3600.0
        person_delay_h_low = effective_delay_s * delay_multiplier_low / 3600.0
        person_delay_h_high = effective_delay_s * delay_multiplier_high / 3600.0
        observed_compliance_multiplier = delay_multipliers["observed_compliance"]
        observed_compliance_multiplier_low = float(
            source.get("mcav_observed_compliance_delay_multiplier_low") or 0
        )
        observed_compliance_multiplier_high = float(
            source.get("mcav_observed_compliance_delay_multiplier_high") or 0
        )
        observed_compliance_delay_h = (
            effective_delay_s * observed_compliance_multiplier / 3600.0
        )
        observed_compliance_delay_h_low = (
            effective_delay_s * observed_compliance_multiplier_low / 3600.0
        )
        observed_compliance_delay_h_high = (
            effective_delay_s * observed_compliance_multiplier_high / 3600.0
        )
        video_observed_behaviour_delay_h = (
            effective_delay_s
            * delay_multipliers["video_observed_behaviour"]
            / 3600.0
        )

        row = dict(source)
        row.update(
            {
                "walk_s_in_hour": walk_s,
                "actuations_matched_to_next_walk": len(service_lags),
                "cycle_plugin_first_actuation_cycles": len(hour_cycles),
                "mean_actuation_to_walk_s": sum(service_lags) / len(service_lags) if service_lags else None,
                "expected_extra_effective_arrivals_after_actuation": extra_arrivals,
                "estimated_effective_arrivals_conditioned": effective_arrivals,
                "mcav_count_multiplier_point": count_multiplier,
                "mcav_count_multiplier_low": count_multiplier_low,
                "mcav_count_multiplier_high": count_multiplier_high,
                "mcav_delay_multiplier_point": delay_multiplier,
                "mcav_delay_multiplier_low": delay_multiplier_low,
                "mcav_delay_multiplier_high": delay_multiplier_high,
                "estimated_mcav_person_arrivals_conditioned": person_arrivals,
                "estimated_mcav_person_arrivals_conditioned_low": person_arrivals_low,
                "estimated_mcav_person_arrivals_conditioned_high": person_arrivals_high,
                "estimated_mcav_person_delay_h_conditioned": person_delay_h,
                "estimated_mcav_person_delay_h_conditioned_low": person_delay_h_low,
                "estimated_mcav_person_delay_h_conditioned_high": person_delay_h_high,
                "estimated_mcav_avg_delay_s_conditioned": person_delay_h * 3600.0 / person_arrivals if person_arrivals else None,
                "estimated_model_delay_h_unexpanded": effective_delay_s / 3600.0,
                "estimated_mcav_person_delay_h_observed_compliance_scenario": (
                    observed_compliance_delay_h
                ),
                "estimated_mcav_person_delay_h_observed_compliance_scenario_low": (
                    observed_compliance_delay_h_low
                ),
                "estimated_mcav_person_delay_h_observed_compliance_scenario_high": (
                    observed_compliance_delay_h_high
                ),
                "estimated_mcav_avg_delay_s_observed_compliance_scenario": (
                    observed_compliance_delay_h * 3600.0 / person_arrivals
                    if person_arrivals
                    else None
                ),
                "estimated_video_person_delay_h_observed_behaviour_sensitivity": (
                    video_observed_behaviour_delay_h
                ),
                "estimated_video_avg_delay_s_observed_behaviour_sensitivity": (
                    video_observed_behaviour_delay_h * 3600.0 / person_arrivals
                    if person_arrivals
                    else None
                ),
                "count_model": "pooled_first_actuation_with_no_actuation_right_censoring",
                "delay_model": "pooled_rate_first_actuation_to_walk_plus_later_arrivals",
            }
        )
        rows.append(row)
    return rows, unmatched


def site_hour_rows(movement_rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in movement_rows:
        groups[(row["site"], int(float(row["hour"])))].append(row)
    result = []
    for (site, hour), rows in sorted(groups.items(), key=lambda item: (int(item[0][0]), item[0][1])):
        included = [row for row in rows if row.get("recommended_for_mcav_aggregate") == "yes"]
        arrivals = sum(float(row["estimated_mcav_person_arrivals_conditioned"] or 0) for row in included)
        arrivals_low = sum(float(row["estimated_mcav_person_arrivals_conditioned_low"] or 0) for row in included)
        arrivals_high = sum(float(row["estimated_mcav_person_arrivals_conditioned_high"] or 0) for row in included)
        delay_h = sum(float(row["estimated_mcav_person_delay_h_conditioned"] or 0) for row in included)
        delay_h_low = sum(float(row["estimated_mcav_person_delay_h_conditioned_low"] or 0) for row in included)
        delay_h_high = sum(float(row["estimated_mcav_person_delay_h_conditioned_high"] or 0) for row in included)
        observed_compliance_delay_h = sum(
            float(
                row[
                    "estimated_mcav_person_delay_h_observed_compliance_scenario"
                ]
                or 0
            )
            for row in included
        )
        observed_compliance_delay_h_low = sum(
            float(
                row[
                    "estimated_mcav_person_delay_h_observed_compliance_scenario_low"
                ]
                or 0
            )
            for row in included
        )
        observed_compliance_delay_h_high = sum(
            float(
                row[
                    "estimated_mcav_person_delay_h_observed_compliance_scenario_high"
                ]
                or 0
            )
            for row in included
        )
        video_observed_behaviour_delay_h = sum(
            float(
                row[
                    "estimated_video_person_delay_h_observed_behaviour_sensitivity"
                ]
                or 0
            )
            for row in included
        )
        first = rows[0]
        result.append(
            {
                "date": DATE,
                "site": site,
                "region": first["region"],
                "street1": first["street1"],
                "street2": first["street2"],
                "suburb": first["suburb"],
                "lon": first["lon"],
                "lat": first["lat"],
                "hour": hour,
                "movement_hour_rows": len(rows),
                "included_movement_hour_rows": len(included),
                "mcav_person_arrivals_conditioned": arrivals,
                "mcav_person_arrivals_conditioned_low": arrivals_low,
                "mcav_person_arrivals_conditioned_high": arrivals_high,
                "mcav_person_delay_h_conditioned": delay_h,
                "mcav_person_delay_h_conditioned_low": delay_h_low,
                "mcav_person_delay_h_conditioned_high": delay_h_high,
                "mcav_avg_delay_s_conditioned": delay_h * 3600.0 / arrivals if arrivals else None,
                "mcav_person_delay_h_observed_compliance_scenario": (
                    observed_compliance_delay_h
                ),
                "mcav_person_delay_h_observed_compliance_scenario_low": (
                    observed_compliance_delay_h_low
                ),
                "mcav_person_delay_h_observed_compliance_scenario_high": (
                    observed_compliance_delay_h_high
                ),
                "mcav_avg_delay_s_observed_compliance_scenario": (
                    observed_compliance_delay_h * 3600.0 / arrivals
                    if arrivals
                    else None
                ),
                "video_person_delay_h_observed_behaviour_sensitivity": (
                    video_observed_behaviour_delay_h
                ),
                "video_avg_delay_s_observed_behaviour_sensitivity": (
                    video_observed_behaviour_delay_h * 3600.0 / arrivals
                    if arrivals
                    else None
                ),
                "count_model": "pooled_first_actuation_with_no_actuation_right_censoring",
                "delay_model": "pooled_rate_first_actuation_to_walk_plus_later_arrivals",
            }
        )
    return result


def write_summary(
    movement_rows: list[dict],
    site_rows: list[dict],
    unmatched: int,
    delay_multipliers: dict[str, float],
) -> None:
    included = [row for row in movement_rows if row.get("recommended_for_mcav_aggregate") == "yes"]
    arrivals = sum(float(row["estimated_mcav_person_arrivals_conditioned"] or 0) for row in included)
    arrivals_low = sum(float(row["estimated_mcav_person_arrivals_conditioned_low"] or 0) for row in included)
    arrivals_high = sum(float(row["estimated_mcav_person_arrivals_conditioned_high"] or 0) for row in included)
    delay_h = sum(float(row["estimated_mcav_person_delay_h_conditioned"] or 0) for row in included)
    delay_h_low = sum(float(row["estimated_mcav_person_delay_h_conditioned_low"] or 0) for row in included)
    delay_h_high = sum(float(row["estimated_mcav_person_delay_h_conditioned_high"] or 0) for row in included)
    observed_compliance_delay_h = sum(
        float(
            row["estimated_mcav_person_delay_h_observed_compliance_scenario"]
            or 0
        )
        for row in included
    )
    observed_compliance_delay_h_low = sum(
        float(
            row["estimated_mcav_person_delay_h_observed_compliance_scenario_low"]
            or 0
        )
        for row in included
    )
    observed_compliance_delay_h_high = sum(
        float(
            row["estimated_mcav_person_delay_h_observed_compliance_scenario_high"]
            or 0
        )
        for row in included
    )
    video_observed_behaviour_delay_h = sum(
        float(
            row["estimated_video_person_delay_h_observed_behaviour_sensitivity"]
            or 0
        )
        for row in included
    )
    site_516 = [row for row in site_rows if row["site"] == "516" and row["included_movement_hour_rows"] > 0]
    with README_OUT.open("w", encoding="utf-8") as handle:
        handle.write(f"# Pedestrian movement-hour delay ({DATE})\n\n")
        handle.write(f"- Movement-hour rows: {len(movement_rows):,}\n")
        handle.write(f"- Included usable non-auto-served movement-hours: {len(included):,}\n")
        handle.write(f"- First actuations without a following observed Walk: {unmatched:,}\n")
        handle.write(
            f"- MCAV 100%-compliance delay alpha: "
            f"{delay_multipliers['full_compliance']:.3f}\n"
        )
        handle.write(
            f"- MCAV observed-compliance-scenario delay alpha: "
            f"{delay_multipliers['observed_compliance']:.3f}\n"
        )
        handle.write(
            f"- Video observed-behaviour delay alpha sensitivity: "
            f"{delay_multipliers['video_observed_behaviour']:.3f}\n"
        )
        handle.write(f"- Hourly conditioned MCAV person arrivals: {arrivals:,.0f}\n")
        handle.write(f"- Empirical count-factor interval: {arrivals_low:,.0f}--{arrivals_high:,.0f}\n")
        handle.write(
            f"- 100%-compliance pedestrian delay: {delay_h:,.1f} "
            "pedestrian-hours\n"
        )
        handle.write(
            f"- 100%-compliance empirical factor interval: {delay_h_low:,.1f}--"
            f"{delay_h_high:,.1f} pedestrian-hours\n"
        )
        handle.write(
            f"- Observed-compliance pedestrian-delay scenario: "
            f"{observed_compliance_delay_h:,.1f} pedestrian-hours "
            f"({observed_compliance_delay_h_low:,.1f}--"
            f"{observed_compliance_delay_h_high:,.1f})\n"
        )
        handle.write(
            f"- Video observed-behaviour sensitivity: "
            f"{video_observed_behaviour_delay_h:,.1f} pedestrian-hours\n"
        )
        if arrivals:
            handle.write(
                f"- Aggregate average delay: {delay_h * 3600 / arrivals:.1f} "
                "seconds/person under 100% compliance; "
                f"{observed_compliance_delay_h * 3600 / arrivals:.1f} under "
                "the MCAV observed-compliance scenario; "
                f"{video_observed_behaviour_delay_h * 3600 / arrivals:.1f} "
                "under the video observed-behaviour sensitivity\n\n"
            )
        handle.write("## Site 516 included hours\n\n")
        handle.write("| Hour | Pedestrian arrivals | Delay pedestrian-h | Average delay s |\n")
        handle.write("|---:|---:|---:|---:|\n")
        for row in site_516:
            handle.write(
                f"| {row['hour']:02d}:00 | {row['mcav_person_arrivals_conditioned']:.1f} | "
                f"{row['mcav_person_delay_h_conditioned']:.2f} | {row['mcav_avg_delay_s_conditioned']:.1f} |\n"
            )


def main() -> None:
    delay_multipliers = load_delay_multipliers()
    movement_rows, unmatched = movement_hour_rows(delay_multipliers)
    site_rows = site_hour_rows(movement_rows)
    write_csv(MOVEMENT_HOUR_OUT, movement_rows)
    write_csv(SITE_HOUR_OUT, site_rows)
    write_summary(movement_rows, site_rows, unmatched, delay_multipliers)
    print(MOVEMENT_HOUR_OUT)
    print(SITE_HOUR_OUT)
    print(README_OUT)


if __name__ == "__main__":
    main()
