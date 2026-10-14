# Estimating Pedestrian Flows and Signal Delay from Sydney Traffic-Signal Event Histories

David M. Levinson (2026). *Findings*. DOI: [10.32866/001c.172160](https://doi.org/10.32866/001c.172160).

Code and releasable derived outputs for the accepted manuscript. The accepted source is the supplied Overleaf export, matched to the 1 October 2026 resubmission. The public release preserves the final correction to the site-hour denominator and the pooled 38-case calibration used in that manuscript.

## Reproduce the paper

Requires Python 3.10 or later. Tested with Python 3.14. For Figures 1 and 3, install a LaTeX distribution providing `pdflatex`, TikZ, PGFPlots, and `standalone`.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/reproduce.py
```

`python scripts/reproduce.py --skip-latex` verifies all numeric results and regenerates Figure 2 without requiring TeX. Generated files are written to `outputs/`, which Git ignores. The entrypoint checks the archive SHA-256 manifest, reconstructs the calibration summaries and site distributions, pools the temporal sufficient statistics, compares the saved reference tables, and regenerates the three figures. Original figure PDFs and JPEGs remain in `paper/figures/`.

The numerical acceptance checks are 9,626 candidate movement-hours, 4,290 statistical exclusions, 222 additional controller-pattern exclusions, 5,114 retained movement-hours at 174 sites, and **2,307 usable site-hours**. The pooled point estimates are 331,728.65 crossings, 3,671.50 hours of full-compliance delay, and 2,746.35 hours in the behaviour scenario. Weekly and monthly Site 516 comparisons use 56 and 79 common movement-hour cells, respectively. Empirical calibration envelopes describe case-transfer variation; they are not sampling confidence intervals.

## Contents

- `broad_results/`: movement-hour and site-hour aggregates, temporal sufficient statistics, reduced calibration-factor inputs, and upstream analysis code.
- `converted_samples/`: authored event extraction, aggregation, mapping, and screening code. No decoded events, vendor binaries, or raw histories are included.
- `scripts/`: accepted correction and public reproduction entrypoint.
- `derived_inputs/`: minimal coordinate table derived from the final map display table.
- `reference_outputs/`: corrected site summaries, calibration summaries, and figure-source density tables checked against the accepted revision.
- `paper/`: accepted author manuscript, supplement, source, references, and final figures. Correspondence and private publisher proofs are excluded.
- `documentation/`: data dictionary, provenance, external-input boundaries, licenses, and the corrected availability statement.

`paper/figures/paper2_scats_flow_map_sites.csv` is a pre-correction intermediate retained as an input to the accepted correction. Use `reference_outputs/site_summary_corrected.csv` for reported site flow and usable hours. Do not use the upstream MCAV-only calibration outputs as the final pooled results. The public entrypoint applies the same pooled policy as the accepted paper.

## Release boundary

Raw SCATS `.hst` histories, VS data, decoded event traces, per-cycle records, individual actuation/censoring observations, proprietary SCATS software and JARs, video recordings, personal identifiers, correspondence, and publisher proof access tokens are excluded. The released observations are aggregate counts, exposure sufficient statistics and estimates by movement-hour, site-hour, site, calibration case, or figure point. Infrastructure site/movement identifiers and coordinates identify intersections rather than people.

The public inputs reproduce the reported aggregate analysis and figures. Re-running raw history decoding and event-level delay construction requires separately authorized access to the restricted SCATS histories and the external decoder. See [the external-input guide](documentation/EXTERNAL_INPUTS.md).

## Calibration provenance

The factor tables contain 14 manual-validation cases and 24 video leg-session cases. They are reduced snapshots of the inputs actually used by this paper. The underlying validation scripts and releasable validation data are already archived with the companion paper:

[Testing Pedestrian Flow and Delay Estimation from First-Actuation Latency](https://github.com/dlevinson/paper-2026-21-testing-pedestrian-flow-and-delay-estimation-from-first-actuation-latency/tree/fd0f4c270b4ca793d4b03c63f5d32c7f0bcadfc0).

The snapshots here allow independent reproduction without downloading that larger archive. Their input hashes and selected columns are recorded in `documentation/SOURCE_MANIFEST.json`.

## Licenses and availability

Authored code is MIT licensed; authored documentation and releasable derived outputs are CC BY 4.0, following the companion archive. These licenses do not grant access to restricted inputs or relicense third-party software or sources. See `LICENSE.md`.

Raw SCATS controller histories cannot be redistributed under the archive terms. Reproducible scripts and derived, nonidentifying movement-hour, site, calibration-factor, and figure-source outputs are available at https://github.com/dlevinson/paper-2026-25-estimating-pedestrian-flows-and-signal-delay-from-sydney-trafficsignal-event-histories.


The accepted manuscript in `paper/` preserves the submission-era future-tense availability wording; `documentation/AVAILABILITY_STATEMENT.txt` supplies the corrected present-tense statement for the final article.
