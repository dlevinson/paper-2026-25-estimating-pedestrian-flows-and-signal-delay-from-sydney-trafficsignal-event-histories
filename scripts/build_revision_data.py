"""Reproduce the accepted site-hour denominator and figures from aggregate outputs.

Reads the public aggregate inputs; writes under outputs/revision.
No raw histories or event-level observations are needed.
"""
from pathlib import Path
import csv
import hashlib
import json
import math
import statistics
import collections

SOURCE = Path(__file__).resolve().parents[1]
OUT = SOURCE / 'outputs' / 'revision'
OUT.mkdir(parents=True, exist_ok=True)
FIG = OUT / 'figures'
FIG.mkdir(exist_ok=True)

def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write(path, rows):
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

site_input = SOURCE/'broad_results/network_20180918/pedestrian_site_hour_delay_20180918.csv'
rows = read(site_input)
usable = [r for r in rows if int(r['included_movement_hour_rows']) > 0]
excluded = [r for r in rows if int(r['included_movement_hour_rows']) == 0]
assert all(float(r['mcav_person_arrivals_conditioned']) == 0 and
           float(r['mcav_person_delay_h_conditioned']) == 0 for r in excluded)
assert sum(int(r['included_movement_hour_rows']) for r in usable) == 5114
counts = collections.Counter(r['site'] for r in usable)
original_sites = read(SOURCE/'paper/figures/paper2_scats_flow_map_sites.csv')
assert len(original_sites) == 174
new_sites = []
for old in original_sites:
    row = dict(old)
    row['exported_site_hours'] = old['usable_site_hours']
    row['usable_site_hours'] = counts[old['site']]
    row['estimated_crossings_per_usable_hour'] = float(old['estimated_crossings']) / counts[old['site']]
    new_sites.append(row)
write(OUT/'site_summary_corrected.csv', new_sites)
write(OUT/'site_hours_with_retained_movements.csv', usable)

# Run the original density calculation with corrected input and redirected outputs.
# The density script includes the accepted retained-site-hour correction.
source_script = SOURCE/'paper/scripts/build_paper2_distribution_data.py'
code = source_script.read_text()
namespace = {'__file__': str(source_script), '__name__': 'revision_density'}
exec(compile(code, str(source_script), 'exec'), namespace)
namespace['OUTPUT'] = FIG/'paper2_scats_pedestrian_distribution_data.csv'
namespace['CALIBRATION_SUMMARY_OUTPUT'] = OUT/'calibration_summary_verified.csv'
namespace['SITE_SUMMARY_OUTPUT'] = OUT/'site_distribution_summary_corrected.csv'
namespace['main']()
(FIG/'paper2_scats_pedestrian_distributions.tex').write_text(
    (SOURCE/'paper/figures/paper2_scats_pedestrian_distributions.tex').read_text())

inventory = read(SOURCE/'derived_inputs/map_site_coordinates.csv')
by_site = {r['site']: r for r in new_sites}
assert len({r['TCS_NO'] for r in inventory}) == 229
groups = collections.defaultdict(list)
for row in inventory:
    groups[(float(row['X_COORD']), float(row['Y_COORD']))].append(row)

# Scientific figure generated directly from tabular data. Small deterministic
# offsets expose sites sharing rounded coordinates; true grid anchors are shown.
tex = [r'\documentclass[tikz,border=5pt]{standalone}',
       r'\usepackage{helvet}\renewcommand{\familydefault}{\sfdefault}',
       r'\begin{document}\begin{tikzpicture}[font=\small]']
xmin,xmax,ymin,ymax=150.99,151.23,-33.895,-33.745
def xy(lon,lat): return ((lon-xmin)/(xmax-xmin)*7.4,(lat-ymin)/(ymax-ymin)*5.8)
palette=['440154','3B528B','21918C','5EC962','FDE725']
def colour(v):
    t=min(1,max(0,(math.log10(v)-1)/(math.log10(1000)-1)))*4
    i=min(3,int(t)); a=t-i
    rgb=[]
    for j in (0,2,4):rgb.append(round(int(palette[i][j:j+2],16)*(1-a)+int(palette[i+1][j:j+2],16)*a))
    return ''.join(f'{v:02X}' for v in rgb)
tex += [r'\node[font=\bfseries,anchor=west] at (0,6.25) {A. Metropolitan Sydney};',
        r'\draw[gray] (0,0) rectangle (7.4,5.8);']
for lon in [151.00,151.05,151.10,151.15,151.20]:
    x,_=xy(lon,ymin)
    tex += [fr'\draw[gray!20] ({x},0)--({x},5.8);',fr'\node[below,font=\scriptsize] at ({x},0) {{{lon:.2f}}};']
for lat in [-33.88,-33.84,-33.80,-33.76]:
    _,y=xy(xmin,lat)
    tex += [fr'\draw[gray!20] (0,{y})--(7.4,{y});',fr'\node[left,font=\scriptsize] at (0,{y}) {{{lat:.2f}}};']
tex += [r'\node at (3.7,-0.65) {Longitude};',r'\node[rotate=90] at (-1.0,2.9) {Latitude};']
positions=[]
for (lon,lat),group in sorted(groups.items()):
    x,y=xy(lon,lat)
    group.sort(key=lambda r:int(r['TCS_NO']))
    n=len(group)
    if n>1:tex.append(fr'\fill[gray!70] ({x},{y}) circle (0.014);')
    for index,row in enumerate(group):
        angle=2*math.pi*index/n
        radius=0 if n==1 else max(0.11,n*0.025)
        xx=x+radius*math.cos(angle); yy=y+radius*math.sin(angle)
        if n>1:tex.append(fr'\draw[gray!60,line width=0.15pt] ({x},{y})--({xx},{yy});')
        site=row['TCS_NO']; d=by_site.get(site)
        c=colour(d['estimated_crossings_per_usable_hour']) if d else 'D5D5D5'
        tex += [fr'\definecolor{{site{site}}}{{HTML}}{{{c}}}',fr'\filldraw[fill=site{site},draw=black!65,line width=0.18pt] ({xx},{yy}) circle (0.043);']
        if site=='516':
            tex += [fr'\draw[black,line width=0.5pt] ({xx},{yy}) circle (0.10);',fr'\node[above right,font=\tiny] at ({xx+0.04},{yy+0.07}) {{516}};']
        positions.append({'site':site,'lon':lon,'lat':lat,'display_x_cm':xx,'display_y_cm':yy,'sites_at_coordinate':n})
for i,v in enumerate([10,20,50,100,200,500,1000]):
    x=.45+i*.93
    tex += [fr'\definecolor{{legend{i}}}{{HTML}}{{{colour(v)}}}',fr'\filldraw[fill=legend{i},draw=black!65,line width=.18pt] ({x},-1.15) circle (.055);',fr'\node[below,font=\scriptsize] at ({x},-1.22) {{{v:,}}};']
tex += [r'\node[font=\scriptsize] at (3.7,-1.8) {Estimated crossings per usable site-hour};',
        r'\node[font=\scriptsize] at (3.7,-2.15) {Grey: no retained estimate. Linked symbols share rounded coordinates.};']
# Scale bar at latitude 33.82 S; approximate map scale.
dx=5/(111.32*math.cos(math.radians(33.82)))/(xmax-xmin)*7.4
tex += [fr'\draw[|-|,line width=.7pt] (.35,.35)--({.35+dx},.35) node[midway,above,font=\scriptsize] {{5 km}};',r'\draw[->] (7.02,4.92)--(7.02,5.42) node[above,font=\scriptsize] {N};']

focus=read(SOURCE/'paper/figures/paper2_scats_flow_map_site516.csv')
tex += [r'\node[font=\bfseries,anchor=west] at (8.5,6.25) {B. Willoughby Road / Albany Street};']
cols=['1B9E77','D95F02','7570B3','E7298A']
for idx,r in enumerate(focus):
    def loc(lon,lat):return (8.85+(lon-151.2008)/.00026*4.8, .65+(lat+33.82393)/.00022*4.5)
    x1,y1=loc(float(r['start_lon']),float(r['start_lat']));x2,y2=loc(float(r['end_lon']),float(r['end_lat']))
    v=float(r['estimated_crossings']); w=1.5+3.2*v/2576.8912
    tex += [fr'\definecolor{{mov{idx}}}{{HTML}}{{{cols[idx]}}}',fr'\draw[mov{idx},line width={w}pt,line cap=round] ({x1},{y1})--({x2},{y2});']
    for x,y in [(x1,y1),(x2,y2)]:tex.append(fr'\filldraw[fill=white,draw=mov{idx},line width=.4pt] ({x},{y}) circle (.045);')
    tex.append(fr'\node[anchor=west,font=\scriptsize,text=mov{idx}] at (8.8,{5.65-idx*.27}) {{Crosswalk {r["movement"]}: {v:,.0f} crossings}};')
tex += [r'\draw[->] (13.35,.85)--(13.35,1.5) node[above,font=\scriptsize] {N};']
dx=20/(111320*math.cos(math.radians(33.8238)))/.00026*4.8
tex += [fr'\draw[|-|,line width=.7pt] (9.4,.25)--({9.4+dx},.25) node[midway,above,font=\scriptsize] {{20 m}};',
        r'\node[align=center,font=\scriptsize] at (11.25,-.7) {Line width: estimated crossings over usable hours.\\Both travel directions are combined within each crosswalk.};',r'\end{tikzpicture}\end{document}']
(FIG/'paper2_scats_flow_map.tex').write_text('\n'.join(tex))
write(OUT/'map_display_positions.csv',positions)
coverage=[r['usable_site_hours'] for r in new_sites]
audit={
 'sites':len(new_sites), 'retained_movement_hours':5114,
 'old_site_hours':sum(int(r['usable_site_hours']) for r in original_sites),
 'corrected_site_hours':sum(coverage),
 'corrected_hours_min_median_max':[min(coverage),statistics.median(coverage),max(coverage)],
 'site516_old_hours':20,'site516_corrected_hours':counts['516'],
 'rounded_coordinate_groups_positive':len({(r['lon'],r['lat']) for r in new_sites}),
 'positive_sites':174,
 'unchanged_metrics':['crossing count','total delay','average delay','calibration factors'],
 'source_sha256':{str(p.relative_to(SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [site_input,source_script,SOURCE/'derived_inputs/map_site_coordinates.csv']}
}
(OUT/'calculation_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps(audit,indent=2))
