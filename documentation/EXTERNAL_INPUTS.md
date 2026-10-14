# External inputs and upstream code

## Public aggregate route

Run `python scripts/reproduce.py`. All required numerical inputs are included. The network aggregate CSVs contain statistics and estimates by infrastructure movement-hour/site-hour, not event timestamps or individual trajectories. The temporal table contains per-day movement-hour sufficient statistics; monthly pools can therefore be recomputed publicly. Factors are unweighted paired cases (14 manual plus 24 video cases) exactly as used in the accepted paper.

## Restricted upstream route

The authored Java adapters `BroadWalkExtractor`, `SelectedMultiDateWalkExtractor`, `PedWindowExtractor` and `PedSignalGroupMapper` call the `au.com.scats` history-viewer API and Eclipse runtime. They require an independently authorized SCATS History Viewer/decoder installation, its dependencies, a site inventory and licensed HST histories. Vendor classes, JARs and compiled binaries are not included or relicensed.

`converted_samples/summarize_broad_walk.py` pools the first-actuation and right-censored observations; `flag_auto_served_ped_phases.py` supplies controller-pattern exclusions. `compute_actuated_delay.py` and `compute_cycle_actuation_summary.py` construct upstream delay/cycle intermediates. Mapping helpers require the external spatial source inventory. The network `apply_mcav_calibration.py` and `compute_pedestrian_hour_delay.py` apply the manual calibration to those upstream intermediates, before the accepted pooled-calibration distribution/correction step. The temporal extractor and original temporal builder expect the restricted per-event extraction tree. The public driver instead pools the included sufficient statistics.

The repository preserves these original relative-path interfaces. Authorized users must supply their own input tree and calibration source inputs where an upstream script requests them; the archive does not imply those raw-dependent stages can run from public files alone. The full validation archive is linked in the main README rather than duplicated here.

## Excluded classes

- HST/VS histories, signal event exports, acceptance/demand/walk timestamps, per-cycle rows and event-level latency/censor observations.
- SCATS decoder payloads, vendor libraries, decompiled sources and compiled classes.
- Video recordings, raw personal records and person-linked observations.
- Journal correspondence, reviewer responses, private publisher proofs, private access URLs and authentication tokens.
- Unrelated vehicle-comparison/counterfactual analyses and superseded manuscripts.

Raw SCATS histories cannot be redistributed under the archive terms. Obtain authorized access separately from the relevant data controller; this repository grants no rights to those histories.
