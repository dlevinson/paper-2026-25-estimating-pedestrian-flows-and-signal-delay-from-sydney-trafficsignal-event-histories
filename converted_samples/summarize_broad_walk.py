#!/usr/bin/env python3
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


META_FIELDS = ["site", "region", "street1", "street2", "suburb", "lon", "lat", "movement"]


def fnum(value, places=3):
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return f"{value:.{places}f}"


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


def read_observations(path):
    records = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["site"] = int(row["site"])
            row["movement"] = int(row["movement"])
            row["hour"] = int(row["hour"])
            row["delay_s"] = float(row["delay_s"])
            row["lon"] = float(row["lon"])
            row["lat"] = float(row["lat"])
            records.append(row)
    return records


def read_censored(path):
    records = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["site"] = int(row["site"])
            row["movement"] = int(row["movement"])
            row["hour"] = int(row["hour"])
            row["censored_wait_s"] = float(row["censored_wait_s"])
            row["lon"] = float(row["lon"])
            row["lat"] = float(row["lat"])
            records.append(row)
    return records


def key_for(row, include_hour):
    base = tuple(row[field] for field in META_FIELDS)
    if include_hour:
        return base + (row["hour"],)
    return base


def aggregate(observations, censored, include_hour):
    groups = {}
    delays = defaultdict(list)
    censors = defaultdict(list)

    for row in observations:
        key = key_for(row, include_hour)
        groups.setdefault(key, {field: row[field] for field in META_FIELDS})
        if include_hour:
            groups[key]["hour"] = row["hour"]
        delays[key].append(row["delay_s"])

    for row in censored:
        key = key_for(row, include_hour)
        groups.setdefault(key, {field: row[field] for field in META_FIELDS})
        if include_hour:
            groups[key]["hour"] = row["hour"]
        censors[key].append(row["censored_wait_s"])

    rows = []
    for key, meta in groups.items():
        ds = delays.get(key, [])
        cs = censors.get(key, [])
        exposure = sum(ds) + sum(cs)
        n = len(ds)
        c = len(cs)
        zero = sum(1 for value in ds if value == 0)
        positive = [value for value in ds if value > 0]
        zero_share = zero / n if n else None
        lambda_per_s = n / exposure if exposure > 0 else None
        mle_groups_per_hour = 3600 * lambda_per_s if lambda_per_s is not None else None
        uncensored_mean = statistics.fmean(ds) if ds else None
        uncensored_groups_per_hour = 3600 / uncensored_mean if uncensored_mean and uncensored_mean > 0 else None
        positive_mean = statistics.fmean(positive) if positive else None
        positive_groups_per_hour = 3600 / positive_mean if positive_mean and positive_mean > 0 else None

        if n == 0:
            quality = "no_demands"
        elif n < 5:
            quality = "sparse"
        elif zero_share is not None and zero_share >= 0.5:
            quality = "zero_heavy"
        elif c > 0 and c / (n + c) >= 0.75:
            quality = "censor_heavy"
        else:
            quality = "usable"

        out = dict(meta)
        out.update(
            {
                "observed_demands": n,
                "censored_intervals": c,
                "zero_delay_demands": zero,
                "zero_delay_share": zero_share,
                "total_exposure_s": exposure,
                "mean_delay_uncensored_s": uncensored_mean,
                "median_delay_uncensored_s": statistics.median(ds) if ds else None,
                "p25_delay_uncensored_s": percentile(ds, 0.25),
                "p75_delay_uncensored_s": percentile(ds, 0.75),
                "mean_positive_delay_s": positive_mean,
                "mle_effective_arrivals_per_hour": mle_groups_per_hour,
                "uncensored_mean_arrivals_per_hour": uncensored_groups_per_hour,
                "positive_only_arrivals_per_hour": positive_groups_per_hour,
                "quality_flag": quality,
            }
        )
        rows.append(out)

    sort_fields = ["site", "movement"] + (["hour"] if include_hour else [])
    rows.sort(key=lambda row: tuple(row[field] for field in sort_fields))
    return rows


def write_rows(path, rows, include_hour):
    fieldnames = META_FIELDS.copy()
    if include_hour:
        fieldnames.append("hour")
    fieldnames += [
        "observed_demands",
        "censored_intervals",
        "zero_delay_demands",
        "zero_delay_share",
        "total_exposure_s",
        "mean_delay_uncensored_s",
        "median_delay_uncensored_s",
        "p25_delay_uncensored_s",
        "p75_delay_uncensored_s",
        "mean_positive_delay_s",
        "mle_effective_arrivals_per_hour",
        "uncensored_mean_arrivals_per_hour",
        "positive_only_arrivals_per_hour",
        "quality_flag",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            formatted = row.copy()
            for field in fieldnames:
                if isinstance(formatted.get(field), float):
                    formatted[field] = fnum(formatted[field])
            writer.writerow(formatted)


def site_summary(day_rows):
    by_site = defaultdict(list)
    for row in day_rows:
        by_site[row["site"]].append(row)
    out = []
    for site, rows in sorted(by_site.items()):
        first = rows[0]
        usable = [row for row in rows if row["quality_flag"] == "usable"]
        zero_heavy = [row for row in rows if row["quality_flag"] == "zero_heavy"]
        total_demands = sum(row["observed_demands"] for row in rows)
        total_censored = sum(row["censored_intervals"] for row in rows)
        estimated = [row["mle_effective_arrivals_per_hour"] for row in rows if row["mle_effective_arrivals_per_hour"] is not None]
        out.append(
            {
                "site": site,
                "region": first["region"],
                "street1": first["street1"],
                "street2": first["street2"],
                "suburb": first["suburb"],
                "lon": first["lon"],
                "lat": first["lat"],
                "pedestrian_movements": len(rows),
                "usable_movements": len(usable),
                "zero_heavy_movements": len(zero_heavy),
                "observed_demands": total_demands,
                "censored_intervals": total_censored,
                "mean_movement_arrivals_per_hour": statistics.fmean(estimated) if estimated else None,
                "max_movement_arrivals_per_hour": max(estimated) if estimated else None,
            }
        )
    return out


def write_site_summary(path, rows):
    fieldnames = [
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "lon",
        "lat",
        "pedestrian_movements",
        "usable_movements",
        "zero_heavy_movements",
        "observed_demands",
        "censored_intervals",
        "mean_movement_arrivals_per_hour",
        "max_movement_arrivals_per_hour",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            formatted = row.copy()
            for field in fieldnames:
                if isinstance(formatted.get(field), float):
                    formatted[field] = fnum(formatted[field])
            writer.writerow(formatted)


def choose_example_site(site_rows):
    candidates = [
        row
        for row in site_rows
        if row["usable_movements"] >= 4 and row["observed_demands"] >= 1000 and row["zero_heavy_movements"] <= 1
    ]
    if not candidates:
        candidates = [row for row in site_rows if row["pedestrian_movements"] >= 4 and row["observed_demands"] >= 1000]
    if not candidates:
        candidates = site_rows
    return max(candidates, key=lambda row: (row["usable_movements"], row["observed_demands"]))


def write_report(path, date, observations, censored, day_rows, hour_rows, site_rows, status_path, example_site):
    flags = defaultdict(int)
    for row in day_rows:
        flags[row["quality_flag"]] += 1
    sites_with_ped = {row["site"] for row in day_rows}
    all_estimates = [row["mle_effective_arrivals_per_hour"] for row in day_rows if row["mle_effective_arrivals_per_hour"] is not None]
    usable_estimates = [
        row["mle_effective_arrivals_per_hour"]
        for row in day_rows
        if row["quality_flag"] == "usable" and row["mle_effective_arrivals_per_hour"] is not None
    ]
    hourly_usable = [
        row["mle_effective_arrivals_per_hour"]
        for row in hour_rows
        if row["quality_flag"] == "usable" and row["mle_effective_arrivals_per_hour"] is not None
    ]

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"# Pedestrian Actuation Summary for {date}\n\n")
        handle.write(f"- Observed demand-delay records: {len(observations):,}\n")
        handle.write(f"- Right-censored no-demand intervals: {len(censored):,}\n")
        handle.write(f"- Site-movement combinations with pedestrian data: {len(day_rows):,}\n")
        handle.write(f"- Sites with pedestrian data: {len(sites_with_ped):,}\n")
        handle.write(f"- Processing status file: `{status_path}`\n\n")
        handle.write("## Movement Quality Flags\n\n")
        for flag in sorted(flags):
            handle.write(f"- {flag}: {flags[flag]:,}\n")
        handle.write("\n")
        handle.write("## Effective Arrival Rate Distribution\n\n")
        handle.write("Daily site-movement estimates use the censored exponential MLE and are actuation-arrival units per hour, not calibrated person counts.\n\n")
        if all_estimates:
            handle.write(f"- All estimable movements, median: {statistics.median(all_estimates):.1f}/h\n")
            handle.write(f"- All estimable movements, p25-p75: {percentile(all_estimates, 0.25):.1f}-{percentile(all_estimates, 0.75):.1f}/h\n")
            handle.write(f"- All estimable movements, max: {max(all_estimates):.1f}/h\n")
        if usable_estimates:
            handle.write(f"- Usable daily movements, median: {statistics.median(usable_estimates):.1f}/h\n")
            handle.write(f"- Usable daily movements, p25-p75: {percentile(usable_estimates, 0.25):.1f}-{percentile(usable_estimates, 0.75):.1f}/h\n")
        if hourly_usable:
            handle.write(f"- Usable movement-hour estimates, median: {statistics.median(hourly_usable):.1f}/h\n")
            handle.write(f"- Usable movement-hour p25-p75: {percentile(hourly_usable, 0.25):.1f}-{percentile(hourly_usable, 0.75):.1f}/h\n")
        handle.write("\n")
        handle.write("## Example Intersection\n\n")
        handle.write(
            f"Selected site {example_site['site']} ({example_site['street1']} / {example_site['street2']}, "
            f"{example_site['suburb']}) because it has {example_site['usable_movements']} usable pedestrian movements "
            f"and {example_site['observed_demands']:,} observed demand-delay records.\n"
        )


def main():
    if len(sys.argv) != 4:
        print("Usage: summarize_broad_walk.py <observations.csv> <censored.csv> <output-dir>", file=sys.stderr)
        return 2

    observations_path = Path(sys.argv[1])
    censored_path = Path(sys.argv[2])
    output_dir = Path(sys.argv[3])
    output_dir.mkdir(parents=True, exist_ok=True)
    date = observations_path.stem.rsplit("_", 1)[-1]

    observations = read_observations(observations_path)
    censored = read_censored(censored_path)
    day_rows = aggregate(observations, censored, include_hour=False)
    hour_rows = aggregate(observations, censored, include_hour=True)
    site_rows = site_summary(day_rows)
    example_site = choose_example_site(site_rows)

    day_path = output_dir / f"movement_day_estimates_{date}.csv"
    hour_path = output_dir / f"movement_hour_estimates_{date}.csv"
    site_path = output_dir / f"site_day_summary_{date}.csv"
    example_path = output_dir / f"example_intersection_site_{example_site['site']}_{date}.csv"
    report_path = output_dir / f"network_summary_{date}.md"

    write_rows(day_path, day_rows, include_hour=False)
    write_rows(hour_path, hour_rows, include_hour=True)
    write_site_summary(site_path, site_rows)

    example_rows = [row for row in hour_rows if row["site"] == example_site["site"]]
    write_rows(example_path, example_rows, include_hour=True)
    write_report(report_path, date, observations, censored, day_rows, hour_rows, site_rows, "site_processing_status_" + date + ".csv", example_site)

    print(day_path)
    print(hour_path)
    print(site_path)
    print(example_path)
    print(report_path)


if __name__ == "__main__":
    raise SystemExit(main())
