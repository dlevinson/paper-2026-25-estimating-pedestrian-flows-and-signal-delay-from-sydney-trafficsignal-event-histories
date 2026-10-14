#!/usr/bin/env python3
import csv
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


CYCLE_ITEMS = {
    "Nominal cycle length": "nominal_cycle",
    "Active cycle length": "active_cycle",
    "Actual cycle": "actual_cycle",
}


def f(value, places=3):
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return f"{value:.{places}f}"


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, skipinitialspace=True)
        for row in reader:
            yield {key.strip(): value.strip() for key, value in row.items()}


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


def hms_to_s(value):
    hour, minute, second = [int(part) for part in value.split(":")]
    return hour * 3600 + minute * 60 + second


def summarize_intervals(values):
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "p25": None,
            "p75": None,
            "min": None,
            "max": None,
        }
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p25": percentile(values, 0.25),
        "p75": percentile(values, 0.75),
        "min": min(values),
        "max": max(values),
    }


def read_site_day(path):
    out = {}
    for row in read_csv(path):
        out[row["site"]] = row
    return out


def read_stats(path):
    stats = defaultdict(dict)
    for row in read_csv(path):
        item = row["Data item"]
        if item not in CYCLE_ITEMS:
            continue
        prefix = CYCLE_ITEMS[item]
        site = row["Site"]
        stats[site][f"{prefix}_frequency"] = int(row["Frequency"])
        stats[site][f"{prefix}_min_s"] = float(row["Minimum"])
        stats[site][f"{prefix}_max_s"] = float(row["Maximum"])
        stats[site][f"{prefix}_avg_s"] = float(row["Average"])
        stats[site][f"{prefix}_total_s"] = float(row["Total"])
    return stats


def read_hourly_estimates(path):
    site_hour_flow = defaultdict(float)
    movement_hour = {}
    for row in read_csv(path):
        value = row.get("mle_effective_arrivals_per_hour", "")
        if value == "":
            continue
        site = row["site"]
        hour = int(row["hour"])
        movement = row["movement"]
        flow = float(value)
        if row.get("quality_flag") == "usable":
            site_hour_flow[(site, hour)] += flow
        movement_hour[(site, movement, hour)] = row
    return site_hour_flow, movement_hour


def read_observations(path):
    site_total = Counter()
    site_hour = Counter()
    movement_hour = Counter()
    movement_total = Counter()
    for row in read_csv(path):
        site = row["site"]
        movement = row["movement"]
        hour = int(row["hour"])
        site_total[site] += 1
        site_hour[(site, hour)] += 1
        movement_hour[(site, movement, hour)] += 1
        movement_total[(site, movement)] += 1
    return site_total, site_hour, movement_total, movement_hour


def read_walk_windows(path):
    starts = defaultdict(list)
    durations = defaultdict(list)
    for row in read_csv(path):
        if row["state_desc"] != "Green":
            continue
        key = (row["site"], row["movement"])
        starts[key].append(float(row["start_s"]))
        durations[key].append(float(row["duration_s"]))
    for values in starts.values():
        values.sort()
    return starts, durations


def site_walk_headways(starts):
    out = {}
    by_site = defaultdict(list)
    by_movement = {}
    for key, values in starts.items():
        intervals = [b - a for a, b in zip(values, values[1:])]
        by_movement[key] = summarize_intervals(intervals)
        by_site[key[0]].extend(intervals)
    for site, values in by_site.items():
        out[site] = summarize_intervals(values)
    return out, by_movement


def read_cycle_restarts(path):
    starts = []
    if not path.exists():
        return starts
    for row in read_csv(path):
        if row.get("Event") == "Cycle generator: restart":
            starts.append(hms_to_s(row["Time"]))
    return starts


def read_phase_starts(path, phase_name):
    starts = []
    if not path.exists():
        return starts
    for row in read_csv(path):
        phase = row.get("Phase", "").replace("<", "").replace(">", "")
        if phase == phase_name:
            starts.append(hms_to_s(row["Start"]))
    return starts


def intervals_starting_in_hour(starts, hour):
    start_s = hour * 3600
    end_s = (hour + 1) * 3600
    return [
        starts[index + 1] - starts[index]
        for index in range(len(starts) - 1)
        if start_s <= starts[index] < end_s and starts[index + 1] >= starts[index]
    ]


def write_rows(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            formatted = {}
            for field in fields:
                value = row.get(field, "")
                if isinstance(value, float):
                    formatted[field] = f(value)
                else:
                    formatted[field] = value
            writer.writerow(formatted)


def build_site_summary(site_day, stats, site_hour_flow, site_total, site_hour, site_walk_stats):
    rows = []
    for site, row in sorted(site_day.items(), key=lambda item: int(item[0])):
        flow_hours = {hour: flow for (s, hour), flow in site_hour_flow.items() if s == site}
        peak_hour = None
        peak_flow = None
        if flow_hours:
            peak_hour, peak_flow = max(flow_hours.items(), key=lambda item: (item[1], -item[0]))
        walk = site_walk_stats.get(site, {})
        out = {
            "site": site,
            "region": row["region"],
            "street1": row["street1"],
            "street2": row["street2"],
            "suburb": row["suburb"],
            "lon": row["lon"],
            "lat": row["lat"],
            "pedestrian_movements": row["pedestrian_movements"],
            "usable_movements": row["usable_movements"],
            "observed_actuations": int(row["observed_demands"]),
            "observed_actuations_per_hour_24h": int(row["observed_demands"]) / 24.0,
            "estimated_ped_flow_per_hour_all_movements": float(row["mean_movement_arrivals_per_hour"]) * int(row["pedestrian_movements"]),
            "peak_hour": peak_hour,
            "peak_hour_estimated_ped_flow_per_hour": peak_flow,
            "peak_hour_observed_actuations": site_hour.get((site, peak_hour), "") if peak_hour is not None else "",
            "walk_service_headway_count": walk.get("n", 0),
            "walk_service_headway_mean_s": walk.get("mean"),
            "walk_service_headway_median_s": walk.get("median"),
            "walk_service_headway_p25_s": walk.get("p25"),
            "walk_service_headway_p75_s": walk.get("p75"),
        }
        out.update(stats.get(site, {}))
        rows.append(out)
    return rows


def build_site_516_peak(
    site_day,
    stats,
    site_hour_flow,
    movement_hour_estimates,
    site_hour_obs,
    movement_hour_obs,
    movement_total_obs,
    starts,
    durations,
    events_path,
    phases_path,
):
    site = "516"
    peak_hour, peak_flow = max(
        ((hour, flow) for (s, hour), flow in site_hour_flow.items() if s == site),
        key=lambda item: (item[1], -item[0]),
    )
    cycle_restart_starts = read_cycle_restarts(events_path)
    phase_a_starts = read_phase_starts(phases_path, "A")
    cycle_restart_stats = summarize_intervals(intervals_starting_in_hour(cycle_restart_starts, peak_hour))
    phase_a_stats = summarize_intervals(intervals_starting_in_hour(phase_a_starts, peak_hour))

    site_row = site_day[site]
    rows = [{
        "site": site,
        "region": site_row["region"],
        "street1": site_row["street1"],
        "street2": site_row["street2"],
        "suburb": site_row["suburb"],
        "row_type": "site_total",
        "movement": "",
        "hour": peak_hour,
        "estimated_ped_flow_per_hour": peak_flow,
        "observed_actuations_in_hour": site_hour_obs[(site, peak_hour)],
        "observed_actuations_per_hour_24h": int(site_row["observed_demands"]) / 24.0,
        "daily_observed_actuations": int(site_row["observed_demands"]),
        "active_cycle_avg_s_daily": stats.get(site, {}).get("active_cycle_avg_s"),
        "nominal_cycle_avg_s_daily": stats.get(site, {}).get("nominal_cycle_avg_s"),
        "actual_cycle_avg_s_daily": stats.get(site, {}).get("actual_cycle_avg_s"),
        "peak_cycle_generator_interval_mean_s": cycle_restart_stats["mean"],
        "peak_cycle_generator_interval_median_s": cycle_restart_stats["median"],
        "peak_cycle_generator_interval_count": cycle_restart_stats["n"],
        "peak_a_phase_interval_mean_s": phase_a_stats["mean"],
        "peak_a_phase_interval_median_s": phase_a_stats["median"],
        "peak_a_phase_interval_count": phase_a_stats["n"],
        "peak_walk_service_headway_mean_s": "",
        "peak_walk_service_headway_median_s": "",
        "peak_walks": "",
        "daily_movement_actuations": "",
    }]

    for movement in sorted({movement for s, movement in starts if s == site}, key=int):
        key = (site, movement)
        hour_intervals = intervals_starting_in_hour(starts[key], peak_hour)
        hour_stats = summarize_intervals(hour_intervals)
        hour_walks = sum(1 for start in starts[key] if peak_hour * 3600 <= start < (peak_hour + 1) * 3600)
        estimate = movement_hour_estimates.get((site, movement, peak_hour), {})
        rows.append({
            "site": site,
            "region": site_row["region"],
            "street1": site_row["street1"],
            "street2": site_row["street2"],
            "suburb": site_row["suburb"],
            "row_type": "movement",
            "movement": movement,
            "hour": peak_hour,
            "estimated_ped_flow_per_hour": float(estimate["mle_effective_arrivals_per_hour"]) if estimate else "",
            "observed_actuations_in_hour": movement_hour_obs[(site, movement, peak_hour)],
            "observed_actuations_per_hour_24h": movement_total_obs[(site, movement)] / 24.0,
            "daily_observed_actuations": movement_total_obs[(site, movement)],
            "active_cycle_avg_s_daily": "",
            "nominal_cycle_avg_s_daily": "",
            "actual_cycle_avg_s_daily": "",
            "peak_cycle_generator_interval_mean_s": "",
            "peak_cycle_generator_interval_median_s": "",
            "peak_cycle_generator_interval_count": "",
            "peak_a_phase_interval_mean_s": "",
            "peak_a_phase_interval_median_s": "",
            "peak_a_phase_interval_count": "",
            "peak_walk_service_headway_mean_s": hour_stats["mean"],
            "peak_walk_service_headway_median_s": hour_stats["median"],
            "peak_walks": hour_walks,
            "daily_movement_actuations": movement_total_obs[(site, movement)],
        })
    return rows


def main():
    if len(sys.argv) != 3:
        print("Usage: compute_cycle_actuation_summary.py <broad-results-dir> <date>", file=sys.stderr)
        return 2

    results_dir = Path(sys.argv[1])
    date = sys.argv[2]

    site_day = read_site_day(results_dir / f"site_day_summary_{date}.csv")
    stats = read_stats(results_dir / f"site_stats_{date}.csv")
    site_hour_flow, movement_hour_estimates = read_hourly_estimates(results_dir / f"movement_hour_estimates_{date}.csv")
    site_total_obs, site_hour_obs, movement_total_obs, movement_hour_obs = read_observations(
        results_dir / f"walk_delay_observations_{date}.csv"
    )
    starts, durations = read_walk_windows(results_dir / f"ped_walk_windows_{date}.csv")
    site_walk_stats, movement_walk_stats = site_walk_headways(starts)

    site_rows = build_site_summary(site_day, stats, site_hour_flow, site_total_obs, site_hour_obs, site_walk_stats)
    site_fields = [
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "lon",
        "lat",
        "pedestrian_movements",
        "usable_movements",
        "observed_actuations",
        "observed_actuations_per_hour_24h",
        "estimated_ped_flow_per_hour_all_movements",
        "peak_hour",
        "peak_hour_estimated_ped_flow_per_hour",
        "peak_hour_observed_actuations",
        "active_cycle_frequency",
        "active_cycle_min_s",
        "active_cycle_max_s",
        "active_cycle_avg_s",
        "nominal_cycle_frequency",
        "nominal_cycle_min_s",
        "nominal_cycle_max_s",
        "nominal_cycle_avg_s",
        "actual_cycle_frequency",
        "actual_cycle_min_s",
        "actual_cycle_max_s",
        "actual_cycle_avg_s",
        "walk_service_headway_count",
        "walk_service_headway_mean_s",
        "walk_service_headway_median_s",
        "walk_service_headway_p25_s",
        "walk_service_headway_p75_s",
    ]
    site_path = results_dir / f"site_cycle_actuation_summary_{date}.csv"
    write_rows(site_path, site_rows, site_fields)

    script_dir = Path(__file__).resolve().parent
    peak_rows = build_site_516_peak(
        site_day,
        stats,
        site_hour_flow,
        movement_hour_estimates,
        site_hour_obs,
        movement_hour_obs,
        movement_total_obs,
        starts,
        durations,
        script_dir / "516_WILL_20180918_events.csv",
        script_dir / "516_WILL_20180918_phases.csv",
    )
    peak_fields = [
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "row_type",
        "movement",
        "hour",
        "estimated_ped_flow_per_hour",
        "observed_actuations_in_hour",
        "observed_actuations_per_hour_24h",
        "daily_observed_actuations",
        "active_cycle_avg_s_daily",
        "nominal_cycle_avg_s_daily",
        "actual_cycle_avg_s_daily",
        "peak_cycle_generator_interval_mean_s",
        "peak_cycle_generator_interval_median_s",
        "peak_cycle_generator_interval_count",
        "peak_a_phase_interval_mean_s",
        "peak_a_phase_interval_median_s",
        "peak_a_phase_interval_count",
        "peak_walk_service_headway_mean_s",
        "peak_walk_service_headway_median_s",
        "peak_walks",
        "daily_movement_actuations",
    ]
    peak_path = results_dir / f"site_516_peak_hour_cycle_actuation_{date}.csv"
    write_rows(peak_path, peak_rows, peak_fields)

    print(site_path)
    print(peak_path)


if __name__ == "__main__":
    raise SystemExit(main())
