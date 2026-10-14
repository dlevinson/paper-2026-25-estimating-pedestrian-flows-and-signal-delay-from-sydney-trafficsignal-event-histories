#!/usr/bin/env python3
"""Build pooled-calibration density data for the SCATS pedestrian paper.

The 14 manual-observation cases and 24 video-observation cases form one 38-case
empirical distribution.
The point curves use the pooled mean count and 100%-compliance delay
adjustments.  The bands are pointwise central 95% transfer envelopes obtained
by applying every case-specific count/delay adjustment set to all usable SCATS
sites and recomputing the density.  Density is evaluated in log space because
site totals and rates are strongly right-skewed.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from statistics import mean, stdev


ROOT = Path(__file__).resolve().parents[2]
SITE_HOUR_INPUT = (
    ROOT
    / "broad_results"
    / "network_20180918"
    / "pedestrian_site_hour_delay_20180918.csv"
)
MCAV_ALPHA_INPUT = (
    ROOT
    / "broad_results"
    / "network_20180918"
    / "mcav_alpha_case_distribution.csv"
)
VIDEO_ALPHA_INPUT = (
    ROOT
    / "broad_results"
    / "validation"
    / "video_noncompliance_validation"
    / "video_upstream_peer_cases.csv"
)
MCAV_BEHAVIOR_INPUT = (
    ROOT
    / "broad_results"
    / "validation"
    / "mcav_validation"
    / "mcav_compliance_scenario_by_case.csv"
)
OUTPUT = ROOT / "paper" / "figures" / "paper2_scats_pedestrian_distribution_data.csv"
CALIBRATION_SUMMARY_OUTPUT = (
    ROOT / "paper" / "figures" / "paper2_peer_calibration_summary.csv"
)
SITE_SUMMARY_OUTPUT = ROOT / "paper" / "figures" / "paper2_peer_site_summary.csv"


def quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = p * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def log_grid(series: list[list[float]], points: int = 301) -> list[float]:
    positive = [value for values in series for value in values if value > 0]
    low = min(positive) * 0.80
    high = max(positive) * 1.20
    log_low = math.log(low)
    step = (math.log(high) - log_low) / (points - 1)
    return [math.exp(log_low + index * step) for index in range(points)]


def log_kde(values: list[float], grid: list[float]) -> list[float]:
    logs = [math.log(value) for value in values if value > 0]
    n = len(logs)
    sigma = stdev(logs)
    iqr_scale = (quantile(logs, 0.75) - quantile(logs, 0.25)) / 1.34
    scale = min(sigma, iqr_scale) if iqr_scale > 0 else sigma
    bandwidth = max(0.08, 0.90 * scale * n ** (-0.2))
    normalizer = n * bandwidth * math.sqrt(2 * math.pi)
    return [
        sum(
            math.exp(-0.5 * ((math.log(x_value) - observation) / bandwidth) ** 2)
            for observation in logs
        )
        / normalizer
        for x_value in grid
    ]


def density_bundles(
    point_values: dict[str, list[float]],
    stochastic_values: dict[str, list[list[float]]],
) -> tuple[
    list[float],
    dict[str, tuple[list[float], list[float], list[float]]],
]:
    all_series: list[list[float]] = []
    for source in point_values:
        all_series.append(point_values[source])
        all_series.extend(stochastic_values[source])
    grid = log_grid(all_series)
    source_bundles: dict[str, tuple[list[float], list[float], list[float]]] = {}
    for source in point_values:
        point_density = log_kde(point_values[source], grid)
        stochastic_densities = [
            log_kde(values, grid) for values in stochastic_values[source]
        ]
        lower = [
            quantile([density[index] for density in stochastic_densities], 0.025)
            for index in range(len(grid))
        ]
        upper = [
            quantile([density[index] for density in stochastic_densities], 0.975)
            for index in range(len(grid))
        ]
        source_bundles[source] = (point_density, lower, upper)
    return grid, source_bundles


def main() -> None:
    with SITE_HOUR_INPUT.open(newline="", encoding="utf-8-sig") as handle:
        site_hour_rows = list(csv.DictReader(handle))

    site_totals: dict[str, dict[str, float]] = {}
    for row in site_hour_rows:
        site = row["site"]
        totals = site_totals.setdefault(
            site, {"hours": 0.0, "arrivals": 0.0, "delay_h": 0.0}
        )
        totals["hours"] += int(row["included_movement_hour_rows"]) > 0
        totals["arrivals"] += float(row["mcav_person_arrivals_conditioned"])
        totals["delay_h"] += float(row["mcav_person_delay_h_conditioned"])

    sites = [
        totals
        for totals in site_totals.values()
        if totals["hours"] > 0 and totals["arrivals"] > 0 and totals["delay_h"] > 0
    ]

    with MCAV_ALPHA_INPUT.open(newline="", encoding="utf-8-sig") as handle:
        mcav_rows = list(csv.DictReader(handle))
    with VIDEO_ALPHA_INPUT.open(newline="", encoding="utf-8-sig") as handle:
        video_rows = list(csv.DictReader(handle))
    with MCAV_BEHAVIOR_INPUT.open(newline="", encoding="utf-8-sig") as handle:
        mcav_behavior_rows = list(csv.DictReader(handle))

    mcav_behavior_by_case = {
        row["case"]: float(row["delay_alpha_observed_compliance_scenario"])
        for row in mcav_behavior_rows
    }
    calibration = {
        "pooled": {
            "count": (
                [float(row["count_alpha_case"]) for row in mcav_rows]
                + [float(row["count_alpha"]) for row in video_rows]
            ),
            "delay": (
                [float(row["delay_alpha_case"]) for row in mcav_rows]
                + [float(row["delay_alpha"]) for row in video_rows]
            ),
            "behavior": (
                [mcav_behavior_by_case[row["case"]] for row in mcav_rows]
                + [float(row["realised_delay_alpha"]) for row in video_rows]
            ),
        },
    }
    assert all(
        len(factors["count"]) == len(factors["delay"]) == len(factors["behavior"])
        for factors in calibration.values()
    )

    mcav_mean_count = mean(
        [float(row["count_alpha_case"]) for row in mcav_rows]
    )
    mcav_mean_delay = mean(
        [float(row["delay_alpha_case"]) for row in mcav_rows]
    )
    mcav_point_count = [row["arrivals"] for row in sites]
    mcav_point_flow = [row["arrivals"] / row["hours"] for row in sites]
    mcav_point_average_delay = [
        row["delay_h"] * 3600 / row["arrivals"] for row in sites
    ]
    mcav_point_total_delay = [row["delay_h"] for row in sites]

    base_count = [value / mcav_mean_count for value in mcav_point_count]
    base_flow = [value / mcav_mean_count for value in mcav_point_flow]
    base_total_delay = [value / mcav_mean_delay for value in mcav_point_total_delay]
    base_average_delay = [
        value * mcav_mean_count / mcav_mean_delay
        for value in mcav_point_average_delay
    ]

    point_values: dict[str, dict[str, list[float]]] = {
        "flow": {},
        "count": {},
        "average_delay": {},
        "total_delay": {},
    }
    stochastic_values: dict[str, dict[str, list[list[float]]]] = {
        "flow": {},
        "count": {},
        "average_delay": {},
        "total_delay": {},
    }
    for source, factors in calibration.items():
        mean_count_alpha = mean(factors["count"])
        mean_delay_alpha = mean(factors["delay"])
        point_values["count"][source] = [
            value * mean_count_alpha for value in base_count
        ]
        point_values["flow"][source] = [
            value * mean_count_alpha for value in base_flow
        ]
        point_values["total_delay"][source] = [
            value * mean_delay_alpha for value in base_total_delay
        ]
        point_values["average_delay"][source] = [
            value * mean_delay_alpha / mean_count_alpha
            for value in base_average_delay
        ]
        stochastic_values["count"][source] = [
            [value * alpha for value in base_count] for alpha in factors["count"]
        ]
        stochastic_values["flow"][source] = [
            [value * alpha for value in base_flow] for alpha in factors["count"]
        ]
        stochastic_values["total_delay"][source] = [
            [value * alpha for value in base_total_delay]
            for alpha in factors["delay"]
        ]
        stochastic_values["average_delay"][source] = [
            [
                value * delay_alpha / count_alpha
                for value in base_average_delay
            ]
            for count_alpha, delay_alpha in zip(factors["count"], factors["delay"])
        ]

    bundles = {
        name: density_bundles(point_values[name], stochastic_values[name])
        for name in point_values
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for name in bundles:
        fieldnames.append(f"{name}_x")
        for source in calibration:
            fieldnames.extend(
                [
                    f"{name}_density_{source}_point",
                    f"{name}_density_{source}_p025",
                    f"{name}_density_{source}_p975",
                ]
            )

    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index in range(len(next(iter(bundles.values()))[0])):
            row: dict[str, str] = {}
            for name, (grid, source_bundles) in bundles.items():
                row[f"{name}_x"] = f"{grid[index]:.9f}"
                for source, (point, lower, upper) in source_bundles.items():
                    row[f"{name}_density_{source}_point"] = (
                        f"{point[index]:.9f}"
                    )
                    row[f"{name}_density_{source}_p025"] = (
                        f"{lower[index]:.9f}"
                    )
                    row[f"{name}_density_{source}_p975"] = (
                        f"{upper[index]:.9f}"
                    )
            writer.writerow(row)

    for name, (grid, source_bundles) in bundles.items():
        for source, (_point, lower, upper) in source_bundles.items():
            band_output = (
                OUTPUT.parent
                / f"paper2_{name}_{source}_density_band.csv"
            )
            with band_output.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow([f"{name}_x", f"{name}_density_band"])
                for x_value, density in zip(grid, lower):
                    writer.writerow([f"{x_value:.9f}", f"{density:.9f}"])
                for x_value, density in zip(reversed(grid), reversed(upper)):
                    writer.writerow([f"{x_value:.9f}", f"{density:.9f}"])

    with CALIBRATION_SUMMARY_OUTPUT.open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        fields = [
            "source",
            "cases",
            "count_alpha_mean",
            "count_alpha_p025",
            "count_alpha_p975",
            "delay_alpha_100_mean",
            "delay_alpha_100_p025",
            "delay_alpha_100_p975",
            "delay_alpha_behavior_mean",
            "delay_alpha_behavior_p025",
            "delay_alpha_behavior_p975",
            "network_estimated_crossings_mean",
            "network_estimated_crossings_p025",
            "network_estimated_crossings_p975",
            "network_delay_100_h_mean",
            "network_delay_100_h_p025",
            "network_delay_100_h_p975",
            "network_delay_100_s_per_crossing",
            "network_delay_behavior_h_mean",
            "network_delay_behavior_h_p025",
            "network_delay_behavior_h_p975",
            "network_delay_behavior_s_per_crossing",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        network_base_count = sum(base_count)
        network_base_delay = sum(base_total_delay)
        for source, factors in calibration.items():
            count_mean = mean(factors["count"])
            delay_mean = mean(factors["delay"])
            count_low = quantile(factors["count"], 0.025)
            count_high = quantile(factors["count"], 0.975)
            delay_low = quantile(factors["delay"], 0.025)
            delay_high = quantile(factors["delay"], 0.975)
            behavior_mean = mean(factors["behavior"])
            behavior_low = quantile(factors["behavior"], 0.025)
            behavior_high = quantile(factors["behavior"], 0.975)
            crossings = network_base_count * count_mean
            delay_h = network_base_delay * delay_mean
            behavior_delay_h = network_base_delay * behavior_mean
            writer.writerow(
                {
                    "source": source,
                    "cases": len(factors["count"]),
                    "count_alpha_mean": f"{count_mean:.9f}",
                    "count_alpha_p025": f"{count_low:.9f}",
                    "count_alpha_p975": f"{count_high:.9f}",
                    "delay_alpha_100_mean": f"{delay_mean:.9f}",
                    "delay_alpha_100_p025": f"{delay_low:.9f}",
                    "delay_alpha_100_p975": f"{delay_high:.9f}",
                    "delay_alpha_behavior_mean": f"{behavior_mean:.9f}",
                    "delay_alpha_behavior_p025": f"{behavior_low:.9f}",
                    "delay_alpha_behavior_p975": f"{behavior_high:.9f}",
                    "network_estimated_crossings_mean": f"{crossings:.6f}",
                    "network_estimated_crossings_p025": (
                        f"{network_base_count * count_low:.6f}"
                    ),
                    "network_estimated_crossings_p975": (
                        f"{network_base_count * count_high:.6f}"
                    ),
                    "network_delay_100_h_mean": f"{delay_h:.6f}",
                    "network_delay_100_h_p025": (
                        f"{network_base_delay * delay_low:.6f}"
                    ),
                    "network_delay_100_h_p975": (
                        f"{network_base_delay * delay_high:.6f}"
                    ),
                    "network_delay_100_s_per_crossing": (
                        f"{delay_h * 3600 / crossings:.6f}"
                    ),
                    "network_delay_behavior_h_mean": (
                        f"{behavior_delay_h:.6f}"
                    ),
                    "network_delay_behavior_h_p025": (
                        f"{network_base_delay * behavior_low:.6f}"
                    ),
                    "network_delay_behavior_h_p975": (
                        f"{network_base_delay * behavior_high:.6f}"
                    ),
                    "network_delay_behavior_s_per_crossing": (
                        f"{behavior_delay_h * 3600 / crossings:.6f}"
                    ),
                }
            )

    with SITE_SUMMARY_OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "source",
            "metric",
            "median",
            "p25",
            "p75",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for source in calibration:
            for metric in ("flow", "count", "average_delay", "total_delay"):
                values = point_values[metric][source]
                writer.writerow(
                    {
                        "source": source,
                        "metric": metric,
                        "median": f"{quantile(values, 0.5):.9f}",
                        "p25": f"{quantile(values, 0.25):.9f}",
                        "p75": f"{quantile(values, 0.75):.9f}",
                    }
                )

    print(f"Usable sites: {len(sites)}")
    print(f"Manual-observation cases: {len(mcav_rows)}")
    print(f"Video-observation leg-session cases: {len(video_rows)}")
    print(f"Pooled cases: {len(calibration['pooled']['count'])}")
    print(f"Wrote: {OUTPUT}")


if __name__ == "__main__":
    main()
