"""Write DDR engineering interchange files from the parametric parts registry."""
import csv
import json
from collections import Counter
from math import sqrt
from pathlib import Path

import cadquery as cq
import design as d

OUT = d.ROOT / "out"
DIST = d.ROOT / "print"
SECTIONS = {
    "F": "前箭头", "L": "左箭头", "R": "右箭头", "B": "后箭头",
    "Base": "底板", "Frame": "骨架", "Rear": "扶手", "Center": "控制器", "Retainers": "交点方压片",
    "C": "中心检修盖", "FL": "左前固定格", "FR": "右前固定格",
    "BL": "左后固定格", "BR": "右后固定格", "Edge_F": "前边带",
    "Edge_B1": "后边带前半", "Edge_B2": "后边带后半",
    "Edge_L": "左边带", "Edge_R": "右边带",
    "Case_F": "前侧围", "Case_B": "后侧围", "Case_L": "左侧围", "Case_R": "右侧围",
}

def solid_bounds(shape):
    b = shape.BoundingBox()
    return (b.xmin,b.xmax,b.ymin,b.ymax,b.zmin,b.zmax)

def rounded(values, places=4):
    return [round(v,places) for v in values]

def bounds(parts, exploded=False):
    pairs = []
    for p in parts:
        b = solid_bounds(p.shape)
        offset = p.offset if exploded else (0,0,0)
        pairs.append([v+offset[k//2] for k,v in enumerate(b)])
    return rounded([min(row[k] for row in pairs) if k%2==0 else max(row[k] for row in pairs)
                    for k in range(6)])

def table(path, headers, rows):
    with path.open("w",newline="",encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)

def write_bom():
    model_qty = Counter(p.sku for p in d.PARTS)
    reported = 0
    bom = []
    for sku, item in sorted(d.ITEMS.items()):
        n = model_qty[sku]
        absences = d.UNMODELED.get(sku, 0)
        reported += n
        if n+absences:
            bom.append((sku,item.name,item.spec,n,n+absences,item.process,item.keyword,item.spare,item.remark))
    assert reported == len(d.PARTS)
    table(d.ROOT / "BOM-octagon.csv",("料号","零件","规格_mm","模型数量","装机数量","取得方式","购物关键词",
        "建议另备","备注"),bom)
    rails = sorted(d.RAILS,key=lambda r:(-(r[3]-r[2]),r[0]))
    table(d.ROOT / "2020-cut-list.csv",
          ("构件","轴线","起点_mm","终点_mm","跨轴中心_mm","定长_mm","分组"),
          [(name,axis,start,end,cross,end-start,SECTIONS[group]) for name,axis,start,end,cross,_,group in rails])
    table(OUT / "part-index.csv",("装配件名","料号","分组","层","材料","质量估算_kg"),
          [(p.name,p.sku,SECTIONS.get(p.group,p.group),p.layer,d.MATERIALS[p.material][0],
            f"{p.shape.Volume()*d.MATERIALS[p.material][2]/1e9:.6f}") for p in d.PARTS])

def collisions(parts, exploded=False):
    checks = []
    for p in parts:
        shift = p.offset if exploded else (0,0,0)
        shape = p.shape.translate(shift) if any(shift) else p.shape
        checks.append((solid_bounds(shape),p,shape))
    checks.sort(key=lambda check:check[0][0])
    hits=[]
    checked=0
    for i,(box,p,shape) in enumerate(checks):
        for test,q,other in checks[i+1:]:
            if test[0]>=box[1]-0.005:
                break
            if any(min(box[k+1],test[k+1])-max(box[k],test[k])<0.005 for k in (0,2,4)):
                continue
            checked+=1
            common=shape.intersect(other)
            volume=common.Volume()
            if volume>0.01:
                hits.append((p.name,q.name,round(volume,4)))
    return checked,sorted(hits,key=lambda pair:-pair[2])


def verify_pc_travel():
    nearby = []
    for p in d.PARTS:
        if p.sku in ("AR-PC","FS-A","RET"):
            continue
        b = solid_bounds(p.shape)
        if b[5]>32.45 and b[4]<44:
            nearby.append((p,b))
    result = []
    corner_poses = [(f"corner {ax}:{ay}",-0.108,ax*0.08,ay*0.08)
                    for ax in (-1,1) for ay in (-1,1)]
    for module,(x,y) in d.ARROWS.items():
        panel=next(p.shape for p in d.PARTS if p.name==f"{module}_Polycarbonate")
        for label,dz,ax,ay in [("flat travel",-.5,0,0)]+corner_poses:
            moved=panel.translate((0,0,dz))
            if ax:
                moved=moved.rotate((x,y,38),(x+1,y,38),ax)
                moved=moved.rotate((x,y,38),(x,y+1,38),ay)
            b = solid_bounds(moved)
            contact = []
            for p,c in nearby:
                if any(min(b[k+1],c[k+1])-max(b[k],c[k])<0.004 for k in (0,2,4)):
                    continue
                volume = moved.intersect(p.shape).Volume()
                if volume>.01:
                    contact.append((p.name,round(volume,4)))
            result.append({"module":module,"pose":label,"down_mm":-dz,
                           "tilt_degrees":[ax,ay],"rigid_overlap_mm3":contact})
    return result

def mass_center():
    points=[]
    for p in d.PARTS:
        mass = p.shape.Volume()*d.MATERIALS[p.material][2]/1e9
        pos = p.shape.Center().toTuple()
        points.append((mass,pos))
    total=sum(mass for mass,_ in points)
    return rounded([sum(mass*pos[axis] for mass,pos in points)/total for axis in range(3)],2)

def arrow_step_parts():
    from dataclasses import replace

    x,y=d.ARROWS["F"]
    limits=d.box(x-178,x+178,y-178,y+178,-3,155)
    selected=[]
    window = solid_bounds(limits)[:4]
    for p in d.PARTS:
        in_window = d.box_overlap(solid_bounds(p.shape)[:4],window)
        if p.group=="F" or (p.group=="Retainers" and in_window):
            selected.append(p)
        elif p.layer in ("rail","wood","top") and in_window:
            clipped=p.shape.intersect(limits)
            if clipped.Volume()>.01:
                selected.append(replace(p,shape=clipped))
    return selected


def record_checks():
    report = dict(d.CHECKS)
    all_names = {p.name:p for p in d.PARTS}
    rails = [p for p in d.PARTS if p.sku.startswith("AL-")]
    report["part_count"] = len(d.PARTS)
    report["solid_count"] = sum(len(p.shape.Solids()) for p in d.PARTS)
    report["rail_count"] = len(rails)
    report["rail_bounds_mm"] = bounds(rails)
    report["body_bounds_mm"] = bounds([p for p in d.PARTS if p.layer!="handrail"])
    report["full_bounds_mm"] = bounds(d.PARTS)
    report["exploded_bounds_mm"] = bounds(d.PARTS,True)
    report["invalid_parts"] = [p.name for p in d.PARTS if not p.shape.isValid()]
    report["mass_kg"] = {}
    for p in d.PARTS:
        layer = p.layer
        report["mass_kg"][layer] = report["mass_kg"].get(layer,0)+p.shape.Volume()*d.MATERIALS[p.material][2]/1e9
    report["mass_kg"] = dict((k,round(v,3)) for k,v in sorted(report["mass_kg"].items()))
    report["total_geom_mass_kg"] = round(sum(report["mass_kg"].values()),3)
    report["cg_mm"] = mass_center()
    report["rigid_pc_travel"] = verify_pc_travel()
    report["arrow_geometry"] = {
        name:solid_bounds(all_names[f"{name}_Polycarbonate"].shape) for name in d.ARROWS
    }
    report["pc_corner_cut_leg_mm"] = d.PC_CORNER_CUT
    report["pc_plate_thickness_mm"] = {}
    for name,(x,y) in d.ARROWS.items():
        panel = all_names[f"{name}_Polycarbonate"].shape
        expected = {(px,py,z) for px,py in d.pc_outline(x,y) for z in (d.PC_Z,d.PC_TOP)}
        actual = {tuple(rounded(v.toTuple())) for v in panel.Vertices()}
        assert actual == expected, (name,actual)
        thickness = d.PC_TOP-d.PC_Z
        volume = (d.PC_SIZE**2-2*d.PC_CORNER_CUT**2)*thickness
        assert abs(panel.Volume()-volume)<.001
        report["pc_plate_thickness_mm"][name] = thickness
    span = d.PITCH/2-d.SENSOR_V
    report["sensor_actuator_centers_mm"] = {}
    for module,(x,y) in d.ARROWS.items():
        centers = {}
        for side in d.SIDES:
            p = all_names[f"{module}_{side}_Silicone"]
            box = solid_bounds(p.shape)
            centers[side] = rounded(((box[0]+box[1])/2,(box[2]+box[3])/2,box[5]))
        expected = {"N": [x,y-span], "E": [x+span,y],
                    "S": [x,y+span], "W": [x-span,y]}
        assert all(c == expected[side]+[d.BUTTON_TOP] for side,c in centers.items())
        report["sensor_actuator_centers_mm"][module] = centers
    report["nominal_z_gaps_mm"] = {
        "sensor_neutral": round(d.PC_Z-d.BUTTON_TOP,3),
        "stop_neutral": d.PC_Z-d.STOP_TOP,
        "silicone_compression_at_flat_stops": round(d.BUTTON_TOP-d.STOP_TOP,3),
        "anti_lift": round(d.RETAINER_BOTTOM-d.PC_TOP,3), "LED_at_flat_stops": d.STOP_TOP-16,
    }
    report["stop_support"] = {}
    for p in d.PARTS:
        if p.layer!="stopshim":
            continue
        x0,x1,y0,y1,z0,z1=solid_bounds(p.shape)
        # Sample a 0.02 mm slice just below the bridge, at the plane of both bearing lands.
        patch = d.box(x0+.015,x1-.015,y0+.015,y1-.015,z0-.02,z0)
        matches = []
        for rail in rails:
            a0,a1,b0,b1,_,_=solid_bounds(rail.shape)
            if a0>=x1 or a1<=x0 or b0>=y1 or b1<=y0:
                continue
            area=patch.intersect(rail.shape).Volume()/.02
            if area>.1:
                matches.append([rail.name,round(area,1)])
        report["stop_support"][p.name] = matches
    report["corner_seat_support_mm2"] = {}
    for p in d.PARTS:
        if p.sku != "ANTI-S":
            continue
        footprint = solid_bounds(p.shape)[:4]
        sample = p.shape.translate((0,0,-.02))
        area = sum(sample.intersect(rail.shape).Volume()/.02 for rail in rails
                   if d.box_overlap(footprint,solid_bounds(rail.shape)[:4]))
        report["corner_seat_support_mm2"][p.name] = round(area,1)

    sample_height = .02
    projections = {m:d.poly(d.pc_outline(x,y),d.RETAINER_BOTTOM,d.RETAINER_BOTTOM+sample_height)
                   for m,(x,y) in d.ARROWS.items()}
    report["retainer_shim_thickness_mm"] = {}
    for p in d.PARTS:
        if p.sku in ("ANTI-W3","ANTI-W4"):
            *_,z0,z1=solid_bounds(p.shape)
            assert abs(z0-d.RETAINER_SEAT_TOP)<.001 and abs(z1-d.RETAINER_BOTTOM)<.001
            report["retainer_shim_thickness_mm"][p.name] = round(z1-z0,3)
    report["retainer_top_above_steel_mm"] = round(d.RETAINER_TOP-44,3)
    report["square_retainer_size_mm"] = d.CLIP_SIZE
    report["square_retainer_orientation_deg"] = {}
    report["square_retainer_centers_mm"] = {}
    report["square_retainer_coverage_mm2"] = {}
    report["outer_retainer_coverage_mm2"] = {}
    report["outer_retainer_grid_edge_gap_mm"] = {}
    report["outer_retainer_triangle_leg_mm"] = d.OUTER_TRIANGLE_LEG
    report["outer_retainer_triangle_edges"] = {}
    report["outer_retainer_post_xy_travel_overlap_mm3"] = {}
    for (x,y),modules in d.retainer_nodes().items():
        cover = all_names[f"Corner_{x}_{y}_Cover"].shape
        a,b,c,e,z0,z1=solid_bounds(cover)
        assert abs(z0-d.RETAINER_BOTTOM)<.001 and abs(z1-d.RETAINER_TOP)<.001
        cell = f"{x},{y}"
        covered = {m:round(cover.intersect(projections[m]).Volume()/sample_height,2) for m in modules}
        if len(modules)==1:
            report["outer_retainer_coverage_mm2"][cell] = covered
            report["outer_retainer_triangle_edges"][cell] = sum(
                e.geomType()=="LINE" and all(abs(v.Z-d.RETAINER_BOTTOM)<.001 for v in e.Vertices())
                for e in cover.Edges()
            )
            post = all_names[f"Corner_{x}_{y}_Post"].shape
            panel = all_names[f"{modules[0]}_Polycarbonate"].shape
            toward_x = -.8 if d.ARROWS[modules[0]][0]>x else .8
            toward_y = -.8 if d.ARROWS[modules[0]][1]>y else .8
            shifted = panel.translate((toward_x,toward_y,0))
            report["outer_retainer_post_xy_travel_overlap_mm3"][cell] = round(
                post.intersect(shifted).Volume(),5
            )
            report["outer_retainer_grid_edge_gap_mm"][cell] = round(min(
                a-d.GRID_X, d.GRID_X+3*d.PITCH-b, c-d.GRID_Y, d.GRID_Y+3*d.PITCH-e
            ),2)
            continue
        span = d.CLIP_SIZE/sqrt(2)
        assert abs(b-a-2*span)<0.001 and abs(e-c-2*span)<0.001
        cx,cy = (a+b)/2,(c+e)/2
        assert rounded((cx,cy)) == [x,y]
        report["square_retainer_centers_mm"][f"{x},{y}"] = rounded((cx,cy))
        expected = {tuple(rounded(p)) for p in
                    [(cx-span,cy),(cx+span,cy),(cx,cy-span),(cx,cy+span)]}
        actual = {tuple(rounded((v.X,v.Y))) for v in cover.Vertices() if abs(v.Z-d.RETAINER_BOTTOM)<0.001}
        assert expected <= actual, (x,y,expected,actual)
        report["square_retainer_orientation_deg"][f"{x},{y}"] = 45
        report["square_retainer_coverage_mm2"][cell] = covered

    report["pc_primary_stop_contact_mm2"] = {}
    for p in d.PARTS:
        if p.sku != "HS-23":
            continue
        panel = all_names[f"{p.group}_Polycarbonate"].shape
        sample = p.shape.translate((0,0,d.PC_Z-d.STOP_TOP+.02))
        report["pc_primary_stop_contact_mm2"][p.name] = round(sample.intersect(panel).Volume()/.02,1)

    print("checking assembled solids",flush=True)
    checked,hit = collisions(d.PARTS)
    report["assembled_candidate_pairs"], report["assembled_overlap_mm3"] = checked, hit
    print("checking exploded positions",flush=True)
    checked,hit = collisions(d.PARTS,True)
    report["exploded_candidate_pairs"], report["exploded_overlap_mm3"] = checked,hit
    (OUT / "geometry-check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    assert report["body_bounds_mm"][:4] == [0.,890.,0.,1080.]
    assert report["rail_bounds_mm"] == [2.,888.,2.,1078.,10.,30.]
    assert report["full_bounds_mm"][-1] == 964.
    assert all(report["stop_support"].values())
    shared = report["square_retainer_coverage_mm2"]
    outer = report["outer_retainer_coverage_mm2"]
    assert len(shared)==4 and all(len(c)==2 for c in shared.values())
    assert len(outer)==8 and all(len(c)==1 for c in outer.values())
    assert all(area>0 for covered in (shared|outer).values() for area in covered.values())
    assert min(report["outer_retainer_grid_edge_gap_mm"].values()) > 0
    assert set(report["outer_retainer_triangle_edges"].values())=={3}
    assert not any(report["outer_retainer_post_xy_travel_overlap_mm3"].values())
    assert len(report["retainer_shim_thickness_mm"])==12
    assert set(report["retainer_shim_thickness_mm"].values())=={1}
    assert report["nominal_z_gaps_mm"]["anti_lift"]==.5
    assert len(report["perimeter_steel_relief_count"])==5
    assert not any(report["perimeter_steel_relief_count"].values())
    assert len(report["corner_seat_support_mm2"]) == 4
    assert min(report["corner_seat_support_mm2"].values()) > 0
    assert len(report["pc_primary_stop_contact_mm2"]) == 32
    assert min(report["pc_primary_stop_contact_mm2"].values()) > 0
    assert not report["invalid_parts"]
    assert not report["bracket_unplaced"]
    assert not report["assembled_overlap_mm3"], report["assembled_overlap_mm3"]
    assert not hit, hit
    assert not any(p["rigid_overlap_mm3"] for p in report["rigid_pc_travel"]), report["rigid_pc_travel"]
    print(f"assembled overlaps {len(report['assembled_overlap_mm3'])}, exploded overlaps {len(hit)}",flush=True)

def step(title, name, parts, exploded=False):
    path=OUT / name
    report_path=OUT / "STEP-readback.json"
    previous = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    print(f"exporting {name} ({len(parts)} parts)",flush=True)
    d.assemble(title,parts,exploded).export(str(path),exportType="STEP",mode="default",
                                           write_pcurves=False)
    imported=cq.importers.importStep(str(path)).val()
    b=rounded(solid_bounds(imported))
    if b != bounds(parts,exploded):
        assert max(abs(x-y) for x,y in zip(b,bounds(parts,exploded))) < 0.002, (b,bounds(parts,exploded))
    solid_ct = len(imported.Solids())
    assert solid_ct == sum(len(p.shape.Solids()) for p in parts)
    previous[name] = {"assembly_components":len(parts),"readback_solids":solid_ct,"bounds_mm":b}
    report_path.write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding="utf-8")

def preview():
    import base64
    import struct

    # Convert the same OpenCascade solids to compact position/normal triangles for WebGL.
    # Bake the face normals here to keep individual machined edges visible.
    data = []
    packed = bytearray()
    for p in d.PARTS:
        pts,faces=p.shape.tessellate(0.45,0.21)
        start=len(packed)//12
        for face in faces:
            for i in face:
                packed.extend(struct.pack("<fff",*pts[i].toTuple()))
        name=d.ITEMS[p.sku].name
        data.append([p.name,name,p.sku,p.group,p.layer,d.MATERIALS[p.material][1],
                     list(p.offset),start,len(packed)//12-start])
    vendor = (d.ROOT / "viewer" / "three.min.js").read_text(encoding="utf-8")
    license = (d.ROOT / "viewer" / "LICENSE-three.txt").read_text(encoding="utf-8")
    template = (d.ROOT / "viewer" / "template.html").read_text(encoding="utf-8")
    tag = json.dumps(data,ensure_ascii=False,separators=(",",":"))
    payload = json.dumps(base64.b64encode(packed).decode("ascii"))
    html=template.replace("/*__VENDOR__*/",f"/*\n{license}\n*/\n{vendor}")
    html=html.replace("/*__PARTS__*/",tag).replace("/*__POSITIONS__*/",payload)
    (d.ROOT / "DDR-R1-3D.html").write_text(html,encoding="utf-8")

def run(mode):
    OUT.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    write_bom()
    if mode in ("check","all"):
        record_checks()
    if mode in ("export","all"):
        step("DDR_R1_Assembly","DDR-R1-assembly.step",d.PARTS)
        step("DDR_R1_Exploded","DDR-R1-exploded.step",d.PARTS,True)
        module=arrow_step_parts()
        step("DDR_R1_Arrow_F","DDR-R1-arrow-F.step",module)
        d.led_cradle().exportStl(str(DIST / "LED-tray.stl"),tolerance=.08,angularTolerance=.14)
        preview()
