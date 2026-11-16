"""Cross-check serialized BOM, cut list, reports, and the printable STL."""
import csv
import json
import math
from collections import Counter
from pathlib import Path
from struct import iter_unpack, unpack_from

root=Path(__file__).resolve().parent

def rows(path):
    with (root/path).open(encoding="utf-8-sig",newline="") as file:
        return list(csv.DictReader(file))

bom=rows("BOM-octagon.csv")
index=rows("out/part-index.csv")
model_quantities=Counter(part["料号"] for part in index)
assert len({part["装配件名"] for part in index})==len(index)
assert all(int(item["模型数量"])==model_quantities.pop(item["料号"],0)
           and int(item["装机数量"])>=int(item["模型数量"]) for item in bom)
assert not model_quantities
cuts=rows("2020-cut-list.csv")
assert len(cuts)==65 and sum(int(c["定长_mm"]) for c in cuts)==18260
checks=json.loads((root/"out/geometry-check.json").read_text(encoding="utf-8"))
steps=json.loads((root/"out/STEP-readback.json").read_text(encoding="utf-8"))
assert checks["part_count"]==len(index)
mount=checks["handrail_mount"]
assert mount["flange_row_spacing_mm"]==50 and mount["flange_min_head_depth_mm"]>=6
assert mount["checked_spacer_stacks"]==8
assert mount["crossmember_edge_gaps_mm"]=={"rear":0,"left":0,"right":0}
assert mount["rear_frame_m6_hole_x_mm"]==[160,360,470,750]
assert mount["rear_frame_m6_hole_z_mm"]==20 and mount["rear_frame_m6_hole_diameter_mm"]==6.6
for sku in ("REAR-M6","REAR-W6","REAR-T6"):
    assert sum(part["料号"]==sku for part in index)==4
assert sum(p["料号"]=="RHS-W" for p in index)==4
handrail=steps["DDR-R1-handrail.step"]
assert handrail["assembly_components"]==handrail["readback_solids"]
assert "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in (root/"out/DDR-R1-handrail.step").read_text(encoding="utf-8")
assert len(checks["stop_support"])==32 and all(checks["stop_support"].values())
assert checks["pc_corner_cut_leg_mm"]==8
assert len(checks["pc_plate_thickness_mm"])==4 and set(checks["pc_plate_thickness_mm"].values())=={10}
assert list(checks["retainer_shim_thickness_mm"].values())==[1]*12
assert checks["nominal_z_gaps_mm"]["anti_lift"]==.5
assert checks["retainer_top_above_steel_mm"]==.5
assert checks["square_retainer_size_mm"]==26
for key,center in checks["square_retainer_centers_mm"].items():
    assert center==[int(coordinate) for coordinate in key.split(",")]
orientations=checks["square_retainer_orientation_deg"]
assert len(orientations)==4 and set(orientations.values())=={45}
shared=checks["square_retainer_coverage_mm2"]
outer=checks["outer_retainer_coverage_mm2"]
assert len(shared)==4 and all(len(c)==2 for c in shared.values())
assert len(outer)==8 and all(len(c)==1 for c in outer.values())
assert all(area>0 for m in (shared|outer).values() for area in m.values())
assert not any(checks["perimeter_steel_relief_count"].values())
assert min(checks["outer_retainer_grid_edge_gap_mm"].values())>0
assert list(checks["outer_retainer_triangle_edges"].values())==[3]*8
assert not any(checks["outer_retainer_post_xy_travel_overlap_mm3"].values())
assert len(checks["corner_seat_support_mm2"])==4 and min(checks["corner_seat_support_mm2"].values())>0
assert len(checks["pc_primary_stop_contact_mm2"])==32 and min(checks["pc_primary_stop_contact_mm2"].values())>0
assert checks["assembled_overlap_mm3"]==checks["exploded_overlap_mm3"]==[]
poses=checks["rigid_pc_travel"]
assert len(poses)==20 and all(not pose["rigid_overlap_mm3"] for pose in poses)
for name in ["DDR-R1-assembly.step","DDR-R1-exploded.step"]:
    info=steps[name]
    assert info["assembly_components"]==info["readback_solids"]==len(index)
    assert "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in (root/"out"/name).read_text(encoding="utf-8")
stl=(root/"print/LED-tray.stl").read_bytes()
count=unpack_from("<I",stl,80)[0]
assert len(stl)==84+50*count
edges=Counter()
points=set()
volume=0
for face in iter_unpack("<12fH",stl[84:]):
    a,b,c=(tuple(round(v,5) for v in face[i:i+3]) for i in (3,6,9))
    for u,v in [(a,b),(b,c),(c,a)]:
        edges[tuple(sorted([u,v]))]+=1
    points.update([a,b,c])
    volume+=(a[0]*(b[1]*c[2]-b[2]*c[1])
             +a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
assert all(n==2 for n in edges.values())
extent=[max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)]
assert all(math.isclose(n,m,abs_tol=.015) for n,m in zip(extent,[16,94,5]))
assert volume>0
print(f"{len(index)} named parts, {len(bom)} BOM rows; {len(cuts)} cuts; 20 PC poses; "
      f"STL closed ({count} triangles, {extent} mm).")
