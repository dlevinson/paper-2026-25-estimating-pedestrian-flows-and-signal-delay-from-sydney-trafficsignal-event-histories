#!/usr/bin/env python3
"""Apply paired empirical MCAV count and delay alpha distributions to SCATS.

The primary estimator pools first-actuation latencies and right-censored
no-actuation exposure within each movement-hour.  This script uses the 14
case-specific factors from the estimator-matched MCAV censored-Poisson model.
The unweighted case mean is the deterministic count alpha; the empirical paired
case distribution supplies stochastic count and delay bounds.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = ROOT / "broad_results" / "network_20180918"
VALIDATION_DIR = ROOT / "broad_results" / "validation" / "mcav_validation"
DATE = "20180918"

DAY_IN = RESULTS_DIR / f"movement_day_estimates_{DATE}.csv"
HOUR_IN = RESULTS_DIR / f"movement_hour_estimates_{DATE}.csv"
FLOW_DELAY_IN = RESULTS_DIR / f"movement_actuated_flow_delay_{DATE}.csv"
MAPPED_IN = RESULTS_DIR / f"movement_day_estimates_mapped_unique_{DATE}.csv"
MAPPED_GEOJSON_IN = RESULTS_DIR / f"movement_day_estimates_mapped_unique_{DATE}.geojson"
STABILITY_IN = VALIDATION_DIR / "mcav_model_stability_summary.csv"
CASE_IN = VALIDATION_DIR / "mcav_case_model_validation.csv"
COMPLIANCE_CASE_IN = VALIDATION_DIR / "mcav_compliance_scenario_by_case.csv"
MATCHED_MCAV_MODEL = "poisson_censored_implied_count_all_time"
NETWORK_RATE_FIELD = "mle_effective_arrivals_per_hour"
AUTO_MOVEMENT_EXCL_IN = (
    RESULTS_DIR / f"auto_served_flags_{DATE}" / "recommended_movement_hour_exclusions.csv"
)
AUTO_SITE_EXCL_IN = (
    RESULTS_DIR / f"auto_served_flags_{DATE}" / "recommended_site_hour_exclusions.csv"
)

HOUR_OUT = RESULTS_DIR / f"movement_hour_estimates_calibrated_mcav_{DATE}.csv"
DAY_OUT = RESULTS_DIR / f"movement_day_estimates_calibrated_mcav_{DATE}.csv"
FLOW_DELAY_OUT = RESULTS_DIR / f"movement_actuated_flow_delay_calibrated_mcav_{DATE}.csv"
SITE_OUT = RESULTS_DIR / f"site_summary_calibrated_mcav_{DATE}.csv"
MAPPED_OUT = RESULTS_DIR / f"movement_day_estimates_calibrated_mcav_mapped_unique_{DATE}.csv"
MAPPED_GEOJSON_OUT = RESULTS_DIR / f"movement_day_estimates_calibrated_mcav_mapped_unique_{DATE}.geojson"
README_OUT = RESULTS_DIR / f"mcav_calibrated_summary_{DATE}.md"


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: format_value(row.get(field, "")) for field in fieldnames})


def format_value(value):
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.6f}"
    return value


def as_float(row: dict, key: str) -> float:
    value = row.get(key, "")
    if value in ("", None):
        return 0.0
    return float(value)


def as_int(row: dict, key: str) -> int:
    value = row.get(key, "")
    if value in ("", None):
        return 0
    return int(float(value))


def movement_key(row: dict) -> tuple[str, str]:
    return str(row["site"]), str(row["movement"])


def movement_hour_key(row: dict) -> tuple[str, str, str]:
    return str(row["site"]), str(row["movement"]), str(int(float(row["hour"])))


def site_hour_key(row: dict) -> tuple[str, str]:
    return str(row["site"]), str(int(float(row["hour"])))


def linear_quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def load_mcav_multiplier() -> dict:
    case_alphas = []
    for row in read_csv(CASE_IN):
        actual = as_float(row, "actual_total_pedestrians")
        implied = as_float(row, MATCHED_MCAV_MODEL)
        if implied:
            case_alphas.append(actual / implied)
    if not case_alphas:
        raise RuntimeError(f"No MCAV case alphas found for: {MATCHED_MCAV_MODEL}")

    delay_alphas = [
        as_float(row, "delay_alpha_observed_actuation")
        for row in read_csv(COMPLIANCE_CASE_IN)
        if as_float(row, "delay_alpha_observed_actuation")
    ]
    observed_compliance_delay_alphas = [
        as_float(row, "delay_alpha_observed_compliance_scenario")
        for row in read_csv(COMPLIANCE_CASE_IN)
        if as_float(row, "delay_alpha_observed_compliance_scenario")
    ]
    if len(delay_alphas) != len(case_alphas):
        raise RuntimeError(
            "MCAV count and compliance-scenario delay factors must have the same case count"
        )
    if len(observed_compliance_delay_alphas) != len(case_alphas):
        raise RuntimeError(
            "MCAV count and observed-compliance delay factors must have the same case count"
        )

    for row in read_csv(STABILITY_IN):
        if row["model_key"] == MATCHED_MCAV_MODEL:
            return {
                "model_key": row["model_key"],
                "model": row["model"],
                "point": sum(case_alphas) / len(case_alphas),
                "lower": linear_quantile(case_alphas, 0.025),
                "upper": linear_quantile(case_alphas, 0.975),
                "case_min": min(case_alphas),
                "case_max": max(case_alphas),
                "case_p25": linear_quantile(case_alphas, 0.25),
                "case_median": linear_quantile(case_alphas, 0.50),
                "case_p75": linear_quantile(case_alphas, 0.75),
                "delay_point": sum(delay_alphas) / len(delay_alphas),
                "delay_lower": linear_quantile(delay_alphas, 0.025),
                "delay_upper": linear_quantile(delay_alphas, 0.975),
                "delay_case_min": min(delay_alphas),
                "delay_case_max": max(delay_alphas),
                "observed_compliance_delay_point": (
                    sum(observed_compliance_delay_alphas)
                    / len(observed_compliance_delay_alphas)
                ),
                "observed_compliance_delay_lower": linear_quantile(
                    observed_compliance_delay_alphas, 0.025
                ),
                "observed_compliance_delay_upper": linear_quantile(
                    observed_compliance_delay_alphas, 0.975
                ),
                "observed_compliance_delay_case_min": min(
                    observed_compliance_delay_alphas
                ),
                "observed_compliance_delay_case_max": max(
                    observed_compliance_delay_alphas
                ),
                "pooled_diagnostic": float(row["aggregate_calibration_multiplier"]),
                "pooled_bootstrap_lower": float(row["bootstrap_multiplier_p025"]),
                "pooled_bootstrap_upper": float(row["bootstrap_multiplier_p975"]),
                "ratio": float(row["aggregate_implied_to_actual_ratio"]),
                "ratio_lower": float(row["bootstrap_ratio_p025"]),
                "ratio_upper": float(row["bootstrap_ratio_p975"]),
            }
    raise RuntimeError(f"Matched MCAV multiplier not found: {MATCHED_MCAV_MODEL}")


def load_auto_flags() -> tuple[set[tuple[str, str, str]], set[tuple[str, str]]]:
    movement_hours = set()
    site_hours = set()
    if AUTO_MOVEMENT_EXCL_IN.exists():
        for row in read_csv(AUTO_MOVEMENT_EXCL_IN):
            movement_hours.add(movement_hour_key(row))
    if AUTO_SITE_EXCL_IN.exists():
        for row in read_csv(AUTO_SITE_EXCL_IN):
            site_hours.add(site_hour_key(row))
    return movement_hours, site_hours


def add_scaled(row: dict, source_key: str, prefix: str, mult: dict) -> None:
    base = as_float(row, source_key)
    row[f"{prefix}_effective"] = base
    row[f"{prefix}_mcav_person_point"] = base * mult["point"]
    row[f"{prefix}_mcav_person_low"] = base * mult["lower"]
    row[f"{prefix}_mcav_person_high"] = base * mult["upper"]


def add_delay_scaled(row: dict, source_key: str, prefix: str, mult: dict) -> None:
    """Scale unexpanded model delay by the compliance-scenario delay factor."""
    base = as_float(row, source_key)
    row[f"{prefix}_effective"] = base
    row[f"{prefix}_mcav_person_point"] = base * mult["delay_point"]
    row[f"{prefix}_mcav_person_low"] = base * mult["delay_lower"]
    row[f"{prefix}_mcav_person_high"] = base * mult["delay_upper"]


def calibrate_hour_rows(mult: dict, auto_mh: set, auto_sh: set) -> list[dict]:
    rows = []
    for row in read_csv(HOUR_IN):
        out = dict(row)
        mh_auto = movement_hour_key(row) in auto_mh
        sh_auto = site_hour_key(row) in auto_sh
        out["mcav_model"] = mult["model_key"]
        out["mcav_multiplier_point"] = mult["point"]
        out["mcav_multiplier_low"] = mult["lower"]
        out["mcav_multiplier_high"] = mult["upper"]
        out["mcav_delay_multiplier_point"] = mult["delay_point"]
        out["mcav_delay_multiplier_low"] = mult["delay_lower"]
        out["mcav_delay_multiplier_high"] = mult["delay_upper"]
        out["mcav_observed_compliance_delay_multiplier_point"] = mult[
            "observed_compliance_delay_point"
        ]
        out["mcav_observed_compliance_delay_multiplier_low"] = mult[
            "observed_compliance_delay_lower"
        ]
        out["mcav_observed_compliance_delay_multiplier_high"] = mult[
            "observed_compliance_delay_upper"
        ]
        out["auto_served_movement_hour_exclusion"] = "yes" if mh_auto else "no"
        out["auto_served_site_hour_exclusion"] = "yes" if sh_auto else "no"
        out["recommended_for_mcav_aggregate"] = (
            "yes"
            if row.get("quality_flag") == "usable" and not mh_auto and not sh_auto
            else "no"
        )
        add_scaled(out, NETWORK_RATE_FIELD, "arrivals_per_hour", mult)
        rows.append(out)
    return rows


def calibrate_day_rows(mult: dict, hour_rows: list[dict]) -> list[dict]:
    hour_groups = defaultdict(list)
    for row in hour_rows:
        hour_groups[movement_key(row)].append(row)

    out_rows = []
    for row in read_csv(DAY_IN):
        out = dict(row)
        group = hour_groups.get(movement_key(row), [])
        recommended = [r for r in group if r["recommended_for_mcav_aggregate"] == "yes"]
        auto_excluded = [
            r
            for r in group
            if r["auto_served_movement_hour_exclusion"] == "yes"
            or r["auto_served_site_hour_exclusion"] == "yes"
        ]
        nonusable = [r for r in group if r.get("quality_flag") != "usable"]
        add_scaled(out, NETWORK_RATE_FIELD, "day_model_arrivals_per_hour", mult)
        recommended_total_effective = sum(
            as_float(r, NETWORK_RATE_FIELD) for r in recommended
        )
        recommended_hours = len(recommended)
        out["hour_rows"] = len(group)
        out["usable_hour_rows"] = sum(1 for r in group if r.get("quality_flag") == "usable")
        out["recommended_hour_rows"] = recommended_hours
        out["auto_served_excluded_hour_rows"] = len(auto_excluded)
        out["nonusable_hour_rows"] = len(nonusable)
        out["recommended_observed_hours_effective_arrivals"] = recommended_total_effective
        out["recommended_observed_hours_mcav_person_point"] = recommended_total_effective * mult["point"]
        out["recommended_observed_hours_mcav_person_low"] = recommended_total_effective * mult["lower"]
        out["recommended_observed_hours_mcav_person_high"] = recommended_total_effective * mult["upper"]
        out["recommended_mean_hourly_mcav_person_point"] = (
            recommended_total_effective * mult["point"] / recommended_hours
            if recommended_hours
            else ""
        )
        out["recommended_for_mapping"] = (
            "yes"
            if row.get("quality_flag") == "usable" and len(auto_excluded) == 0
            else "review"
        )
        out["mcav_multiplier_point"] = mult["point"]
        out["mcav_multiplier_low"] = mult["lower"]
        out["mcav_multiplier_high"] = mult["upper"]
        out["mcav_delay_multiplier_point"] = mult["delay_point"]
        out["mcav_delay_multiplier_low"] = mult["delay_lower"]
        out["mcav_delay_multiplier_high"] = mult["delay_upper"]
        out["mcav_observed_compliance_delay_multiplier_point"] = mult[
            "observed_compliance_delay_point"
        ]
        out["mcav_observed_compliance_delay_multiplier_low"] = mult[
            "observed_compliance_delay_lower"
        ]
        out["mcav_observed_compliance_delay_multiplier_high"] = mult[
            "observed_compliance_delay_upper"
        ]
        out_rows.append(out)
    return out_rows


def calibrate_flow_delay_rows(mult: dict, day_rows: list[dict]) -> list[dict]:
    day_by_key = {movement_key(row): row for row in day_rows}
    rows = []
    for row in read_csv(FLOW_DELAY_IN):
        out = dict(row)
        day = day_by_key.get(movement_key(row), {})
        out["auto_served_excluded_hour_rows"] = day.get("auto_served_excluded_hour_rows", "")
        out["recommended_hour_rows"] = day.get("recommended_hour_rows", "")
        out["recommended_for_mcav_summary"] = (
            "yes"
            if row.get("quality_flag") == "usable"
            and str(day.get("auto_served_excluded_hour_rows", "0")) in ("0", "0.000000")
            else "no"
        )
        out["observed_period_h"] = (as_float(row, "walk_s") + as_float(row, "nonwalk_s")) / 3600.0
        out["mcav_multiplier_point"] = mult["point"]
        out["mcav_multiplier_low"] = mult["lower"]
        out["mcav_multiplier_high"] = mult["upper"]
        out["mcav_delay_multiplier_point"] = mult["delay_point"]
        out["mcav_delay_multiplier_low"] = mult["delay_lower"]
        out["mcav_delay_multiplier_high"] = mult["delay_upper"]
        out["mcav_observed_compliance_delay_multiplier_point"] = mult[
            "observed_compliance_delay_point"
        ]
        out["mcav_observed_compliance_delay_multiplier_low"] = mult[
            "observed_compliance_delay_lower"
        ]
        out["mcav_observed_compliance_delay_multiplier_high"] = mult[
            "observed_compliance_delay_upper"
        ]
        for source, prefix in [
            ("estimated_arrivals_rate_based_period", "rate_based_period_arrivals"),
            ("estimated_arrivals_conditioned_period", "conditioned_period_arrivals"),
            ("estimated_arrivals_during_walk", "arrivals_during_walk"),
            ("expected_extra_arrivals_after_actuation", "extra_arrivals_after_actuation"),
        ]:
            add_scaled(out, source, prefix, mult)
        add_delay_scaled(
            out,
            "total_delay_ped_h_conditioned",
            "total_delay_ped_h_conditioned",
            mult,
        )
        rows.append(out)
    return rows


def summarize_sites(flow_rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in flow_rows:
        groups[str(row["site"])].append(row)

    site_rows = []
    for site, rows in sorted(groups.items(), key=lambda item: int(item[0])):
        first = rows[0]
        included = [row for row in rows if row["recommended_for_mcav_summary"] == "yes"]
        all_usable = [row for row in rows if row.get("quality_flag") == "usable"]
        period_h = max((as_float(row, "observed_period_h") for row in rows), default=0.0)
        arrivals = sum(as_float(row, "conditioned_period_arrivals_mcav_person_point") for row in included)
        arrivals_low = sum(as_float(row, "conditioned_period_arrivals_mcav_person_low") for row in included)
        arrivals_high = sum(as_float(row, "conditioned_period_arrivals_mcav_person_high") for row in included)
        delay_h = sum(as_float(row, "total_delay_ped_h_conditioned_mcav_person_point") for row in included)
        avg_delay = delay_h * 3600.0 / arrivals if arrivals else ""
        site_rows.append(
            {
                "site": site,
                "region": first.get("region", ""),
                "street1": first.get("street1", ""),
                "street2": first.get("street2", ""),
                "suburb": first.get("suburb", ""),
                "lon": first.get("lon", ""),
                "lat": first.get("lat", ""),
                "movement_rows": len(rows),
                "usable_movement_rows": len(all_usable),
                "included_movement_rows": len(included),
                "auto_or_quality_excluded_movement_rows": len(rows) - len(included),
                "observed_period_h": period_h,
                "mcav_person_arrivals_point": arrivals,
                "mcav_person_arrivals_low": arrivals_low,
                "mcav_person_arrivals_high": arrivals_high,
                "mcav_person_arrivals_per_observed_hour_point": arrivals / period_h if period_h else "",
                "mcav_total_delay_ped_h_point": delay_h,
                "mcav_avg_delay_s_point": avg_delay,
            }
        )
    return site_rows


def calibrated_mapping(day_rows: list[dict]) -> tuple[list[dict], dict]:
    day_by_key = {movement_key(row): row for row in day_rows}
    mapped_rows = []
    for row in read_csv(MAPPED_IN):
        out = dict(row)
        cal = day_by_key.get(movement_key(row))
        if cal:
            for key in [
                "day_model_arrivals_per_hour_mcav_person_point",
                "day_model_arrivals_per_hour_mcav_person_low",
                "day_model_arrivals_per_hour_mcav_person_high",
                "recommended_observed_hours_mcav_person_point",
                "recommended_observed_hours_mcav_person_low",
                "recommended_observed_hours_mcav_person_high",
                "recommended_hour_rows",
                "auto_served_excluded_hour_rows",
                "recommended_for_mapping",
            ]:
                out[key] = cal.get(key, "")
        mapped_rows.append(out)

    geojson = {}
    if MAPPED_GEOJSON_IN.exists():
        geojson = json.loads(MAPPED_GEOJSON_IN.read_text(encoding="utf-8"))
        for feature in geojson.get("features", []):
            props = feature.get("properties", {})
            key = (str(props.get("site", "")), str(props.get("movement", "")))
            cal = day_by_key.get(key)
            if cal:
                props.update(
                    {
                        "mcav_flow_h_point": format_value(
                            cal.get("day_model_arrivals_per_hour_mcav_person_point")
                        ),
                        "mcav_flow_h_low": format_value(
                            cal.get("day_model_arrivals_per_hour_mcav_person_low")
                        ),
                        "mcav_flow_h_high": format_value(
                            cal.get("day_model_arrivals_per_hour_mcav_person_high")
                        ),
                        "mcav_recommended_hours": cal.get("recommended_hour_rows", ""),
                        "auto_excluded_hours": cal.get("auto_served_excluded_hour_rows", ""),
                        "recommended_for_mapping": cal.get("recommended_for_mapping", ""),
                    }
                )
    return mapped_rows, geojson


def write_readme(mult: dict, hour_rows: list[dict], day_rows: list[dict], flow_rows: list[dict], site_rows: list[dict], mapped_rows: list[dict]) -> None:
    hour_quality = Counter(row.get("quality_flag", "") for row in hour_rows)
    recommended_hours = [row for row in hour_rows if row["recommended_for_mcav_aggregate"] == "yes"]
    auto_hours = [
        row
        for row in hour_rows
        if row["auto_served_movement_hour_exclusion"] == "yes"
        or row["auto_served_site_hour_exclusion"] == "yes"
    ]
    included_flow = [row for row in flow_rows if row["recommended_for_mcav_summary"] == "yes"]
    mapped_recommended = [row for row in mapped_rows if row.get("recommended_for_mapping") == "yes"]

    with README_OUT.open("w", encoding="utf-8") as handle:
        handle.write(f"# MCAV-Calibrated SCATS Pedestrian Estimates, {DATE}\n\n")
        handle.write("This applies the empirical Manual Crossing-Actuation Validation (MCAV) case-alpha distribution from the pooled censored first-actuation estimator to SCATS.\n\n")
        handle.write("## Calibration\n\n")
        handle.write(f"- Deterministic count alpha (unweighted mean of 14 case factors): {mult['point']:.3f}\n")
        handle.write(f"- Empirical case-alpha central 95% interval: {mult['lower']:.3f} to {mult['upper']:.3f}\n")
        handle.write(f"- Empirical case-alpha range: {mult['case_min']:.3f} to {mult['case_max']:.3f}\n")
        handle.write(f"- Ratio-of-sums pooled diagnostic: {mult['pooled_diagnostic']:.3f} (not the case mean)\n")
        handle.write(f"- Bootstrap interval around the pooled diagnostic: {mult['pooled_bootstrap_lower']:.3f} to {mult['pooled_bootstrap_upper']:.3f}\n")
        handle.write(f"- Source model: {mult['model']}\n")
        handle.write(
            f"- Deterministic 100%-compliance delay alpha (mean of 14 case factors): "
            f"{mult['delay_point']:.3f}; empirical central 95% interval "
            f"{mult['delay_lower']:.3f} to {mult['delay_upper']:.3f}\n"
        )
        handle.write(
            f"- Deterministic observed-compliance-scenario delay alpha: "
            f"{mult['observed_compliance_delay_point']:.3f}; empirical central "
            f"95% interval {mult['observed_compliance_delay_lower']:.3f} to "
            f"{mult['observed_compliance_delay_upper']:.3f}\n"
        )
        handle.write("- Interpretation: within each movement-hour, first-actuation latencies and full restrictive exposure in no-actuation cycles jointly estimate one event rate. Applying that rate to the complete hour represents Walk-period and later arrivals without treating later pedestrians as additional actuator events. The matched MCAV factor then expands events to provisional person arrivals.\n\n")
        handle.write("## Outputs\n\n")
        for path in [HOUR_OUT, DAY_OUT, FLOW_DELAY_OUT, SITE_OUT, MAPPED_OUT, MAPPED_GEOJSON_OUT]:
            handle.write(f"- `{path.name}`\n")
        handle.write("\n## Legacy Movement-Level Diagnostic\n\n")
        handle.write(
            "The movement flow-delay source predates the pooled movement-hour estimator and is "
            "retained only for backward-compatible diagnostics. Its totals are not estimator-"
            "matched and are not reported or used in the paper. The movement-hour delay summary "
            "is the comprehensive estimator-matched aggregate used for headline and same-hour "
            "modal comparisons.\n\n"
        )
        handle.write(f"- Hour rows: {len(hour_rows):,}\n")
        handle.write(f"- Recommended usable non-auto-served hour rows: {len(recommended_hours):,}\n")
        handle.write(f"- Auto-served/suspect hour rows flagged: {len(auto_hours):,}\n")
        handle.write(f"- Movement-day rows: {len(day_rows):,}\n")
        handle.write(f"- Movement flow-delay rows included in recommended aggregate: {len(included_flow):,}\n")
        handle.write(f"- Mapped unique movements: {len(mapped_rows):,}\n")
        handle.write(f"- Mapped unique movements recommended without auto-served hour flags: {len(mapped_recommended):,}\n")
        handle.write("- Aggregate counts and delay intentionally omitted because the source estimator differs from the pooled movement-hour model.\n\n")
        handle.write("Hour-row quality flags:\n\n")
        for key, value in sorted(hour_quality.items()):
            handle.write(f"- {key}: {value:,}\n")
        handle.write("\n## Caveats\n\n")
        handle.write("- These are calibrated estimates, not directly observed pedestrian counts.\n")
        handle.write("- The MCAV alpha distribution comes from 14 field-observed intersection-direction cases and should be updated as more validation data are added.\n")
        handle.write("- Movement-hour totals exclude non-usable quality rows and records flagged for auto-service, demand suppression, or scheduled/forced calls.\n")
        handle.write("- Spatial mapping remains limited to movements with unique HST-to-spatial matches; crossing orientation is bidirectional, not travel direction.\n")


def main() -> None:
    mult = load_mcav_multiplier()
    auto_mh, auto_sh = load_auto_flags()
    hour_rows = calibrate_hour_rows(mult, auto_mh, auto_sh)
    day_rows = calibrate_day_rows(mult, hour_rows)
    flow_rows = calibrate_flow_delay_rows(mult, day_rows)
    site_rows = summarize_sites(flow_rows)
    mapped_rows, mapped_geojson = calibrated_mapping(day_rows)

    write_csv(HOUR_OUT, hour_rows)
    write_csv(DAY_OUT, day_rows)
    write_csv(FLOW_DELAY_OUT, flow_rows)
    write_csv(SITE_OUT, site_rows)
    write_csv(MAPPED_OUT, mapped_rows)
    if mapped_geojson:
        MAPPED_GEOJSON_OUT.write_text(json.dumps(mapped_geojson, indent=2), encoding="utf-8")
    write_readme(mult, hour_rows, day_rows, flow_rows, site_rows, mapped_rows)

    print(f"Mean count alpha: {mult['point']:.3f} (empirical 95%: {mult['lower']:.3f} to {mult['upper']:.3f})")
    print(
        f"Mean 100%-compliance delay alpha: {mult['delay_point']:.3f} "
        f"(empirical 95%: {mult['delay_lower']:.3f} to {mult['delay_upper']:.3f})"
    )
    print(
        f"Mean observed-compliance delay alpha: "
        f"{mult['observed_compliance_delay_point']:.3f} "
        f"(empirical 95%: {mult['observed_compliance_delay_lower']:.3f} "
        f"to {mult['observed_compliance_delay_upper']:.3f})"
    )
    print(f"Pooled ratio-of-sums diagnostic: {mult['pooled_diagnostic']:.3f}")
    print(f"Wrote {HOUR_OUT}")
    print(f"Wrote {DAY_OUT}")
    print(f"Wrote {FLOW_DELAY_OUT}")
    print(f"Wrote {SITE_OUT}")
    print(f"Wrote {MAPPED_OUT}")
    print(f"Wrote {MAPPED_GEOJSON_OUT}")
    print(f"Wrote {README_OUT}")


if __name__ == "__main__":
    main()
