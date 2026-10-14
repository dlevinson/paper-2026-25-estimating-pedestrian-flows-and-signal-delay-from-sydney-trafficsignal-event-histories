#!/usr/bin/env python3
"""Reproduce the accepted paper from nonidentifying aggregate inputs."""
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    with path.open(newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))

def module(path):
    spec = importlib.util.spec_from_file_location('temporal', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def compare_csv(actual, expected, tolerance=1e-5):
    left, right = read(actual), read(expected)
    assert len(left) == len(right), (actual.name, len(left), len(right))
    for i, (a, b) in enumerate(zip(left, right)):
        assert a.keys() == b.keys(), actual.name
        for key in a:
            if a[key] == b[key]: continue
            try: x, y = float(a[key]), float(b[key])
            except ValueError: raise AssertionError((actual.name, i, key, a[key], b[key]))
            assert math.isclose(x, y, abs_tol=tolerance, rel_tol=1e-9), (actual.name, i, key, x, y)

def monthly_from_sufficient_statistics(models, statuses, alpha, temporal):
    # Sum n, c, zero counts and exposure rather than reconstructing event histories.
    season_days = temporal.dates_between(temporal.SEASON_START, temporal.SEASON_END)
    day_month = {d.strftime('%Y%m%d'): d.strftime('%Y-%m') for d in season_days}
    complete = {r['date'] for r in statuses if r['status']=='ok' and r['coverage_status']=='complete_core'}
    totals = defaultdict(lambda: [0, 0, 0, 0.0])
    for r in models:
        if r['date'] not in day_month or r['date'] not in complete or r['automatic_service_exclusion']=='yes': continue
        t=totals[(day_month[r['date']], r['movement'], r['hour'])]
        t[0]+=r['observed_demands'];t[1]+=r['censored_intervals'];t[2]+=r['zero_delay_demands'];t[3]+=r['total_exposure_s']
    months=list(dict.fromkeys(day_month.values()))
    eligible={m:{} for m in months}
    for (month,movement,hour),(n,c,zero,exposure) in totals.items():
        if temporal.classify(n,c,zero)=='usable' and exposure>0:
            eligible[month][(movement,hour)] = alpha*n/exposure*3600
    common=set.intersection(*(set(eligible[m]) for m in months))
    rows=[]
    for m in months:
        rows.append(dict(month=m, month_label=datetime.strptime(m,'%Y-%m').strftime('%b %Y'),
            expected_days=sum(v==m for v in day_month.values()),
            processed_days=sum(v==m and d in complete for d,v in day_month.items()),
            eligible_movement_hours=len(eligible[m]), common_support_movement_hours=len(common),
            typical_day_estimated_pedestrians_common_support=sum(eligible[m][cell] for cell in sorted(common)),
            typical_day_estimated_pedestrians_all_eligible=sum(eligible[m].values())))
    return rows,common

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-latex',action='store_true',help='Verify tables and Figure 2 only; skip the LaTeX figures.')
    args=parser.parse_args()
    # Verify the distributed payload before using it.
    for r in read(ROOT/'ARCHIVE_MANIFEST.csv'):
        p=ROOT/r['path']
        assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'], r['path']
    subprocess.run([sys.executable,str(ROOT/'scripts/build_revision_data.py')],check=True)
    out=ROOT/'outputs/revision'
    checked=[]
    for p in sorted((ROOT/'reference_outputs').rglob('*.csv')):
        compare_csv(out/p.relative_to(ROOT/'reference_outputs'),p)
        checked.append(str(p.relative_to(ROOT)))
    temporal=module(ROOT/'broad_results/site516_temporal_profiles/scripts/build_site516_temporal_profiles.py')
    source=ROOT/'broad_results/site516_temporal_profiles'
    destination=ROOT/'outputs/temporal'
    destination.mkdir(parents=True,exist_ok=True)
    temporal.RESULTS=destination;temporal.FIGURES=destination
    alpha=float(read(out/'calibration_summary_verified.csv')[0]['count_alpha_mean'])
    models=read(source/'site516_movement_hour_estimates.csv')
    for r in models:
        for k in ['hour','observed_demands','censored_intervals','zero_delay_demands']:r[k]=int(r[k])
        r['total_exposure_s']=float(r['total_exposure_s'])
        rate=3600*r['observed_demands']/r['total_exposure_s'] if r['total_exposure_s'] else float('nan')
        estimate=alpha*rate if r['recommended']=='yes' else float('nan')
        if math.isfinite(estimate):assert abs(estimate-float(r['estimated_pedestrians_per_hour']))<1e-5
        r['estimated_pedestrians_per_hour']=estimate
    diurnal=temporal.build_diurnal(models)
    weekly,week_common=temporal.build_week(models)
    statuses=read(source/'site516_processing_status.csv')
    monthly,month_common=monthly_from_sufficient_statistics(models,statuses,alpha,temporal)
    for name,rows in [('site516_diurnal_20180918.csv',diurnal),('site516_week_20180914_20180920.csv',weekly),('site516_monthly_201709_201808.csv',monthly)]:
        fields=list(read(source/name)[0])
        temporal.write_csv(destination/name,rows,fields)
        compare_csv(destination/name,source/name,tolerance=1e-4)
        checked.append('broad_results/site516_temporal_profiles/'+name)
    temporal.plot(diurnal,weekly,monthly)
    mh=read(ROOT/'broad_results/network_20180918/pedestrian_movement_hour_delay_20180918.csv')
    quality=sum(r['quality_flag']!='usable' for r in mh)
    retained=sum(r['recommended_for_mcav_aggregate']=='yes' for r in mh)
    assert (len(mh),quality,retained)==(9626,4290,5114)
    calibration=read(out/'calibration_summary_verified.csv')[0]
    sites=read(out/'site_summary_corrected.csv')
    assert len(sites)==174 and sum(int(r['usable_site_hours']) for r in sites)==2307
    assert len(week_common)==56 and len(month_common)==79
    expected={'network_estimated_crossings_mean':331728.647333,'network_delay_100_h_mean':3671.498996,'network_delay_behavior_h_mean':2746.345193}
    for key,value in expected.items():assert abs(float(calibration[key])-value)<0.01,(key,calibration[key])
    figures=[str(p.relative_to(ROOT)) for p in destination.glob('*.pdf')]
    if not args.skip_latex:
        latex=shutil.which('pdflatex')
        if latex is None: raise RuntimeError('Install a LaTeX distribution with TikZ/PGFPlots, or run --skip-latex.')
        for stem in ['paper2_scats_flow_map','paper2_scats_pedestrian_distributions']:
            result=subprocess.run([latex,'-interaction=nonstopmode','-halt-on-error',stem+'.tex'],cwd=out/'figures',capture_output=True,text=True)
            if result.returncode:raise RuntimeError(result.stdout[-6000:])
            figures.append(str((out/'figures'/f'{stem}.pdf').relative_to(ROOT)))
    report=dict(status='passed',candidate_movement_hours=len(mh),statistical_exclusions=quality,
        additional_controller_exclusions=len(mh)-quality-retained,retained_movement_hours=retained,
        retained_sites=len(sites),usable_site_hours=2307,pooled_calibration_cases=int(calibration['cases']),
        crossings=float(calibration['network_estimated_crossings_mean']),
        full_compliance_delay_h=float(calibration['network_delay_100_h_mean']),
        behaviour_scenario_delay_h=float(calibration['network_delay_behavior_h_mean']),
        weekly_common_cells=len(week_common),monthly_common_cells=len(month_common),
        numeric_reference_tables_checked=checked,generated_figures=figures,
        raw_history_reestimation='requires restricted histories and external SCATS decoder; not performed')
    (ROOT/'outputs/validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
