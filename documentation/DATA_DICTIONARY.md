# Data dictionary

Each row is an aggregate observation or estimate, not an event or person. Empty estimated cells indicate missing/not estimable, never zero. Calendar dates use YYYYMMDD (or YYYY-MM for monthly pools); `hour` is the start of the archive clock-hour bin, 0–23. No timezone conversion is applied to the saved archive clock bins. Infrastructure IDs are strings.

| Table | Row unit and role |
| --- | --- |
| network `movement_hour_estimates_20180918.csv` | 9,626 candidate site/movement/hour cells; first-actuation count, censor count, exposure and statistical quality screen. |
| network `pedestrian_movement_hour_delay_20180918.csv` | Same 9,626 cells; controller exclusion flags, manual-calibrated intermediate arrivals and delay estimates. `recommended_for_mcav_aggregate=yes` identifies 5,114 retained cells. |
| network `pedestrian_site_hour_delay_20180918.csv` | 3,742 exported site/hour rows, including empty-support exports. A retained site-hour requires `included_movement_hour_rows>0`; 2,307 pass. |
| `reference_outputs/site_hours_with_retained_movements.csv` | The retained site-hour subset. |
| `reference_outputs/site_summary_corrected.csv` | 174 site totals and corrected rates. `exported_site_hours` is the historical pre-correction denominator; `usable_site_hours` is the final retained-support denominator. |
| `reference_outputs/calibration_summary_verified.csv` | Pooled calibration factors, empirical 2.5/97.5 percentiles, expanded network totals and mean delays. |
| `reference_outputs/site_distribution_summary_corrected.csv` | Median and interquartile bounds across sites for count, hourly flow, average delay and total delay. |
| `reference_outputs/figures/*` | Log-scale kernel-density x coordinates and densities/envelope polygons used in Figure 3. |
| temporal `site516_movement_hour_estimates.csv` | Date/movement/hour sufficient statistics, quality and automatic-service masks, effective rate and expanded pedestrian rate. |
| temporal `site516_processing_status.csv` | Date-level decoding/core-hour coverage mask; no event records or raw error paths. |
| temporal diurnal/weekly/monthly CSVs | Figure 2 aggregate series and screened-coverage diagnostics. Weekly and monthly plots use common movement-hour support. Monthly values are typical-day flows, not month totals. |
| calibration input CSVs | Paired case-level count, full-compliance delay and behaviour factors; dimensionless. Case labels identify validation intersections or case IDs, never people. |
| map tables | Infrastructure locations, movement endpoints, corrected site flows, final display offsets. Longitude/latitude are geographic degrees; display positions are centimetres in the generated graphic. |

## Quantities and units

`site`, `movement`, `region`, `street1`, `street2`, `suburb`, `case` and `case_id` are infrastructure/case labels. `lon`, `start_lon`, `end_lon`, `lat`, `start_lat`, `end_lat` are geographic degrees. `observed_demands` counts first actuations, `censored_intervals` counts right-censored opportunities, and `zero_delay_demands` counts zero latency first actuations. `total_exposure_s` is summed observed/censored risk exposure in seconds. `zero_delay_share` is dimensionless. Uncensored latency means/medians/quantiles and `*_s` are seconds unless the name explicitly states a rate per crossing. `*_per_hour` denotes arrivals/crossings per hour; `*_delay_h*` denotes person-hours of delay. `*_avg_delay_s*`, `average_delay_s_100`, and `*_s_per_crossing` denote seconds per crossing. `estimated_crossings` and expanded arrival counts are crossings over included support; fractional counts are model expectations.

Calibration `alpha`/`multiplier` fields are dimensionless. `point` or `mean` indicates an unweighted case mean; `p025`/`low` and `p975`/`high` describe empirical case-factor quantiles. `delay_alpha_case` and `delay_alpha` expand full-compliance model delay, while `delay_alpha_observed_compliance_scenario` and `realised_delay_alpha` supply the behaviour scenario. The preserved intermediate `mcav_*` names refer to manual-case expansion; final pooled values are in `reference_outputs`.

Quality flags are `usable`, `sparse` (fewer than five first actuations), `zero_heavy` (at least 50% zero latencies), `censor_heavy` (at least 75% censored opportunities), or `no_demands`. Controller masks separately flag automatic service. A site/hour is usable if at least one movement-hour survives. Temporal `complete` means all four movements survive; `partial` means fewer survive; `not_estimable` means none survive. `complete_core` means no missing 08:00–18:59 extraction hours; it is a date coverage screen, separate from statistical usability.

The supplement `accepted_manuscript/SI.pdf` supplies the estimator equations, notation, screen definitions, assumptions and calibration details. `TABLE_SCHEMAS.csv` inventories every released CSV header and row count.
