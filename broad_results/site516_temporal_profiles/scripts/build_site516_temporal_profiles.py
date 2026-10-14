#!/usr/bin/env python3
"""Estimate and plot site 516 diurnal, weekly, and seasonal pedestrian flows."""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "broad_results" / "site516_temporal_profiles"
EXTRACT = RESULTS / "extract"
FIGURES = ROOT / "paper" / "figures"
CALIBRATION = FIGURES / "paper2_peer_calibration_summary.csv"

ANALYSIS_DATE = date(2018, 9, 18)
WEEK_START = date(2018, 9, 14)
WEEK_END = date(2018, 9, 20)
SEASON_START = date(2017, 9, 1)
SEASON_END = date(2018, 8, 31)
EXPECTED_MOVEMENTS = ("1", "2", "3", "4")


def dates_between(start: date, end: date) -> list[date]:
    values = []
    current = start
    while current <= end:
        values.append(current)
        current += timedelta(days=1)
    return values


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            output = {}
            for field in fields:
                value = row.get(field, "")
                if isinstance(value, float):
                    output[field] = "" if not math.isfinite(value) else f"{value:.6f}"
                else:
                    output[field] = value
            writer.writerow(output)


def load_alpha() -> float:
    rows = read_csv(CALIBRATION)
    row = next((item for item in rows if item.get("source") == "pooled"), None)
    if row is None:
        raise RuntimeError(f"Pooled count adjustment not found in {CALIBRATION}")
    return float(row["count_alpha_mean"])


def classify(n: int, c: int, zero: int) -> str:
    zero_share = zero / n if n else None
    if n == 0:
        return "no_demands"
    if n < 5:
        return "sparse"
    if zero_share is not None and zero_share >= 0.50:
        return "zero_heavy"
    if c and c / (n + c) >= 0.75:
        return "censor_heavy"
    return "usable"


def load_records(days: list[date]) -> tuple[list[dict], list[dict], list[dict]]:
    observations: list[dict] = []
    censored: list[dict] = []
    statuses: list[dict] = []
    for day in days:
        day_text = day.strftime("%Y%m%d")
        folder = EXTRACT / day_text
        status_path = folder / f"site_processing_status_{day_text}.csv"
        obs_path = folder / f"walk_delay_observations_{day_text}.csv"
        cens_path = folder / f"walk_censored_intervals_{day_text}.csv"
        if not status_path.is_file():
            statuses.append({"date": day_text, "status": "missing_extract", "coverage_status": "unavailable", "error": "status file missing"})
            continue
        status_rows = read_csv(status_path)
        status = status_rows[0] if status_rows else {"status": "empty_status", "error": "status file empty"}
        if status.get("status") != "ok" or not obs_path.is_file() or not cens_path.is_file():
            statuses.append({"date": day_text, **status, "coverage_status": "unavailable"})
            continue
        day_observations = read_csv(obs_path)
        day_censored = read_csv(cens_path)
        event_hours = {int(row["hour"]) for row in day_observations + day_censored}
        missing_core_hours = sorted(set(range(8, 19)) - event_hours)
        statuses.append(
            {
                "date": day_text,
                **status,
                "event_hours": len(event_hours),
                "missing_core_hours": ";".join(str(hour) for hour in missing_core_hours),
                "coverage_status": "complete_core" if not missing_core_hours else "partial_core",
            }
        )
        for row in day_observations:
            row["date"] = day_text
            observations.append(row)
        for row in day_censored:
            row["date"] = day_text
            censored.append(row)
    return observations, censored, statuses


def build_day_models(observations: list[dict], censored: list[dict], alpha: float) -> list[dict]:
    delays: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    censors: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    reasons: dict[tuple[str, str, int], Counter] = defaultdict(Counter)
    for row in observations:
        key = (row["date"], row["movement"], int(row["hour"]))
        delays[key].append(float(row["delay_s"]))
    for row in censored:
        key = (row["date"], row["movement"], int(row["hour"]))
        censors[key].append(float(row["censored_wait_s"]))
        reasons[key][row.get("censor_reason", "")] += 1
    keys = set(delays) | set(censors)
    automatic = {}
    for key in keys:
        n = len(delays[key])
        c = len(censors[key])
        active = reasons[key]["active_on"]
        automatic[key] = n == 0 and c >= 8 and active / c >= 0.80
    site_hour_automatic = {}
    date_hours = {(key[0], key[2]) for key in keys}
    for day_text, hour in date_hours:
        hour_keys = [key for key in keys if key[0] == day_text and key[2] == hour]
        site_hour_automatic[(day_text, hour)] = bool(hour_keys) and sum(automatic[key] for key in hour_keys) / len(hour_keys) >= 0.50

    rows = []
    for key in sorted(keys):
        day_text, movement, hour = key
        ds = delays[key]
        cs = censors[key]
        n = len(ds)
        c = len(cs)
        zero = sum(value == 0 for value in ds)
        exposure = sum(ds) + sum(cs)
        quality = classify(n, c, zero)
        auto = automatic[key] or site_hour_automatic[(day_text, hour)]
        recommended = quality == "usable" and not auto and exposure > 0
        rate = n / exposure * 3600.0 if exposure > 0 else None
        rows.append(
            {
                "date": day_text,
                "day_of_week": datetime.strptime(day_text, "%Y%m%d").strftime("%A"),
                "movement": movement,
                "hour": hour,
                "observed_demands": n,
                "censored_intervals": c,
                "zero_delay_demands": zero,
                "total_exposure_s": exposure,
                "quality_flag": quality,
                "automatic_service_exclusion": "yes" if auto else "no",
                "recommended": "yes" if recommended else "no",
                "effective_arrivals_per_hour": rate if rate is not None else float("nan"),
                "estimated_pedestrians_per_hour": alpha * rate if recommended and rate is not None else float("nan"),
            }
        )
    return rows


def build_diurnal(models: list[dict]) -> list[dict]:
    day_text = ANALYSIS_DATE.strftime("%Y%m%d")
    rows = []
    for hour in range(24):
        observed = [row for row in models if row["date"] == day_text and row["hour"] == hour]
        included = [row for row in observed if row["recommended"] == "yes"]
        estimate = sum(row["estimated_pedestrians_per_hour"] for row in included)
        status = "complete" if len(included) == len(EXPECTED_MOVEMENTS) else "partial" if included else "not_estimable"
        rows.append(
            {
                "date": day_text,
                "hour": hour,
                "observed_movement_rows": len(observed),
                "included_movement_rows": len(included),
                "coverage_status": status,
                "estimated_pedestrians": estimate if included else float("nan"),
            }
        )
    return rows


def build_week(models: list[dict]) -> tuple[list[dict], set[tuple[str, int]]]:
    days = dates_between(WEEK_START, WEEK_END)
    recommended_by_date = {}
    for day in days:
        day_text = day.strftime("%Y%m%d")
        recommended_by_date[day_text] = {
            (row["movement"], row["hour"])
            for row in models
            if row["date"] == day_text and row["recommended"] == "yes"
        }
    common = set.intersection(*recommended_by_date.values()) if recommended_by_date else set()
    rows = []
    for day in days:
        day_text = day.strftime("%Y%m%d")
        included = [row for row in models if row["date"] == day_text and row["recommended"] == "yes"]
        common_rows = [row for row in included if (row["movement"], row["hour"]) in common]
        rows.append(
            {
                "date": day_text,
                "day_of_week": day.strftime("%A"),
                "all_usable_estimated_pedestrians": sum(row["estimated_pedestrians_per_hour"] for row in included),
                "included_movement_hours": len(included),
                "common_support_estimated_pedestrians": sum(row["estimated_pedestrians_per_hour"] for row in common_rows),
                "common_support_movement_hours": len(common),
                "is_analysis_day": "yes" if day == ANALYSIS_DATE else "no",
            }
        )
    return rows, common


def build_monthly(observations: list[dict], censored: list[dict], statuses: list[dict], models: list[dict], alpha: float) -> tuple[list[dict], set[tuple[str, int]]]:
    season_days = dates_between(SEASON_START, SEASON_END)
    day_month = {day.strftime("%Y%m%d"): day.strftime("%Y-%m") for day in season_days}
    complete_dates = {
        row["date"]
        for row in statuses
        if row.get("status") == "ok" and row.get("coverage_status") == "complete_core"
    }
    excluded = {
        (row["date"], row["movement"], row["hour"])
        for row in models
        if row["automatic_service_exclusion"] == "yes"
    }
    delays: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    censors: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for row in observations:
        month = day_month.get(row["date"])
        key_day = (row["date"], row["movement"], int(row["hour"]))
        if month and row["date"] in complete_dates and key_day not in excluded:
            delays[(month, row["movement"], int(row["hour"]))].append(float(row["delay_s"]))
    for row in censored:
        month = day_month.get(row["date"])
        key_day = (row["date"], row["movement"], int(row["hour"]))
        if month and row["date"] in complete_dates and key_day not in excluded:
            censors[(month, row["movement"], int(row["hour"]))].append(float(row["censored_wait_s"]))
    months = [day.strftime("%Y-%m") for day in season_days if day.day == 1]
    months = list(dict.fromkeys(months))
    eligible: dict[str, dict[tuple[str, int], float]] = {}
    for month in months:
        cell_rates = {}
        cells = {(movement, hour) for (cell_month, movement, hour) in set(delays) | set(censors) if cell_month == month}
        for movement, hour in cells:
            ds = delays[(month, movement, hour)]
            cs = censors[(month, movement, hour)]
            n = len(ds)
            c = len(cs)
            zero = sum(value == 0 for value in ds)
            exposure = sum(ds) + sum(cs)
            if classify(n, c, zero) == "usable" and exposure > 0:
                cell_rates[(movement, hour)] = alpha * n / exposure * 3600.0
        eligible[month] = cell_rates
    common = set.intersection(*(set(eligible[month]) for month in months)) if months else set()
    rows = []
    for month in months:
        date_value = datetime.strptime(month, "%Y-%m").date()
        expected_days = sum(1 for day in season_days if day.strftime("%Y-%m") == month)
        processed_days = sum(1 for day in season_days if day.strftime("%Y-%m") == month and day.strftime("%Y%m%d") in complete_dates)
        common_total = sum(eligible[month][cell] for cell in common)
        all_total = sum(eligible[month].values())
        rows.append(
            {
                "month": month,
                "month_label": date_value.strftime("%b %Y"),
                "expected_days": expected_days,
                "processed_days": processed_days,
                "eligible_movement_hours": len(eligible[month]),
                "common_support_movement_hours": len(common),
                "typical_day_estimated_pedestrians_common_support": common_total,
                "typical_day_estimated_pedestrians_all_eligible": all_total,
            }
        )
    return rows, common


def write_summary(alpha: float, diurnal: list[dict], weekly: list[dict], monthly: list[dict], statuses: list[dict], week_common: set, month_common: set) -> None:
    ok = sum(row.get("status") == "ok" for row in statuses)
    expected = len(statuses)
    partial = [row for row in statuses if row.get("coverage_status") == "partial_core"]
    main_total = sum(row["estimated_pedestrians"] for row in diurnal if math.isfinite(row["estimated_pedestrians"]))
    main_hours = [row["hour"] for row in diurnal if row["coverage_status"] != "not_estimable"]
    missing_hours = [row["hour"] for row in diurnal if row["coverage_status"] == "not_estimable"]
    lines = [
        "# Site 516 pedestrian temporal profiles",
        "",
        f"- Count adjustment from the companion calibration study: {alpha:.6f}.",
        f"- Successfully decoded site-days: {ok}/{expected}.",
        f"- Decoded but seasonally excluded for missing core daytime hours: {len(partial)} ({', '.join(row['date'] for row in partial) if partial else 'none'}).",
        f"- Main analysis day: {ANALYSIS_DATE.isoformat()}.",
        f"- Main-day estimate over usable movement-hours: {main_total:,.1f} pedestrian crossings.",
        f"- Main-day clock hours with at least one usable movement: {', '.join(f'{hour:02d}' for hour in main_hours)}.",
        f"- Main-day clock hours not estimable under the fixed movement-hour screens: {', '.join(f'{hour:02d}' for hour in missing_hours)}.",
        f"- Seven-day comparison uses {len(week_common)} movement-hour cells that pass the screens on every day.",
        f"- Seasonal comparison uses {len(month_common)} movement-hour cells estimable in every month.",
        f"- Seasonal window: {SEASON_START.isoformat()} through {SEASON_END.isoformat()} (12 complete calendar months).",
        "",
        "## Week",
        "",
        "| Date | Day | Common-support estimate | All usable-hour estimate | Included movement-hours |",
        "|---|---|---:|---:|---:|",
    ]
    for row in weekly:
        lines.append(
            f"| {row['date']} | {row['day_of_week']} | {row['common_support_estimated_pedestrians']:,.1f} | "
            f"{row['all_usable_estimated_pedestrians']:,.1f} | {row['included_movement_hours']} |"
        )
    lines += ["", "## Seasonal typical day", "", "| Month | Processed days | Common-support estimate |", "|---|---:|---:|"]
    for row in monthly:
        lines.append(
            f"| {row['month_label']} | {row['processed_days']}/{row['expected_days']} | "
            f"{row['typical_day_estimated_pedestrians_common_support']:,.1f} |"
        )
    lines += [
        "",
        "## Missingness and interpretation",
        "",
        "Hourly estimates that fail the pre-specified actuation/censoring screens are missing, not zero. For a like-for-like weekly comparison, every plotted day uses identical screened movement and clock-hour coverage. Movement 1 is omitted at 07:00, 08:00, 19:00, and 21:00 because it records fewer than five actuations in those hours on at least one day, principally Sunday; movements 2--4 remain included. This is a sparse-call screen, not evidence of a phase change or missing data. Coverage-dependent totals using every usable observation remain in the CSV as a diagnostic but are not plotted. Two otherwise decodable seasonal dates have gaps within 08:00--18:59 and are excluded from their monthly pools. Monthly rates pool first-actuation and right-censoring exposure across the remaining complete-core days within each month, then use the same pedestrian movements and clock hours in all 12 months. The seasonal values are typical-day estimates on this common coverage, not monthly totals.",
        "",
    ]
    (RESULTS / "site516_temporal_profiles_summary.md").write_text("\n".join(lines), encoding="utf-8")


def plot(diurnal: list[dict], weekly: list[dict], monthly: list[dict]) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    blue = "#0072B2"
    orange = "#E69F00"
    grey = "#777777"
    light_grey = "#E6E6E6"
    dark = "#222222"

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 10.5,
            "axes.labelsize": 9.5,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
        }
    )
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 9.1), constrained_layout=False)
    fig.subplots_adjust(left=0.105, right=0.985, top=0.955, bottom=0.115, hspace=0.50)

    ax = axes[0]
    hours = [row["hour"] for row in diurnal]
    values = [row["estimated_pedestrians"] if math.isfinite(row["estimated_pedestrians"]) else 0 for row in diurnal]
    colors = [blue if row["coverage_status"] == "complete" else orange if row["coverage_status"] == "partial" else light_grey for row in diurnal]
    bars = ax.bar(hours, values, color=colors, edgecolor=dark, linewidth=0.45, width=0.82)
    ymax = max(values) * 1.18
    for row, bar in zip(diurnal, bars):
        if row["coverage_status"] == "not_estimable":
            ax.axvspan(row["hour"] - 0.41, row["hour"] + 0.41, color=light_grey, alpha=0.55, zorder=0)
            ax.text(row["hour"], ymax * 0.035, "×", color=grey, ha="center", va="bottom", fontsize=9)
        elif row["coverage_status"] == "partial":
            bar.set_hatch("///")
    total = sum(value for value in values)
    estimable = sum(row["coverage_status"] != "not_estimable" for row in diurnal)
    ax.text(0.995, 0.82, f"{total:,.0f} crossings over {estimable} estimable hours", transform=ax.transAxes, ha="right", va="top", fontsize=8.5)
    ax.set_title("A. Main-day diurnal profile: Tuesday 18 September 2018", loc="left", fontweight="bold")
    ax.set_ylabel("Estimated crossings/h")
    ax.set_xlabel("Hour beginning")
    ax.set_xlim(-0.7, 23.7)
    ax.set_ylim(0, ymax)
    ax.set_xticks(range(0, 24, 2))
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.plot([], [], color=blue, linewidth=7, label="All four movements")
    ax.plot([], [], color=orange, linewidth=7, label="Partial movement coverage")
    ax.plot([], [], color=light_grey, marker="x", linestyle="", markeredgecolor=grey, label="Not estimable")
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.02), fontsize=7.8, handlelength=1.2, columnspacing=1.4)

    ax = axes[1]
    x = list(range(len(weekly)))
    common_values = [row["common_support_estimated_pedestrians"] for row in weekly]
    for idx in (1, 2):
        ax.axvspan(idx - 0.5, idx + 0.5, color=light_grey, alpha=0.45, zorder=0)
    bar_colors = [orange if row["is_analysis_day"] == "yes" else blue for row in weekly]
    ax.bar(x, common_values, color=bar_colors, edgecolor=dark, linewidth=0.5, width=0.68)
    for idx, value in enumerate(common_values):
        ax.text(idx, value + max(common_values) * 0.025, f"{value:,.0f}", ha="center", va="bottom", fontsize=7.8, color=dark)
    ax.set_title("B. Day of week: 14–20 September 2018 (identical screened coverage)", loc="left", fontweight="bold")
    ax.set_ylabel("Estimated crossings/day")
    ax.set_xticks(x, [row["day_of_week"][:3] + "\n" + row["date"][6:8] for row in weekly])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
    ax.set_ylim(0, max(common_values) * 1.16)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.set_axisbelow(True)

    ax = axes[2]
    x = list(range(len(monthly)))
    values = [row["typical_day_estimated_pedestrians_common_support"] for row in monthly]
    ax.plot(x, values, color=blue, marker="o", markersize=4.8, linewidth=1.8)
    labels = [datetime.strptime(row["month"], "%Y-%m").strftime("%b\n%y") for row in monthly]
    for idx, row in enumerate(monthly):
        if row["processed_days"] != row["expected_days"]:
            ax.text(idx, values[idx] + 35, f"{row['processed_days']}/{row['expected_days']} days", ha="center", va="bottom", fontsize=7.2, color=orange)
    ax.set_title("C. Seasonal profile: September 2017–August 2018 (same coverage each month)", loc="left", fontweight="bold")
    ax.set_ylabel("Typical-day estimated crossings")
    ax.set_xticks(x, labels)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
    span = max(values) - min(values)
    ax.set_ylim(min(values) - span * 0.18, max(values) + span * 0.16)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.set_axisbelow(True)

    fig.text(
        0.105,
        0.018,
        "Blank hourly cells are not zeros. Weekly bars use the same pedestrian crossing movements during the same "
        "clock hours each day. Monthly estimates pool valid days and use the same movements and hours in all 12 months.",
        ha="left",
        va="bottom",
        fontsize=7.6,
        color=dark,
        wrap=True,
    )
    for suffix in ("pdf", "png", "jpeg"):
        target = RESULTS / f"site516_pedestrian_temporal_profiles.{suffix}"
        kwargs = {"bbox_inches": "tight"}
        if suffix in ("png", "jpeg"):
            kwargs["dpi"] = 300
        fig.savefig(target, **kwargs)
        figure_target = FIGURES / f"paper2_site516_pedestrian_temporal_profiles.{suffix}"
        fig.savefig(figure_target, **kwargs)
    plt.close(fig)


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    all_days = sorted(set(dates_between(SEASON_START, SEASON_END) + dates_between(WEEK_START, WEEK_END)))
    alpha = load_alpha()
    observations, censored, statuses = load_records(all_days)
    if sum(row.get("status") == "ok" for row in statuses) != len(all_days):
        missing = [row["date"] for row in statuses if row.get("status") != "ok"]
        raise RuntimeError(f"Incomplete extraction; unavailable dates: {missing[:20]}")
    models = build_day_models(observations, censored, alpha)
    diurnal = build_diurnal(models)
    weekly, week_common = build_week(models)
    monthly, month_common = build_monthly(observations, censored, statuses, models, alpha)

    write_csv(
        RESULTS / "site516_movement_hour_estimates.csv",
        models,
        [
            "date", "day_of_week", "movement", "hour", "observed_demands", "censored_intervals",
            "zero_delay_demands", "total_exposure_s", "quality_flag", "automatic_service_exclusion",
            "recommended", "effective_arrivals_per_hour", "estimated_pedestrians_per_hour",
        ],
    )
    write_csv(
        RESULTS / "site516_diurnal_20180918.csv",
        diurnal,
        ["date", "hour", "observed_movement_rows", "included_movement_rows", "coverage_status", "estimated_pedestrians"],
    )
    write_csv(
        RESULTS / "site516_week_20180914_20180920.csv",
        weekly,
        [
            "date", "day_of_week", "all_usable_estimated_pedestrians", "included_movement_hours",
            "common_support_estimated_pedestrians", "common_support_movement_hours", "is_analysis_day",
        ],
    )
    write_csv(
        RESULTS / "site516_monthly_201709_201808.csv",
        monthly,
        [
            "month", "month_label", "expected_days", "processed_days", "eligible_movement_hours",
            "common_support_movement_hours", "typical_day_estimated_pedestrians_common_support",
            "typical_day_estimated_pedestrians_all_eligible",
        ],
    )
    write_csv(
        RESULTS / "site516_processing_status.csv",
        statuses,
        ["date", "site", "region", "status", "points", "walk_event_points", "observations", "censored", "event_hours", "missing_core_hours", "coverage_status", "error"],
    )
    write_summary(alpha, diurnal, weekly, monthly, statuses, week_common, month_common)
    plot(diurnal, weekly, monthly)
    print(RESULTS / "site516_pedestrian_temporal_profiles.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
