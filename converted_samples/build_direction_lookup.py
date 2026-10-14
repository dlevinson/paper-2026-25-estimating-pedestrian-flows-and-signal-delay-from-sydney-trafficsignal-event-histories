#!/usr/bin/env python3
import csv
import sys
from collections import defaultdict
from pathlib import Path


def compass16(bearing):
    if bearing == "":
        return ""
    value = float(bearing) % 360.0
    labels = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    return labels[int((value + 11.25) // 22.5) % 16]


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def write_rows(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def split_signal_groups(value):
    value = value.strip()
    if not value:
        return []
    return [part.strip() for part in value.replace("|", ";").replace(",", ";").split(";") if part.strip()]


def main():
    if len(sys.argv) != 3:
        print("Usage: build_direction_lookup.py <broad-results-dir> <date>", file=sys.stderr)
        return 2

    results_dir = Path(sys.argv[1])
    date = sys.argv[2]

    spatial_rows = list(read_rows(results_dir / "spatial_pedestrian_paths.csv"))
    spatial_by_site_sg = defaultdict(list)
    spatial_out = []
    for row in spatial_rows:
        out = row.copy()
        out["bearing_compass16"] = compass16(row["bearing_deg"])
        spatial_by_site_sg[(row["site"], row["signalgroupnumber"])].append(out)
        spatial_out.append(out)

    spatial_fields = list(spatial_rows[0].keys()) + ["bearing_compass16"]
    spatial_path = results_dir / "pedestrian_spatial_path_directions.csv"
    write_rows(spatial_path, spatial_fields, spatial_out)

    mapping_rows = list(read_rows(results_dir / f"ped_signal_group_mapping_{date}.csv"))
    lookup_rows = []
    for row in mapping_rows:
        matched_signal_groups = split_signal_groups(row["matched_signal_groups"])
        base = {
            "site": row["site"],
            "region": row["region"],
            "street1": row["street1"],
            "street2": row["street2"],
            "suburb": row["suburb"],
            "hst_walk_movement": row["hst_walk_movement"],
            "match_status": row["match_status"],
            "matched_signal_groups": row["matched_signal_groups"],
            "ped_frequency": row["ped_frequency"],
            "ped_min_s": row["ped_min_s"],
            "ped_max_s": row["ped_max_s"],
            "ped_total_s": row["ped_total_s"],
        }
        if row["match_status"] != "unique" or len(matched_signal_groups) != 1:
            lookup_rows.append({
                **base,
                "direction_known": "no",
                "signalgroupnumber": "",
                "ped_path_id": "",
                "spatial_id": "",
                "phases": "",
                "start_lon": "",
                "start_lat": "",
                "end_lon": "",
                "end_lat": "",
                "bearing_deg": "",
                "bearing_compass16": "",
                "direction_note": "HST movement not uniquely matched to a spatial pedestrian signal group",
            })
            continue

        spatial_matches = spatial_by_site_sg.get((row["site"], matched_signal_groups[0]), [])
        if not spatial_matches:
            lookup_rows.append({
                **base,
                "direction_known": "no",
                "signalgroupnumber": matched_signal_groups[0],
                "ped_path_id": "",
                "spatial_id": "",
                "phases": "",
                "start_lon": "",
                "start_lat": "",
                "end_lon": "",
                "end_lat": "",
                "bearing_deg": "",
                "bearing_compass16": "",
                "direction_note": "Unique HST signal-group match, but no spatial pedestrian path found for that signal group",
            })
            continue

        for spatial in spatial_matches:
            lookup_rows.append({
                **base,
                "direction_known": "yes",
                "signalgroupnumber": spatial["signalgroupnumber"],
                "ped_path_id": spatial["ped_path_id"],
                "spatial_id": spatial["spatial_id"],
                "phases": spatial["phases"],
                "start_lon": spatial["start_lon"],
                "start_lat": spatial["start_lat"],
                "end_lon": spatial["end_lon"],
                "end_lat": spatial["end_lat"],
                "bearing_deg": spatial["bearing_deg"],
                "bearing_compass16": spatial["bearing_compass16"],
                "direction_note": "Geometry bearing is from spatial path start point to end point; real pedestrian travel may be bidirectional",
            })

    lookup_fields = [
        "site",
        "region",
        "street1",
        "street2",
        "suburb",
        "hst_walk_movement",
        "match_status",
        "matched_signal_groups",
        "direction_known",
        "signalgroupnumber",
        "ped_path_id",
        "spatial_id",
        "phases",
        "start_lon",
        "start_lat",
        "end_lon",
        "end_lat",
        "bearing_deg",
        "bearing_compass16",
        "ped_frequency",
        "ped_min_s",
        "ped_max_s",
        "ped_total_s",
        "direction_note",
    ]
    lookup_path = results_dir / f"hst_pedestrian_movement_direction_lookup_{date}.csv"
    write_rows(lookup_path, lookup_fields, lookup_rows)

    print(spatial_path)
    print(lookup_path)


if __name__ == "__main__":
    raise SystemExit(main())
