#!/usr/bin/env python3
import csv
import glob
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


def bearing(start, end):
    lon1, lat1 = map(math.radians, start)
    lon2, lat2 = map(math.radians, end)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def midpoint(coords):
    if not coords:
        return None
    mid = coords[len(coords) // 2]
    return mid


def read_spatial(spatial_root):
    rows = {}
    pattern = str(Path(spatial_root) / "**" / "*_phaseMovements_*.geojson")
    for path in glob.glob(pattern, recursive=True):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            continue
        for feature in data.get("features") or []:
            props = feature.get("properties", {})
            movement_types = props.get("movementtype", [])
            if not any(isinstance(t, dict) and t.get("type") == "PEDESTRIAN" for t in movement_types):
                continue
            site = props.get("siteid")
            ped_path_id = props.get("id")
            signal_groups = [
                sg.get("signalgroupnumber")
                for sg in props.get("signalgroups", [])
                if isinstance(sg, dict) and sg.get("signalgroupnumber") is not None
            ]
            geometry = feature.get("geometry", {})
            coords = geometry.get("coordinates") or []
            if geometry.get("type") != "LineString" or not coords:
                continue
            start = coords[0]
            end = coords[-1]
            mid = midpoint(coords)
            for signal_group in signal_groups:
                key = (int(site), int(signal_group), int(ped_path_id))
                row = rows.setdefault(
                    key,
                    {
                        "site": int(site),
                        "signalgroupnumber": int(signal_group),
                        "ped_path_id": int(ped_path_id),
                        "spatial_id": props.get("spatial_id"),
                        "siteversion": props.get("siteversion"),
                        "phases": set(),
                        "start_lon": start[0],
                        "start_lat": start[1],
                        "end_lon": end[0],
                        "end_lat": end[1],
                        "mid_lon": mid[0],
                        "mid_lat": mid[1],
                        "bearing_deg": bearing(start, end),
                        "geometry": geometry,
                        "source_file": path,
                    },
                )
                row["phases"].add(str(props.get("phasename")))
    return list(rows.values())


def write_spatial_catalog(path, spatial_rows):
    fields = [
        "site",
        "signalgroupnumber",
        "ped_path_id",
        "spatial_id",
        "siteversion",
        "phases",
        "start_lon",
        "start_lat",
        "end_lon",
        "end_lat",
        "mid_lon",
        "mid_lat",
        "bearing_deg",
        "source_file",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in sorted(spatial_rows, key=lambda r: (r["site"], r["signalgroupnumber"], r["ped_path_id"])):
            out = {field: row.get(field) for field in fields}
            out["phases"] = ";".join(sorted(row["phases"]))
            for field in ["start_lon", "start_lat", "end_lon", "end_lat", "mid_lon", "mid_lat", "bearing_deg"]:
                out[field] = f"{out[field]:.8f}"
            writer.writerow(out)


def read_csv_by_key(path, key_fields):
    out = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = tuple(row[field] for field in key_fields)
            out[key] = row
    return out


def read_mapping(path):
    mapping = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["match_status"] != "unique":
                continue
            mapping[(row["site"], row["hst_walk_movement"])] = row
    return mapping


def join_estimates(estimates_path, mapping_path, spatial_rows):
    mapping = read_mapping(mapping_path)
    spatial_by_site_sg = defaultdict(list)
    for row in spatial_rows:
        spatial_by_site_sg[(str(row["site"]), str(row["signalgroupnumber"]))].append(row)

    joined = []
    with open(estimates_path, newline="", encoding="utf-8") as handle:
        for estimate in csv.DictReader(handle):
            map_row = mapping.get((estimate["site"], estimate["movement"]))
            if not map_row:
                continue
            signal_group = map_row["matched_signal_groups"]
            for spatial in spatial_by_site_sg.get((estimate["site"], signal_group), []):
                row = dict(estimate)
                row["signalgroupnumber"] = signal_group
                row["ped_path_id"] = spatial["ped_path_id"]
                row["spatial_id"] = spatial["spatial_id"]
                row["siteversion"] = spatial["siteversion"]
                row["phases"] = ";".join(sorted(spatial["phases"]))
                row["start_lon"] = f"{spatial['start_lon']:.8f}"
                row["start_lat"] = f"{spatial['start_lat']:.8f}"
                row["end_lon"] = f"{spatial['end_lon']:.8f}"
                row["end_lat"] = f"{spatial['end_lat']:.8f}"
                row["mid_lon"] = f"{spatial['mid_lon']:.8f}"
                row["mid_lat"] = f"{spatial['mid_lat']:.8f}"
                row["bearing_deg"] = f"{spatial['bearing_deg']:.2f}"
                row["_geometry"] = spatial["geometry"]
                joined.append(row)
    return joined


def write_joined_csv(path, rows):
    if not rows:
        return
    fields = [field for field in rows[0].keys() if field != "_geometry"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_geojson(path, rows):
    features = []
    for row in rows:
        props = {key: value for key, value in row.items() if key != "_geometry"}
        features.append({"type": "Feature", "properties": props, "geometry": row["_geometry"]})
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"type": "FeatureCollection", "features": features}, handle, indent=2)


def choose_example_site(rows):
    by_site = defaultdict(list)
    for row in rows:
        by_site[row["site"]].append(row)
    candidates = []
    for site, site_rows in by_site.items():
        usable = [row for row in site_rows if row.get("quality_flag") == "usable"]
        total_demands = sum(int(row.get("observed_demands") or 0) for row in site_rows)
        candidates.append((len(usable), len(site_rows), total_demands, site))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][3]


def main():
    if len(sys.argv) != 6:
        print(
            "Usage: join_ped_estimates_to_spatial.py <spatial-root> <movement-day-estimates.csv> <mapping.csv> <output-dir> <date>",
            file=sys.stderr,
        )
        return 2

    spatial_root, estimates_path, mapping_path, output_dir, date = sys.argv[1:]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    spatial_rows = read_spatial(spatial_root)
    spatial_catalog = output_dir / "spatial_pedestrian_paths.csv"
    write_spatial_catalog(spatial_catalog, spatial_rows)

    joined = join_estimates(estimates_path, mapping_path, spatial_rows)
    joined_csv = output_dir / f"movement_day_estimates_mapped_unique_{date}.csv"
    joined_geojson = output_dir / f"movement_day_estimates_mapped_unique_{date}.geojson"
    write_joined_csv(joined_csv, joined)
    write_geojson(joined_geojson, joined)

    example_site = choose_example_site(joined) or "291"
    example_rows = [row for row in joined if row["site"] == example_site]
    example_csv = output_dir / f"example_intersection_site_{example_site}_mapped_{date}.csv"
    example_geojson = output_dir / f"example_intersection_site_{example_site}_mapped_{date}.geojson"
    write_joined_csv(example_csv, example_rows)
    write_geojson(example_geojson, example_rows)

    print(spatial_catalog)
    print(joined_csv)
    print(joined_geojson)
    print(example_csv)
    print(example_geojson)
    print(f"spatial_paths={len(spatial_rows)}")
    print(f"joined_rows={len(joined)}")
    print(f"example_rows={len(example_rows)}")


if __name__ == "__main__":
    raise SystemExit(main())
