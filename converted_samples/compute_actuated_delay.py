#!/usr/bin/env python3
import bisect
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


META = ["site", "region", "street1", "street2", "suburb", "lon", "lat", "movement"]


def f(value, places=3):
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return f"{value:.{places}f}"


def read_estimates(path):
    out = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out[(row["site"], row["movement"])] = row
    return out


def read_windows(path):
    green_starts = defaultdict(list)
    nonwalk_starts = defaultdict(list)
    totals = defaultdict(
        lambda: {
            "walk_s": 0.0,
            "nonwalk_s": 0.0,
            "coverage_start_s": None,
            "coverage_end_s": None,
            "meta": None,
        }
    )
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["site"], row["movement"])
            totals[key]["meta"] = row
            duration = float(row["duration_s"])
            start = float(row["start_s"])
            end = float(row["end_s"])
            totals[key]["coverage_start_s"] = (
                start
                if totals[key]["coverage_start_s"] is None
                else min(totals[key]["coverage_start_s"], start)
            )
            totals[key]["coverage_end_s"] = (
                end
                if totals[key]["coverage_end_s"] is None
                else max(totals[key]["coverage_end_s"], end)
            )
            if row["state_desc"] == "Green":
                totals[key]["walk_s"] += duration
                green_starts[key].append(start)
            elif row["state_desc"] == "Not green":
                totals[key]["nonwalk_s"] += duration
                nonwalk_starts[key].append(start)
    for starts in green_starts.values():
        starts.sort()
    for starts in nonwalk_starts.values():
        starts.sort()
    return green_starts, nonwalk_starts, totals


def read_observations(path):
    out = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["site"], row["movement"])
            out[key].append(row)
    return out


def aggregate(estimates, green_starts, nonwalk_starts, totals, observations):
    rows = []
    cycle_rows = []
    for key, estimate in sorted(estimates.items(), key=lambda item: (int(item[0][0]), int(item[0][1]))):
        if key not in totals:
            continue
        walk_s = totals[key]["walk_s"]
        nonwalk_s = totals[key]["nonwalk_s"]
        observed_s = walk_s + nonwalk_s
        starts = green_starts.get(key, [])
        closed_starts = nonwalk_starts.get(key, [])
        service_lags = []
        unmatched = 0
        first_by_interval = {}
        for obs in observations.get(key, []):
            acceptance = float(obs["acceptance_start_s"])
            demand = float(obs["demand_on_s"])
            existing = first_by_interval.get(acceptance)
            if existing is None or demand < float(existing["demand_on_s"]):
                first_by_interval[acceptance] = obs

        plugin_count = 0.0
        plugin_delay = 0.0
        plugin_extra = 0.0
        plugin_walk_arrivals = 0.0
        truncated_cycles = 0
        for acceptance, obs in sorted(first_by_interval.items()):
            demand_s = float(obs["demand_on_s"])
            latency = max(demand_s - acceptance, 0.5)
            next_closed_index = bisect.bisect_right(closed_starts, acceptance + 0.5)
            if next_closed_index < len(closed_starts):
                cycle_end = closed_starts[next_closed_index]
                truncated = False
            else:
                cycle_end = totals[key]["coverage_end_s"]
                truncated = True
            if cycle_end is None or cycle_end <= acceptance:
                unmatched += 1
                continue
            cycle_exposure = cycle_end - acceptance
            implied_count = cycle_exposure / latency
            plugin_count += implied_count
            plugin_extra += max(implied_count - 1.0, 0.0)
            if truncated:
                truncated_cycles += 1

            idx = bisect.bisect_left(starts, demand_s)
            if idx >= len(starts):
                unmatched += 1
                service_lag = None
                delay_contribution = 0.0
                walk_arrivals = 0.0
            else:
                service_lag = starts[idx] - demand_s
            if service_lag is not None and service_lag < 0:
                unmatched += 1
                service_lag = None
                delay_contribution = 0.0
                walk_arrivals = 0.0
            elif service_lag is not None:
                service_lags.append(service_lag)
                delay_contribution = service_lag + service_lag**2 / (2.0 * latency)
                plugin_delay += delay_contribution
                walk_arrivals = max(cycle_end - starts[idx], 0.0) / latency
                plugin_walk_arrivals += walk_arrivals

            cycle_rows.append(
                {
                    "site": estimate["site"],
                    "region": estimate["region"],
                    "street1": estimate["street1"],
                    "street2": estimate["street2"],
                    "suburb": estimate["suburb"],
                    "lon": estimate["lon"],
                    "lat": estimate["lat"],
                    "movement": estimate["movement"],
                    "quality_flag": estimate["quality_flag"],
                    "hour": int(acceptance // 3600),
                    "fdw_onset_s": acceptance,
                    "first_actuation_s": demand_s,
                    "first_actuation_latency_s": demand_s - acceptance,
                    "effective_latency_s": latency,
                    "cycle_end_s": cycle_end,
                    "full_cycle_exposure_s": cycle_exposure,
                    "cycle_exposure_truncated_at_coverage_end": "yes" if truncated else "no",
                    "implied_pedestrians_full_cycle": implied_count,
                    "next_walk_s": starts[idx] if service_lag is not None else "",
                    "first_actuation_to_walk_s": service_lag if service_lag is not None else "",
                    "unexpanded_delay_s": delay_contribution,
                    "implied_walk_period_pedestrians": walk_arrivals,
                }
            )

        arrivals_per_hour = plugin_count * 3600.0 / observed_s if observed_s else 0.0
        total_delay_s = plugin_delay
        rate_based_arrivals = plugin_count
        conditioned_arrivals = plugin_count

        row = {
            "site": estimate["site"],
            "region": estimate["region"],
            "street1": estimate["street1"],
            "street2": estimate["street2"],
            "suburb": estimate["suburb"],
            "lon": estimate["lon"],
            "lat": estimate["lat"],
            "movement": estimate["movement"],
            "quality_flag": estimate["quality_flag"],
            "estimator": "cycle_plugin_first_actuation_full_cycle",
            "effective_ped_arrivals_per_hour": arrivals_per_hour,
            "walk_s": walk_s,
            "nonwalk_s": nonwalk_s,
            "walk_time_share": walk_s / observed_s if observed_s else None,
            "actuations_matched_to_next_walk": len(service_lags),
            "actuations_unmatched": unmatched,
            "cycle_plugin_first_actuation_cycles": len(first_by_interval),
            "cycle_plugin_truncated_cycles": truncated_cycles,
            "cycle_plugin_full_cycle_exposure_s": sum(
                row["full_cycle_exposure_s"]
                for row in cycle_rows
                if row["site"] == estimate["site"] and row["movement"] == estimate["movement"]
            ),
            "mean_actuation_to_walk_s": statistics.fmean(service_lags) if service_lags else None,
            "median_actuation_to_walk_s": statistics.median(service_lags) if service_lags else None,
            "p75_actuation_to_walk_s": percentile(service_lags, 0.75),
            "expected_extra_arrivals_after_actuation": plugin_extra,
            "estimated_arrivals_during_walk": plugin_walk_arrivals,
            "estimated_arrivals_rate_based_period": rate_based_arrivals,
            "estimated_arrivals_conditioned_period": conditioned_arrivals,
            "total_delay_ped_s_conditioned": total_delay_s,
            "total_delay_ped_h_conditioned": total_delay_s / 3600.0,
            "avg_delay_s_rate_based_denominator": total_delay_s / rate_based_arrivals if rate_based_arrivals else None,
            "avg_delay_s_conditioned_denominator": total_delay_s / conditioned_arrivals if conditioned_arrivals else None,
        }
        rows.append(row)
    return rows, cycle_rows


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def write_rows(path, rows):
    fields = [
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "lon",
        "lat",
        "movement",
        "quality_flag",
        "estimator",
        "effective_ped_arrivals_per_hour",
        "walk_s",
        "nonwalk_s",
        "walk_time_share",
        "actuations_matched_to_next_walk",
        "actuations_unmatched",
        "cycle_plugin_first_actuation_cycles",
        "cycle_plugin_truncated_cycles",
        "cycle_plugin_full_cycle_exposure_s",
        "mean_actuation_to_walk_s",
        "median_actuation_to_walk_s",
        "p75_actuation_to_walk_s",
        "expected_extra_arrivals_after_actuation",
        "estimated_arrivals_during_walk",
        "estimated_arrivals_rate_based_period",
        "estimated_arrivals_conditioned_period",
        "total_delay_ped_s_conditioned",
        "total_delay_ped_h_conditioned",
        "avg_delay_s_rate_based_denominator",
        "avg_delay_s_conditioned_denominator",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            formatted = row.copy()
            for key, value in list(formatted.items()):
                if isinstance(value, float):
                    formatted[key] = f(value)
            writer.writerow(formatted)


def main():
    if len(sys.argv) != 6:
        print(
            "Usage: compute_actuated_delay.py <movement-day-estimates.csv> <ped-walk-windows.csv> <walk-delay-observations.csv> <output-dir> <date>",
            file=sys.stderr,
        )
        return 2
    estimates_path, windows_path, observations_path, output_dir, date = sys.argv[1:]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    estimates = read_estimates(estimates_path)
    green_starts, nonwalk_starts, totals = read_windows(windows_path)
    observations = read_observations(observations_path)
    rows, cycle_rows = aggregate(
        estimates, green_starts, nonwalk_starts, totals, observations
    )

    all_path = output_dir / f"movement_actuated_flow_delay_{date}.csv"
    example_path = output_dir / f"example_intersection_site_516_actuated_flow_delay_{date}.csv"
    write_rows(all_path, rows)
    write_rows(example_path, [row for row in rows if row["site"] == "516"])
    cycle_path = output_dir / f"cycle_first_actuation_estimates_{date}.csv"
    if cycle_rows:
        with open(cycle_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(cycle_rows[0].keys()))
            writer.writeheader()
            for row in cycle_rows:
                writer.writerow(
                    {key: f(value) if isinstance(value, float) else value for key, value in row.items()}
                )
    print(all_path)
    print(example_path)
    print(cycle_path)


if __name__ == "__main__":
    raise SystemExit(main())
