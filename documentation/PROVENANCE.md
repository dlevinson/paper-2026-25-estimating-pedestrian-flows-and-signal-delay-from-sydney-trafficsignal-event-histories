# Provenance and accepted corrections

The release was prepared on 15 October 2026 from the SCATS research archive and the accepted author package. It uses the supplied Overleaf ZIP (SHA-256 `92e43e24042734a7ad5be8781a900b4d6e53ca92097b93ce9f1903976fc610b3`), whose main text, supplement and bibliography match the 1 October resubmission. No private proof URL or review correspondence is distributed.

`SOURCE_MANIFEST.json` records source-relative paths, original SHA-256 hashes, released hashes at staging, and transformations. Absolute workstation paths are deliberately omitted. `ARCHIVE_MANIFEST.csv` is the authoritative hash manifest for the final released payload.

The 29 September accepted correction counts a site-hour only when `included_movement_hour_rows > 0`. This gives 2,307 usable site-hours and 17 at Site 516. The distribution script contains this correction directly. Density-band output paths were made relative to the selected output directory. The revision builder now uses repository-relative aggregate inputs and writes under `outputs/revision`; its coordinate input is a three-column derivative of the final map table rather than the full SCATS site inventory. The original assertion that non-flow density results are unchanged is replaced by the public entrypoint's comparison of all final reference tables, including flow.

The public reproduction entrypoint adds monthly pooling from the released per-day movement-hour sufficient statistics (`n`, censor count, zero count, exposure), using the original automatic-service and complete-core-date masks. This produces the same monthly rates and common support as pooling the restricted event observations, without redistributing those observations. Minor numeric differences from six-decimal CSV serialization are checked with absolute tolerances of 1e-5 for network tables and 1e-4 for temporal tables. Figure files may differ in metadata, font handling, or rasterization between software versions.

The other extraction and analysis scripts are byte-identical copies of authored source. They are provided for inspection and for researchers with authorized external inputs. The public reproduction entrypoint is the tested route to the accepted results; it does not run proprietary decoding or require raw data.

## Repository naming

The standard full-title basename is 101 characters, exceeding GitHub's 100-character repository-name limit. The compound `traffic-signal` is joined as `trafficsignal` in the folder and remote basename; all title words and the full `paper-2026-25` identifier are retained. The paper citation retains its original spelling.
