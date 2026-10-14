#!/usr/bin/env python3
import bisect
import csv
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


MIN_ACTIVE_ON_CENSORS = 8
MIN_ACTIVE_ON_CENSOR_SHARE = 0.80
SITE_HOUR_EXCLUDE_SHARE = 0.50
RECURRING_MIN_DAYS = 3
RECURRING_EXCLUDE_SHARE = 0.80
SCHEDULED_MIN_CALLS = 100
SCHEDULED_MIN_MATCH_SHARE = 0.95
SCHEDULED_MIN_HOURS = 6
SCHEDULED_MAX_P75_CALL_TO_WALK_S = 10.0


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def inferred_date(path):
    match = re.search(r"(20\d{6})", Path(path).name)
    return match.group(1) if match else ""


def f(value):
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.6f}"
    return value


def write_rows(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: f(row.get(field, "")) for field in fieldnames})


def key_from(row, fallback_date):
    return (
        row.get("date") or fallback_date,
        row.get("period") or "",
        row["site"],
        row.get("region", ""),
        row.get("street1", ""),
        row.get("street2", ""),
        row.get("suburb", ""),
        row["movement"],
        int(row["hour"]),
    )


def linear_quantile(values, probability):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def load_walk_starts(path):
    starts = defaultdict(list)
    if path is None:
        return starts
    for row in read_rows(path):
        if row.get("state_desc") != "Green":
            continue
        starts[(row["site"], row["movement"])].append(float(row["start_s"]))
    for values in starts.values():
        values.sort()
    return starts


def build_flags(observations_path, censored_path, walk_windows_path=None):
    obs_date = inferred_date(observations_path)
    cens_date = inferred_date(censored_path)
    groups = {}
    delays = defaultdict(list)
    censors = defaultdict(list)
    censor_reasons = defaultdict(Counter)
    walk_starts = load_walk_starts(walk_windows_path)
    hourly_call_to_walk = defaultdict(list)
    movement_call_to_walk = defaultdict(list)
    movement_observed_calls = Counter()
    movement_demand_hours = defaultdict(set)
    movement_sources = {}

    for row in read_rows(observations_path):
        key = key_from(row, obs_date)
        groups.setdefault(key, row)
        delays[key].append(float(row["delay_s"]))
        movement_key = key[:-1]
        movement_sources.setdefault(movement_key, row)
        movement_observed_calls[movement_key] += 1
        movement_demand_hours[movement_key].add(key[-1])
        starts = walk_starts.get((row["site"], row["movement"]), [])
        if starts and row.get("demand_on_s") not in (None, ""):
            demand = float(row["demand_on_s"])
            index = bisect.bisect_left(starts, demand)
            if index < len(starts):
                lag = starts[index] - demand
                if lag >= 0:
                    hourly_call_to_walk[key].append(lag)
                    movement_call_to_walk[movement_key].append(lag)

    for row in read_rows(censored_path):
        key = key_from(row, cens_date)
        groups.setdefault(key, row)
        wait = float(row["censored_wait_s"])
        censors[key].append(wait)
        censor_reasons[key][row.get("censor_reason", "")] += 1

    scheduled_rows = []
    scheduled_by_movement = {}
    movement_keys = sorted(
        set(movement_observed_calls) | set(movement_call_to_walk),
        key=lambda item: (item[0], int(item[2]), int(item[7])),
    )
    for key in movement_keys:
        calls = movement_observed_calls[key]
        lags = movement_call_to_walk.get(key, [])
        match_share = len(lags) / calls if calls else 0.0
        hours = len(movement_demand_hours.get(key, set()))
        p75 = linear_quantile(lags, 0.75)
        scheduled = (
            calls >= SCHEDULED_MIN_CALLS
            and match_share >= SCHEDULED_MIN_MATCH_SHARE
            and hours >= SCHEDULED_MIN_HOURS
            and p75 is not None
            and p75 <= SCHEDULED_MAX_P75_CALL_TO_WALK_S
        )
        source = movement_sources[key]
        summary = {
            "date": key[0],
            "period": key[1],
            "site": key[2],
            "region": key[3],
            "street1": key[4],
            "street2": key[5],
            "suburb": key[6],
            "movement": key[7],
            "observed_demands": calls,
            "matched_calls_to_next_walk": len(lags),
            "matched_call_share": match_share,
            "hours_with_demand": hours,
            "mean_call_to_walk_s": statistics.fmean(lags) if lags else None,
            "median_call_to_walk_s": statistics.median(lags) if lags else None,
            "p75_call_to_walk_s": p75,
            "scheduled_call_candidate": "yes" if scheduled else "no",
            "rule": (
                f"calls>={SCHEDULED_MIN_CALLS};match_share>={SCHEDULED_MIN_MATCH_SHARE:.2f};"
                f"hours>={SCHEDULED_MIN_HOURS};p75_call_to_walk<="
                f"{SCHEDULED_MAX_P75_CALL_TO_WALK_S:.0f}s"
            ),
        }
        scheduled_rows.append(summary)
        scheduled_by_movement[key] = summary

    rows = []
    for key in sorted(groups, key=lambda item: (item[0], int(item[2]), item[8], int(item[7]))):
        ds = delays.get(key, [])
        cs = censors.get(key, [])
        service_lags = hourly_call_to_walk.get(key, [])
        reasons = censor_reasons.get(key, Counter())
        active_on = reasons.get("active_on", 0)
        censored_total = len(cs)
        observed = len(ds)
        active_share = active_on / censored_total if censored_total else 0.0
        total_exposure = sum(ds) + sum(cs)
        no_demand_repeated_service = (
            observed == 0
            and active_on >= MIN_ACTIVE_ON_CENSORS
            and active_share >= MIN_ACTIVE_ON_CENSOR_SHARE
        )
        scheduled_call = (
            scheduled_by_movement.get(key[:-1], {}).get("scheduled_call_candidate") == "yes"
        )
        exclude_movement_hour = no_demand_repeated_service or scheduled_call
        likely_usable_actuation = observed > 0 and not scheduled_call
        if no_demand_repeated_service:
            flag = "candidate_auto_served_or_demand_suppressed"
        elif scheduled_call:
            flag = "candidate_scheduled_or_forced_call"
        elif observed == 0 and censored_total > 0:
            flag = "zero_demand_sparse_or_low_service"
        elif observed > 0:
            flag = "demand_observed"
        else:
            flag = "no_walk_demand_evidence"

        source = groups[key]
        rows.append(
            {
                "date": key[0],
                "period": key[1],
                "site": key[2],
                "region": key[3],
                "street1": key[4],
                "street2": key[5],
                "suburb": key[6],
                "movement": key[7],
                "hour": key[8],
                "observed_demands": observed,
                "censored_intervals": censored_total,
                "active_on_censored_intervals": active_on,
                "active_on_censor_share": active_share,
                "end_of_file_censors": reasons.get("end_of_file", 0),
                "total_exposure_s": total_exposure,
                "mean_delay_s": statistics.fmean(ds) if ds else None,
                "mean_censored_wait_s": statistics.fmean(cs) if cs else None,
                "mle_arrivals_per_hour": 3600.0 * observed / total_exposure if total_exposure > 0 else None,
                "calls_matched_to_next_walk": len(service_lags),
                "mean_call_to_walk_s": statistics.fmean(service_lags) if service_lags else None,
                "median_call_to_walk_s": statistics.median(service_lags) if service_lags else None,
                "p75_call_to_walk_s": linear_quantile(service_lags, 0.75),
                "no_demand_repeated_walk_service": "yes" if no_demand_repeated_service else "no",
                "scheduled_call_movement_day": "yes" if scheduled_call else "no",
                "exclude_movement_hour": "yes" if exclude_movement_hour else "no",
                "likely_usable_actuation_hour": "yes" if likely_usable_actuation else "no",
                "flag": flag,
            }
        )
    return rows, scheduled_rows


def site_hour_summary(movement_rows):
    groups = defaultdict(list)
    for row in movement_rows:
        key = (
            row["date"],
            row["period"],
            row["site"],
            row["region"],
            row["street1"],
            row["street2"],
            row["suburb"],
            row["hour"],
        )
        groups[key].append(row)

    rows = []
    for key, group in sorted(groups.items(), key=lambda item: (item[0][0], int(item[0][2]), item[0][7])):
        movement_count = len(group)
        candidate_count = sum(1 for row in group if row["no_demand_repeated_walk_service"] == "yes")
        scheduled_count = sum(1 for row in group if row["scheduled_call_movement_day"] == "yes")
        observed_demands = sum(row["observed_demands"] for row in group)
        active_on = sum(row["active_on_censored_intervals"] for row in group)
        candidate_share = candidate_count / movement_count if movement_count else 0.0
        exclude = candidate_count > 0 and candidate_share >= SITE_HOUR_EXCLUDE_SHARE
        rows.append(
            {
                "date": key[0],
                "period": key[1],
                "site": key[2],
                "region": key[3],
                "street1": key[4],
                "street2": key[5],
                "suburb": key[6],
                "hour": key[7],
                "movement_count": movement_count,
                "candidate_auto_served_movements": candidate_count,
                "candidate_auto_served_movement_share": candidate_share,
                "candidate_scheduled_call_movements": scheduled_count,
                "observed_demands_all_movements": observed_demands,
                "active_on_censored_all_movements": active_on,
                "exclude_site_hour": "yes" if exclude else "no",
            }
        )
    return rows


def recurring_schedule(site_hour_rows, movement_rows):
    site_hour_groups = defaultdict(list)
    for row in site_hour_rows:
        key = (row["site"], row["region"], row["street1"], row["street2"], row["suburb"], row["period"], row["hour"])
        site_hour_groups[key].append(row)

    movement_groups = defaultdict(list)
    for row in movement_rows:
        key = (
            row["site"],
            row["region"],
            row["street1"],
            row["street2"],
            row["suburb"],
            row["period"],
            row["hour"],
            row["movement"],
        )
        movement_groups[key].append(row)

    site_hour_out = []
    for key, rows in sorted(site_hour_groups.items(), key=lambda item: (int(item[0][0]), item[0][5], item[0][6])):
        days_seen = len(rows)
        days_excluded = sum(1 for row in rows if row["exclude_site_hour"] == "yes")
        exclude_share = days_excluded / days_seen if days_seen else 0.0
        observed = sum(row["observed_demands_all_movements"] for row in rows)
        active = sum(row["active_on_censored_all_movements"] for row in rows)
        recurring = days_seen >= RECURRING_MIN_DAYS and exclude_share >= RECURRING_EXCLUDE_SHARE
        site_hour_out.append(
            {
                "site": key[0],
                "region": key[1],
                "street1": key[2],
                "street2": key[3],
                "suburb": key[4],
                "period": key[5],
                "hour": key[6],
                "days_seen": days_seen,
                "days_site_hour_excluded": days_excluded,
                "site_hour_exclusion_share": exclude_share,
                "observed_demands_all_days": observed,
                "active_on_censored_all_days": active,
                "recurring_exclusion_recommended": "yes" if recurring else "no",
            }
        )

    movement_out = []
    for key, rows in sorted(movement_groups.items(), key=lambda item: (int(item[0][0]), item[0][5], item[0][6], int(item[0][7]))):
        days_seen = len(rows)
        days_candidate = sum(1 for row in rows if row["no_demand_repeated_walk_service"] == "yes")
        candidate_share = days_candidate / days_seen if days_seen else 0.0
        observed = sum(row["observed_demands"] for row in rows)
        active = sum(row["active_on_censored_intervals"] for row in rows)
        recurring = days_seen >= RECURRING_MIN_DAYS and candidate_share >= RECURRING_EXCLUDE_SHARE
        movement_out.append(
            {
                "site": key[0],
                "region": key[1],
                "street1": key[2],
                "street2": key[3],
                "suburb": key[4],
                "period": key[5],
                "hour": key[6],
                "movement": key[7],
                "days_seen": days_seen,
                "days_candidate_auto_served": days_candidate,
                "candidate_auto_served_share": candidate_share,
                "observed_demands_all_days": observed,
                "active_on_censored_all_days": active,
                "recurring_exclusion_recommended": "yes" if recurring else "no",
            }
        )
    return site_hour_out, movement_out


def write_report(
    path,
    movement_rows,
    scheduled_rows,
    site_hour_rows,
    recurring_site_hours,
    recurring_movements,
):
    movement_total = len(movement_rows)
    movement_candidates = sum(1 for row in movement_rows if row["no_demand_repeated_walk_service"] == "yes")
    scheduled_candidates = [row for row in scheduled_rows if row["scheduled_call_candidate"] == "yes"]
    scheduled_hour_exclusions = sum(
        1 for row in movement_rows if row["scheduled_call_movement_day"] == "yes"
    )
    recommended_movement_exclusions = sum(
        1 for row in movement_rows if row["exclude_movement_hour"] == "yes"
    )
    site_hour_total = len(site_hour_rows)
    site_hour_excluded = sum(1 for row in site_hour_rows if row["exclude_site_hour"] == "yes")
    recurring_site_excluded = [row for row in recurring_site_hours if row["recurring_exclusion_recommended"] == "yes"]
    recurring_movement_excluded = [row for row in recurring_movements if row["recurring_exclusion_recommended"] == "yes"]
    by_site = Counter(row["site"] for row in recurring_site_excluded)

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# Auto-Served Pedestrian Phase Flags\n\n")
        handle.write("This flags SCATS pedestrian movement-hours where Walk service repeats but no ")
        handle.write("pedestrian demand bit is logged. Such rows are not reliable for estimating ")
        handle.write("pedestrian arrivals from actuation latency. It also identifies movement-days ")
        handle.write("with many calls concentrated immediately before Walk, which is a high-confidence ")
        handle.write("signature of scheduled, forced, or otherwise non-arrival-generated demand.\n\n")
        handle.write("Default movement-hour candidate rule:\n\n")
        handle.write(f"- observed pedestrian demands = 0\n")
        handle.write(f"- active-on censored intervals >= {MIN_ACTIVE_ON_CENSORS}\n")
        handle.write(f"- active-on censors / all censors >= {MIN_ACTIVE_ON_CENSOR_SHARE:.2f}\n\n")
        handle.write("Scheduled-call movement-day rule:\n\n")
        handle.write(f"- observed calls >= {SCHEDULED_MIN_CALLS}\n")
        handle.write(f"- calls matched to a following Walk / observed calls >= {SCHEDULED_MIN_MATCH_SHARE:.2f}\n")
        handle.write(f"- hours with observed calls >= {SCHEDULED_MIN_HOURS}\n")
        handle.write(
            f"- 75th-percentile call-to-Walk time <= {SCHEDULED_MAX_P75_CALL_TO_WALK_S:.0f} seconds\n\n"
        )
        handle.write("Default site-hour exclusion rule:\n\n")
        handle.write(f"- candidate movements / active pedestrian movements >= {SITE_HOUR_EXCLUDE_SHARE:.2f}\n\n")
        handle.write("Recurring schedule rule:\n\n")
        handle.write(f"- days seen >= {RECURRING_MIN_DAYS}\n")
        handle.write(f"- exclusion share >= {RECURRING_EXCLUDE_SHARE:.2f}\n\n")
        handle.write("## Counts\n\n")
        handle.write(f"- Movement-hours analysed: {movement_total:,}\n")
        handle.write(f"- Candidate demand-not-informative movement-hours: {movement_candidates:,}\n")
        handle.write(f"- Candidate scheduled-call movement-days: {len(scheduled_candidates):,}\n")
        handle.write(f"- Movement-hours excluded by scheduled-call rule: {scheduled_hour_exclusions:,}\n")
        handle.write(f"- Total recommended movement-hour exclusions: {recommended_movement_exclusions:,}\n")
        handle.write(f"- Site-hours analysed: {site_hour_total:,}\n")
        handle.write(f"- Site-hours recommended for row-level exclusion: {site_hour_excluded:,}\n")
        handle.write(f"- Recurring site-hour schedule exclusions: {len(recurring_site_excluded):,}\n")
        handle.write(f"- Recurring movement-hour schedule exclusions: {len(recurring_movement_excluded):,}\n\n")
        handle.write("## Recurring Site-Hour Exclusions by Site\n\n")
        for site, count in sorted(by_site.items(), key=lambda item: int(item[0])):
            example = next(row for row in recurring_site_excluded if row["site"] == site)
            handle.write(f"- Site {site} {example['street1']} / {example['street2']}: {count} period-hour blocks\n")
        handle.write("\n## Scheduled-Call Movement-Day Candidates\n\n")
        for row in scheduled_candidates:
            handle.write(
                f"- Site {row['site']} movement {row['movement']} {row['street1']} / "
                f"{row['street2']}: {row['observed_demands']} calls, "
                f"{row['hours_with_demand']} hours, p75 call-to-Walk "
                f"{row['p75_call_to_walk_s']:.1f} s\n"
            )


def main():
    if len(sys.argv) not in (4, 5):
        print(
            "Usage: flag_auto_served_ped_phases.py <observations.csv> <censored.csv> "
            "[walk_windows.csv] <output-dir>",
            file=sys.stderr,
        )
        return 2

    observations_path = Path(sys.argv[1])
    censored_path = Path(sys.argv[2])
    walk_windows_path = Path(sys.argv[3]) if len(sys.argv) == 5 else None
    output_dir = Path(sys.argv[4]) if len(sys.argv) == 5 else Path(sys.argv[3])
    output_dir.mkdir(parents=True, exist_ok=True)

    movement_rows, scheduled_rows = build_flags(
        observations_path,
        censored_path,
        walk_windows_path,
    )
    site_hour_rows = site_hour_summary(movement_rows)
    recurring_site_hours, recurring_movements = recurring_schedule(site_hour_rows, movement_rows)

    movement_fields = [
        "date",
        "period",
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "movement",
        "hour",
        "observed_demands",
        "censored_intervals",
        "active_on_censored_intervals",
        "active_on_censor_share",
        "end_of_file_censors",
        "total_exposure_s",
        "mean_delay_s",
        "mean_censored_wait_s",
        "mle_arrivals_per_hour",
        "calls_matched_to_next_walk",
        "mean_call_to_walk_s",
        "median_call_to_walk_s",
        "p75_call_to_walk_s",
        "no_demand_repeated_walk_service",
        "scheduled_call_movement_day",
        "exclude_movement_hour",
        "likely_usable_actuation_hour",
        "flag",
    ]
    site_hour_fields = [
        "date",
        "period",
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "hour",
        "movement_count",
        "candidate_auto_served_movements",
        "candidate_auto_served_movement_share",
        "candidate_scheduled_call_movements",
        "observed_demands_all_movements",
        "active_on_censored_all_movements",
        "exclude_site_hour",
    ]
    recurring_site_fields = [
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "period",
        "hour",
        "days_seen",
        "days_site_hour_excluded",
        "site_hour_exclusion_share",
        "observed_demands_all_days",
        "active_on_censored_all_days",
        "recurring_exclusion_recommended",
    ]
    recurring_movement_fields = [
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "period",
        "hour",
        "movement",
        "days_seen",
        "days_candidate_auto_served",
        "candidate_auto_served_share",
        "observed_demands_all_days",
        "active_on_censored_all_days",
        "recurring_exclusion_recommended",
    ]
    scheduled_fields = [
        "date",
        "period",
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "movement",
        "observed_demands",
        "matched_calls_to_next_walk",
        "matched_call_share",
        "hours_with_demand",
        "mean_call_to_walk_s",
        "median_call_to_walk_s",
        "p75_call_to_walk_s",
        "scheduled_call_candidate",
        "rule",
    ]

    write_rows(output_dir / "auto_served_movement_hour_flags.csv", movement_rows, movement_fields)
    write_rows(output_dir / "auto_served_site_hour_flags.csv", site_hour_rows, site_hour_fields)
    write_rows(output_dir / "scheduled_call_movement_day_flags.csv", scheduled_rows, scheduled_fields)
    write_rows(output_dir / "auto_served_recurring_site_hour_schedule.csv", recurring_site_hours, recurring_site_fields)
    write_rows(output_dir / "auto_served_recurring_movement_hour_schedule.csv", recurring_movements, recurring_movement_fields)
    write_rows(
        output_dir / "recommended_site_hour_exclusions.csv",
        [row for row in site_hour_rows if row["exclude_site_hour"] == "yes"],
        site_hour_fields,
    )
    write_rows(
        output_dir / "recommended_movement_hour_exclusions.csv",
        [row for row in movement_rows if row["exclude_movement_hour"] == "yes"],
        movement_fields,
    )
    write_report(
        output_dir / "auto_served_flag_readme.md",
        movement_rows,
        scheduled_rows,
        site_hour_rows,
        recurring_site_hours,
        recurring_movements,
    )

    print(output_dir / "auto_served_movement_hour_flags.csv")
    print(output_dir / "auto_served_site_hour_flags.csv")
    print(output_dir / "auto_served_recurring_site_hour_schedule.csv")
    print(output_dir / "scheduled_call_movement_day_flags.csv")
    print(output_dir / "recommended_site_hour_exclusions.csv")


if __name__ == "__main__":
    raise SystemExit(main())
