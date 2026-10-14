# Release validation, 15 October 2026

The public entrypoint passed with Python 3.14, matplotlib 3.11.2 and pdfTeX (TeX Live 2026). Thirteen reference CSV tables were compared numerically. All accepted sample sizes, calibration cases, network totals, corrected usable-hour denominators and temporal common-support sizes passed. Figures 1, 2 and 3 regenerated successfully; their rendered output was inspected for labels, clipping, scales and legibility. The machine-readable result is VALIDATION.json.

All CSV headers were reviewed for the release boundary. No per-event timestamp fields, latency observation rows, censor event rows, cycle traces, raw histories, proprietary binary software, private proof URLs or access tokens are included. The archive is an explicit file allowlist, rather than a recursive copy of the research archive. Code may name restricted input interfaces; the corresponding input files are excluded.
