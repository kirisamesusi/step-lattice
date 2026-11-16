"""DDR R1 parametric nominal assembly. Dimensions in millimeters."""
from collections import Counter
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
import argparse
import cadquery as cq

ROOT = Path(__file__).resolve().parent
W, D, SHELL = 890, 1080, 2
GRID_X, GRID_Y, PITCH = 25, 82, 280
WOOD_BOTTOM, WOOD_TOP, DECK = 30, 42, 44
PC_SIZE, PC_Z, PC_TOP = 274, 33, 43
PC_CORNER_CUT = 8
RAIL_Z, RAIL_TOP = 10, 30
BASE_STEEL = 1  # floor-side steel sheet under the 9 mm plywood
RING_V = 120  # arrow center to the center of its inner ring rail
STOP_TOP = 32.5
POSTS, POST_Y, GRIP = (240, 650), 1038, 964
ARROWS = {"F": (445, 222), "L": (165, 502), "R": (725, 502), "B": (445, 782)}
FIXED = {"FL": (165, 222), "FR": (725, 222), "C": (445, 502),
         "BL": (165, 782), "BR": (725, 782)}
# Rotation maps local +Y toward the panel center. Local origin is the cell edge.
SIDES = {"N": (0, -140, 0), "E": (140, 0, 90), "S": (0, 140, 180), "W": (-140, 0, 270)}
MATERIALS = {
    "ply": ("海洋板", "#ab855e", 650),
    "304": ("304 不锈钢", "#7b8b9c", 7930),
    "coat": ("喷塑不锈钢", "#27313d", 7930),
    "al": ("2020 铝型材", "#a2b5c8", 2700),
    "al6061": ("6061 铝合金", "#a2b5c8", 2700),
    "pc": ("实心透光 PC", "#66a9ff", 1200),
    "pc2": ("实心透光 PC", "#ee619d", 1200),
    "rubber": ("密实橡胶", "#27292f", 1150),
    "galv": ("镀锌钢板喷塑", "#46525f", 7850),
    "spring": ("微孔弹性体", "#b974ee", 350),
    "silicone": ("软硅胶", "#ffd77e", 1120),
    "fsr": ("柔性 FSR", "#ee9a36", 1450),
    "steel": ("碳钢", "#53616e", 7850),
    "zinc": ("镀锌钢", "#c7cedc", 7850),
    "pOM": ("黑色 POM", "#2b3540", 1410),
    "petg": ("PETG", "#7666cb", 1270),
    "pcb": ("PCB/元件包络", "#239b77", 1750),
    "led": ("WS2812B 灯带", "#83e6b8", 1550),
    "diff": ("乳白扩散片", "#eef5e9", 1200),
}
LAYERS = {
    "floor": (0, 0, -50), "basesteel": (0, 0, -37), "base": (0, 0, -13),
    "rail": (0, 0, 30), "join": (0, 0, 52), "rear": (0, 0, 30),
    "rearHardware": (0, 0, 58), "skin": (0, 0, 0),
    "electronics": (0, 0, 86), "led": (0, 0, 65), "diff": (0, 0, 83),
    "carrier": (0, 0, 101), "fsr": (0, 0, 125), "return": (0, 0, 145),
    "stopshim": (0, 0, 109), "stop": (0, 0, 139), "guide": (0, 0, 170),
    "wood": (0, 0, 195), "top": (0, 0, 264), "pc": (0, 0, 233),
    "clipshim": (0, 0, 291), "clip": (0, 0, 322), "fixing": (0, 0, 350),
    "handrail": (0, 138, 330), "flange": (0, 138, 330),
}
@dataclass
class Part:
    name: str
    sku: str
    shape: cq.Shape
    material: str
    layer: str
    group: str
    offset: tuple

@dataclass
class Item:
    name: str
    spec: str
    process: str
    keyword: str
    spare: str = ""
    remark: str = ""

PARTS = []
ITEMS = {}
RAILS = []
UNMODELED = {}
CHECKS = {}

def item(sku, name, spec, process, keyword, spare="", remark=""):
    ITEMS[sku] = Item(name, spec, process, keyword, spare, remark)

def add(name, sku, shape, material, layer, group="", offset=None):
    assert sku in ITEMS, sku
    assert not any(p.name == name for p in PARTS), name
    part = Part(name, sku, shape, material, layer, group, LAYERS[layer] if offset is None else offset)
    PARTS.append(part)
    return part

def consumable(sku, quantity, *description):
    item(sku, *description)
    UNMODELED[sku] = quantity

def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, cq.Vector(x0, y0, z0))

def rect(cx, cy, w, d, z0, z1):
    return box(cx-w/2, cx+w/2, cy-d/2, cy+d/2, z0, z1)

def cyl(cx, cy, radius, z0, z1):
    return cq.Solid.makeCylinder(radius, z1-z0, cq.Vector(cx, cy, z0))

def tip(cx, cy, r0, r1, z0, z1):
    return cq.Solid.makeCone(r0, r1, z1-z0, cq.Vector(cx, cy, z0))

def poly(points, z0, z1):
    return cq.Workplane("XY", origin=(0, 0, z0)).polyline(points).close().extrude(z1-z0).val()

def bevel_rect(x0, x1, y0, y1, z0, z1, chamfer):
    return (cq.Workplane("XY").newObject([box(x0,x1,y0,y1,z0,z1)])
            .edges("|Z").fillet(chamfer).val())

def remove(shape, holes):
    return shape.cut(*holes).clean() if holes else shape

def translate(shape, x, y, z=0):
    return shape.translate((x, y, z))

def local(shape, module, side):
    x, y = ARROWS[module]
    dx, dy, angle = SIDES[side]
    return translate(shape.rotate((0,0,0),(0,0,1),angle),x+dx,y+dy)

def screw_model(x, y, major, bottom, shoulder, top, head):
    shaft = cyl(x, y, major/2, bottom, shoulder)
    return shaft.fuse(tip(x,y,major/2,head/2,shoulder,top)).clean()

def drill_cs(x,y,diam,head,bottom,shoulder,top):
    return [cyl(x,y,diam/2,bottom,shoulder+0.01), tip(x,y,diam/2,head/2,shoulder,top)]

def rail_blank(length):
    # Nominal slot model. Top/end datums and mouths are designed, groove profile must be measured.
    body = box(-10,10,-10,10,0,length)
    slot = poly([(-3.15,10.1),(3.15,10.1),(3.15,8.8),(5.35,8.8),
                 (5.35,5.65),(2.7,4.5),(-2.7,4.5),(-5.35,5.65),
                 (-5.35,8.8),(-3.15,8.8)], -1,length+1)
    central = cyl(0,0,2.05,-1,length+1)
    return remove(body,[central]+[slot.rotate((0,0,0),(0,0,1),a) for a in (0,90,180,270)])

def rail(name, axis, start, end, cross, group="Frame"):
    length = end-start
    sku = f"AL-{length:04d}"
    if sku not in ITEMS:
        item(sku, "2020 定长料", f"20×20×{length}", "现料锯切",
             "欧标 2020 花孔 6 mm 槽（用现料）", "",
             "端面垂直、去毛刺。槽口、底腔、端孔和槽螺母以实际挤型抽检为准。")
    shape = RAIL_BLANKS.setdefault(length, rail_blank(length)) if length not in RAIL_BLANKS else RAIL_BLANKS[length]
    if axis == "X":
        shape = translate(shape.rotate((0,0,0),(0,1,0),90),start,cross,20)
        envelope = (start,end,cross-10,cross+10)
    else:
        shape = translate(shape.rotate((0,0,0),(1,0,0),-90),cross,start,20)
        envelope = (cross-10,cross+10,start,end)
    RAILS.append((name,axis,start,end,cross,envelope,group))
    add(name,sku,shape,"al","rail",group)

RAIL_BLANKS = {}

def frame():
    for tag,x in (("L",12),("R",878)):
        rail(f"Outer_{tag}","Y",2,1078,x)
    for tag,y in (("F",12),("B",1068)):
        rail(f"Outer_{tag}","X",22,868,y)
    for tag,x in (("L",305),("R",585)):
        rail(f"Grid_long_{tag}","Y",22,REAR_FRONT,x)
    for y in (45,82,362,642,922):
        zones = [(22,295),(315,575),(595,868)]
        if y == 922:
            zones = [(22,220),(260,295),(315,575),(595,630),(670,868)]
        for i,(a,b) in enumerate(zones):
            rail(f"Grid_{y}_{i+1}","X",a,b,y)
    rail("L_Stop_Outer_Rail","Y",372,632,32,"L")
    rail("R_Stop_Outer_Rail","Y",372,632,858,"R")
    for k,(x,y) in ARROWS.items():
        # A second 2020 lies against every grid rail inside the arrow cell, so each
        # panel edge, its stops and its sensor seat rest on extrusion of one height.
        # The outer edges of L and R already have their doubled rail above.
        left = 42 if k=="L" else x-130
        right = 848 if k=="R" else x+130
        for tag,cy in (("N",y-RING_V),("S",y+RING_V)):
            rail(f"{k}_Ring_{tag}","X",left,right,cy,k)
        west = left if k=="L" else x-RING_V-10
        east = right if k=="R" else x+RING_V+10
        if k!="L":
            rail(f"{k}_Ring_W","Y",y-RING_V+10,y+RING_V-10,x-RING_V,k)
            west = x-RING_V+10
        if k!="R":
            rail(f"{k}_Ring_E","Y",y-RING_V+10,y+RING_V-10,x+RING_V,k)
            east = x+RING_V-10
        rail(f"{k}_Cross_Long","Y",y-RING_V+10,y+RING_V-10,x,k)
        rail(f"{k}_Cross_Left","X",west,x-10,y,k)
        rail(f"{k}_Cross_Right","X",x+10,east,y,k)
    for y in (157,287,717,847):
        zones = [(22,295),(595,868)]
        if y == 847:
            zones = [(22,220),(260,295),(595,630),(670,868)]
        for i,(a,b) in enumerate(zones):
            rail(f"Fixed_rib_{y}_{i+1}","X",a,b,y)
    for y in (450,554):
        rail(f"Center_rib_{y}","X",315,575,y,"Center")
    for x in (100,790):
        rail(f"Rear_outboard_{x}","Y",932,REAR_BACK,x,"Rear")
    # Front band screw seats on the perimeter and y=82 rail.
    # Side edge screws use the perimeter rail. The steel crossmember supports the rear band.

ARM_Y0, REAR_FRONT, REAR_BACK = 748, POST_Y-20, POST_Y+20
REAR_LEFT, REAR_RIGHT = 110, 780
REAR_M6_X = (160, 360, 470, 750)
REAR_M6_Z = (RAIL_Z+RAIL_TOP)/2
REAR_M6_HOLE_D = 6.6
BASE_BOLTS = [(x,y) for x in POSTS for y in (768,870,946,POST_Y)]
SEAT_FRONT, SEAT_LENGTH = REAR_FRONT-40, 32
FLANGE_FRONT, FLANGE_BACK, FLANGE_TOP = POST_Y-61, POST_Y+23, RAIL_TOP+8
FLANGE_ROWS = (REAR_FRONT-25, POST_Y+5)
FLANGE_BOLTS = [(x+dx,y) for x in POSTS for dx in (-33,33) for y in FLANGE_ROWS]
SEAT_STUBS = [bounds for x in POSTS for bounds in
              ((x-20-SEAT_LENGTH,x-20),(x+20,x+20+SEAT_LENGTH))]
BACKING_TOP = BASE_STEEL+5
M8_HEAD_R = 16.43/2
M8_SEAT_R = 16.6/2
M8_HOLE_R = 8.6/2
BASE_ACCESS_D = 20

def steel_rhs_x(x0, x1, y, holes):
    body = box(x0,x1,y-20,y+20,10,30)
    core = box(x0-1,x1+1,y-17,y+17,13,27)
    return remove(body,[core]+[cyl(x,yy,r,9,31) for x,yy,r in holes])

def steel_rhs_y(y0, y1, x, holes):
    core = box(x-17,x+17,y0-1,y1+1,13,27)
    return remove(box(x-20,x+20,y0,y1,10,30),
                  [core]+[cyl(xx,y,r,9,31) for xx,y,r in holes])

def m8_countersink(x,y,mouth_z,from_below=False):
    depth = M8_SEAT_R-M8_HOLE_R
    cone = tip(x,y,M8_HOLE_R,M8_SEAT_R,mouth_z-depth,mouth_z)
    if from_below:
        return cone.rotate((x,y,mouth_z),(x+1,y,mouth_z),180)
    return cone


def m8_flat_head(x,y,head_z,length,shank_r,from_below=False):
    shoulder = head_z-(M8_HEAD_R-4)
    head = tip(x,y,4,M8_HEAD_R,shoulder,head_z)
    bolt = cyl(x,y,shank_r,head_z-length,shoulder).fuse(head).clean()
    if from_below:
        return bolt.rotate((x,y,head_z),(x+1,y,head_z),180)
    return bolt


def rear_frame():
    item("RHS-L", "共用后横管", f"40×20×3，长度 {REAR_RIGHT-REAR_LEFT}，20 高", "外包焊接",
         "Q235B 矩形钢管 40 20 3", "", "后面贴后框，两端贴铝纵支。4 处 Ø6.6 横向通孔，两壁对钻，孔中心 z20；距横管左端 50、250、360、640。")
    item("REAR-M6", "后横管连接螺钉", "M6×45 初选，内六角圆柱头", "购买",
         "M6×45 内六角圆柱头全牙", "1", "按槽螺母与垫圈的实物深度复核长度，拧紧前检查有效咬合且端部不顶槽底。轻贴锁紧，避免把空心管壁夹凹。")
    item("REAR-W6", "后横管连接平垫圈", "Ø6.4／Ø12×1，钢", "购买",
         "M6 薄平垫圈 内径6.4 外径12 厚1 钢", "1", "各一只装在钢管前面螺钉头下；按实物通孔、头径和厚度核对。")
    item("REAR-T6", "后边框 M6 槽螺母", "槽6，实配 2020 槽口", "购买",
         "欧标 2020 槽6 M6 钢制槽螺母", "1", "四只先装入后边框朝踏板的内槽。实配槽唇和螺钉拧入深度。")
    item("RHS-A", "前伸副架纵臂", f"40×20×3，长度 {REAR_FRONT-ARM_Y0}，20 高", "外包焊接",
         "Q235B 矩形钢管 40 20 3", "", f"x240/650，y{ARM_Y0}–{REAR_FRONT}。")
    item("RHS-W", "扶手法兰前排短支座", f"40×20×3，直切长 {SEAT_LENGTH}，20 高", "直切/钻孔焊接",
         "Q235B 矩形钢管 40 20 3", "", "每脚两段，分别贴焊纵臂和后横管。"
         "两壁同轴 Ø14.2，孔中心距管前边 15、距贴纵臂的切口 13；焊入同款 M8 螺纹套。")
    item("SL-8", "落地穿栓抗压套管", "Ø12 / Ø8.5 × 20", "外包车/切管焊接",
         "钢隔套 12 8.5", "1", "实配管壁孔和穿栓，焊后铣平或磨平。")
    item("TH-8", "扶手法兰 M8 焊接螺纹套", "外径 14 × 20，M8 通牙", "标准件或圆料直切钻攻/焊接",
         "钢制焊接螺纹套 M8 长 20", "1", "实配套外径和管壁孔，焊后端面齐平。核实有效牙和防焊渣。模型为螺纹中径包络。")
    item("BP-5", "底板钢背板", "70×350×5，两端 R4，4×Ø8.6", "激光切割/钻沉孔",
         "5 mm Q235B 钢板激光切割 钻沉孔", "", "反面 90° 沉头按实物配，头齐平；木芯反面铣 5 mm 嵌槽。")
    item("SP-8", "木芯让位处厚钢垫圈", "DIN 7349 M8，Ø8.4 / Ø21 × 4", "购买",
         "DIN 7349 M8 21 4 钢厚垫圈", "2", "装在钢背板与副架抗压套之间，木芯开 Ø23 让位；"
         "实测涂装后间隙并配平，使钢件顶实。")
    item("BR-M8", "副架底部沉头穿栓", "M8×40 初选，配垫圈/防松螺母", "购买",
         "ISO 10642 M8 40 010.9 沉头螺钉", "2", "从底部穿入，上侧锁；按供应商的沉头规格校核承载和拧紧。")
    item("BR-N8", "副架防松螺母和垫圈包络", "M8，合计高 9", "购买",
         "M8 全金属锁紧螺母 平垫圈", "2", "预紧经抗压套、厚钢垫圈、钢背板闭合。")
    bh = [(x,y,6.1) for x,y in BASE_BOLTS if y==POST_Y]
    fh = [(x,y,7.1) for x,y in FLANGE_BOLTS if y>REAR_FRONT]
    cross = steel_rhs_x(REAR_LEFT,REAR_RIGHT,POST_Y,bh+fh)
    bores = [side_turn(cyl(0,0,REAR_M6_HOLE_D/2,-1,REAR_BACK-REAR_FRONT+1),
                       (x,REAR_FRONT,REAR_M6_Z),"F") for x in REAR_M6_X]
    add("Rear_Steel_Crossmember","RHS-L",remove(cross,bores),"steel","rear","Rear")
    for i,x in enumerate(REAR_M6_X,1):
        front = (x,REAR_FRONT,REAR_M6_Z)
        rear = (x,REAR_BACK,REAR_M6_Z)
        screw = cyl(0,0,3,-1,44).fuse(cyl(0,0,5,-7,-1)).clean()
        washer = remove(cyl(0,0,6,-1,0),[cyl(0,0,3.2,-1.1,.1)])
        nut = remove(rect(0,0,10,10,1.3,3.9),[cyl(0,0,3.05,1,4.1)])
        add(f"Rear_Frame_M6_Screw_{i}","REAR-M6",side_turn(screw,front,"F"),
            "zinc","fixing","Rear",(0,-145,76))
        add(f"Rear_Frame_M6_Washer_{i}","REAR-W6",side_turn(washer,front,"F"),
            "zinc","rearHardware","Rear",(0,-72,57))
        add(f"Rear_Frame_M6_TNut_{i}","REAR-T6",side_turn(nut,rear,"F"),
            "zinc","rearHardware","Rear",(0,18,75))
    for i,(x0,x1) in enumerate(SEAT_STUBS,1):
        holes = [(x,y,7.1) for x,y in FLANGE_BOLTS if x0<x<x1 and y<REAR_FRONT]
        stub = steel_rhs_x(x0,x1,SEAT_FRONT+20,holes)
        add(f"Rear_Steel_Seat_Stub_{i}","RHS-W",stub,"steel","rear","Rear")
    for i,x in enumerate(POSTS,1):
        holes = [(x,y,6.1) for px,y in BASE_BOLTS if x==px and y!=POST_Y]
        add(f"Rear_Steel_Arm_{i}","RHS-A",steel_rhs_y(ARM_Y0,REAR_FRONT,x,holes),"steel","rear","Rear")
        plate = bevel_rect(x-35,x+35,710,1060,BASE_STEEL,BACKING_TOP,4)
        for px,y in BASE_BOLTS:
            if px == x:
                plate = remove(plate,[cyl(x,y,M8_HOLE_R,BASE_STEEL-1,BACKING_TOP+1),
                                      m8_countersink(x,y,BASE_STEEL,from_below=True)])
        add(f"Backing_Plate_{i}","BP-5",plate,"steel","base","Rear",(0,0,-29))
    for i,(x,y) in enumerate(BASE_BOLTS,1):
        sleeve = remove(cyl(x,y,6,10,30),[cyl(x,y,4.25,9,31)])
        add(f"Base_Crush_Sleeve_{i}","SL-8",sleeve,"steel","rearHardware","Rear")
        spacer = remove(cyl(x,y,10.5,BACKING_TOP,RAIL_Z),[cyl(x,y,4.2,BACKING_TOP-1,RAIL_Z+1)])
        add(f"Base_Steel_Spacer_{i}","SP-8",spacer,"steel","rearHardware","Rear",(0,0,-13))
        screw = m8_flat_head(x,y,BASE_STEEL,40,4,from_below=True)
        add(f"Base_Through_Bolt_{i}","BR-M8",screw,"zinc","rearHardware","Rear",(0,0,-145))
        nut_z = 30
        nut = cq.Workplane("XY",origin=(x,y,nut_z+1.5)).polygon(6,15).extrude(7.5).val()
        nut = remove(nut.fuse(cyl(x,y,8,nut_z,nut_z+1.5)),[cyl(x,y,4.05,nut_z-1,nut_z+10)])
        add(f"Base_Nut_Washer_{i}","BR-N8",nut,"zinc","rearHardware","Rear")
    for i,(x,y) in enumerate(FLANGE_BOLTS,1):
        bung = remove(cyl(x,y,7,10,30),[cyl(x,y,3.6,9,31)])
        add(f"Handrail_Welded_Bung_{i}","TH-8",bung,"steel","rearHardware","Rear")
    item("HAND", "倒 U 扶手钢管", "Ø38×3，CLR 90，中心距 410，外宽 448", "外包弯管/焊接",
         "Q235B 圆管 Ø38×3 数控弯管 CLR90", "", "中心线展开约 2147，按弯管机补偿和试折确立下料。")
    item("FLG", "扶手脚法兰", "100×84×8，R5，孔距 66×50，4×Ø8.6", "激光切割/钻沉孔/焊接",
         "8 mm Q235B 钢板 激光切割 法兰", "", "90° 沉头按实物配，头齐平；法兰横跨短支座与横管。"
         "立柱中心距法兰前边 61，焊后两脚共面。")
    item("RA-M8", "扶手可拆内六角沉头螺钉", "M8×20，90°，每脚 4 颗", "购买",
         "ISO 10642 M8 20 010.9 沉头螺钉", "2", "按供应商的沉头规格校核承载和拧紧。"
         "模型名义深入螺纹套 12 mm，试装确认有效咬合及防松。")
    points = [
        (240,POST_Y,FLANGE_TOP),(240,POST_Y,855),
        (330,POST_Y,945),(560,POST_Y,945),
        (650,POST_Y,855),(650,POST_Y,FLANGE_TOP),
    ]
    a,b,c,d,e,f = map(cq.Vector,points)
    delta = 90/sqrt(2)
    path = cq.Wire.assembleEdges([
        cq.Edge.makeLine(a,b),
        cq.Edge.makeThreePointArc(b,cq.Vector(330-delta,POST_Y,855+delta),c),
        cq.Edge.makeLine(c,d),
        cq.Edge.makeThreePointArc(d,cq.Vector(560+delta,POST_Y,855+delta),e),
        cq.Edge.makeLine(e,f),
    ])
    tube = cq.Workplane("XY",origin=points[0]).circle(19).circle(16).sweep(path).val()
    add("Handrail_Bent_Tube","HAND",tube,"steel","handrail","Rear")
    for i,x in enumerate(POSTS,1):
        flange = bevel_rect(x-50,x+50,FLANGE_FRONT,FLANGE_BACK,RAIL_TOP,FLANGE_TOP,5)
        holes = [cyl(x,POST_Y,9.1,RAIL_TOP-1,FLANGE_TOP+1)]
        for px,y in FLANGE_BOLTS:
            if abs(px-x)<40:
                holes.extend([cyl(px,y,M8_HOLE_R,RAIL_TOP-1,FLANGE_TOP+1),
                              m8_countersink(px,y,FLANGE_TOP)])
        flange = remove(flange,holes)
        add(f"Handrail_Flange_{i}","FLG",flange,"steel","flange","Rear")
    for i,(x,y) in enumerate(FLANGE_BOLTS,1):
        bolt = m8_flat_head(x,y,FLANGE_TOP,20,3.55)
        add(f"Handrail_Flange_Screw_{i}","RA-M8",bolt,"zinc",
            "fixing","Rear",(0,138,400))


# Field geometry in edge coordinates. Same cuts define the mating pockets and moving plate.
SENSOR_V = 13
FSR_TAIL_ANGLE = -45
STOP_US = (-90,90)
GUIDE_US = (-65,65)
OUTER_GUIDE_SIDES = {"F":"N","L":"W","R":"E","B":"S"}
RETURN_U = -34
RETAINER_SEAT_TOP = 42.5
RETAINER_SHIM = 1
RETAINER_THICKNESS = 1
RETAINER_BOTTOM = RETAINER_SEAT_TOP+RETAINER_SHIM
RETAINER_TOP = RETAINER_BOTTOM+RETAINER_THICKNESS
OUTER_FOOT_TOP = 31.5
FSR_TOP = 31.275
BUTTON_TOP = 32.775
CLIP_SIZE, CLIP_CLEARANCE = 26, 0.65
CLIP_BLOCK_SIZE = 12
OUTER_TRIANGLE_LEG = 18
M5_HEAD = 9.8
DECK_SCREWS = {
    "FL": [(x,y) for x in (100,242) for y in (157,287)],
    "FR": [(x,y) for x in (648,790) for y in (157,287)],
    "BL": [(x,y) for x in (102,281) for y in (717,847)],
    "BR": [(x,y) for x in (609,788) for y in (717,847)],
    "C": [(x,y) for x in (365,525) for y in (450,554)],
    "Edge_L": [(12,y) for y in (60,184,313,453,579,711,840,982,1059)],
    "Edge_R": [(878,y) for y in (60,184,410,453,579,711,840,982,1059)],
    "Edge_F": [(x,y) for x in (70,241,445,649,820) for y in (12,45)],
    "Edge_B1": [(x,982) for x in (100,305,585,790)],
    "Edge_B2": [(x,1068) for x in (82,260,445,630,806)],
}
USB_Y = 322
WOOD_RELIEFS, STEEL_RELIEFS = [], []
BRACKETED = Counter()

def nut_top(x,y):
    return remove(rect(x,y,10,10,25.7,28.65),[cyl(x,y,2.53,25.5,28.8)])

def nut_bottom(x,y):
    return nut_top(x,y).rotate((x,y,20),(x+1,y,20),180)

def side_turn(shape,start,axis):
    x,y,z=start
    if axis=="L":
        return translate(shape.rotate((0,0,0),(0,1,0),90),x,y,z)
    if axis=="R":
        return translate(shape.rotate((0,0,0),(0,1,0),-90),x,y,z)
    if axis=="F":
        return translate(shape.rotate((0,0,0),(1,0,0),-90),x,y,z)
    return translate(shape.rotate((0,0,0),(1,0,0),90),x,y,z)

def rail_hardware_items():
    item("T-M5", "2020 槽螺母 M5", "包络 10×10×2.95，滚入/从端部滑入", "购买",
         "欧标 2020 槽6 M5 薄 T 型螺母", "12", "先用手头实物确认槽唇承压、不能旋脱及装配路径。")
    item("M5-D", "踏面和边带沉头螺钉", "M5×18 起选，90° 头", "购买",
         "304 M5 18 十字/内六角沉头", "5", "实配槽腔末端。选低头内六角，板件孔按实物刀型。")
    item("M5-B", "底板超薄头螺钉", "M5×14，头高约 1.3、头径约 9.5", "购买",
         "M5×14 超薄头 大扁头 内六角螺钉", "5", "格内型材每根 1 颗、长型材 3–4 颗，两端有角件的短料不用。头压在底钢板上并藏进 2 mm 橡胶厚度内，装前在型材试螺纹和孔深。")
    item("M5-S", "侧板沉头螺钉", "M5×6 或实配短牙，90° 头", "购买",
         "M5×6 平头沉头螺钉 短螺丝", "4", "2 mm 壁需验证锥孔，必要时改低矮圆头并记录壳外尺寸。")
    item("M3-F", "托片与挡块齐平螺钉", "M3 沉头 90°，长 5/6 按叠厚选", "购买",
         "M3 5 6 微型沉头螺钉 2020 槽6 螺母", "8", "不能顶面突出。FSR 托片须用低头成品或合适沉头成形。")
    item("T-M3", "2020 槽螺母 M3", "包络 10×9×2.9", "购买",
         "国标/欧标 2020 槽6 M3 薄滑块螺母", "8", "按实际槽型选。")
    item("ANGLE-S", "2020 紧凑角件", "双翼 12×15，名义壁厚 3", "购买/小批机加工",
         "2020 12mm 小内角件 M4 窄翼", "2", "用于前围 13 mm 净空等窄位，先实配工具与螺帽。")
    item("ANGLE", "2020 内藏角件", "双翼 17×15，名义壁厚 3", "购买/实配",
         "欧标2020 17mm 小内角件 槽6 M4", "5", "用于外框、格线主骨架和钢副架周围，格内型材由底板螺钉压住。位置为几何包络；按实物确认扳手和螺钉。")
    consumable("ANGLE-FIX",0,"2020 小角件锁紧硬件","每件 2 个配套连接位","随角件购买",
               "2020 角件配套 T 螺母 螺栓","10","采购量按对应角件的两倍，线下实配。")

def add_deck_hardware(group, points, moving_group=""):
    for i,(x,y) in enumerate(points,1):
        add(f"{group}_Top_Screw_{i}","M5-D",screw_model(x,y,5,26.0,41.6,44,M5_HEAD),
            "zinc","fixing",moving_group or group)
        add(f"{group}_Top_TNut_{i}","T-M5",nut_top(x,y),"zinc","join",moving_group or group)

def deck_holes(points):
    wood, steel = [], []
    for x,y in points:
        wood.extend(drill_cs(x,y,5.5,10.0,29.8,41.65,44.05))
        steel.extend(drill_cs(x,y,5.5,10.0,29.8,41.65,44.05))
    return wood,steel

def filt_cuts(body,cuts):
    bb = body.BoundingBox()
    result = []
    for c in cuts:
        bc = c.BoundingBox()
        if (min(bb.xmax,bc.xmax)>max(bb.xmin,bc.xmin)+0.001
                and min(bb.ymax,bc.ymax)>max(bb.ymin,bc.ymin)+0.001
                and min(bb.zmax,bc.zmax)>max(bb.zmin,bc.zmin)+0.001):
            result.append(c)
    return result

def pocketed(body,cuts):
    return remove(body,filt_cuts(body,cuts))

def base_fix_points():
    # The bracketed lattice keeps its own shape, so the base is a replaceable cover.
    # Rails inside a cell butt against the lattice and get one screw at mid-length to
    # hold them down; the long rails get three or four to carry the base. Short rails
    # bracketed at both ends need none. Holes are 6 mm clearance, drilled by hand.
    # Stations stay clear of the inlaid steel plates.
    plates = [(x-35,x+35,710,1060) for x in POSTS]
    points = []
    for name,axis,start,end,cross,_,_ in RAILS:
        length = end-start
        if length <= 300 and BRACKETED[name] >= 2:
            continue
        if length <= 300:
            stations = [(start+end)/2]
        else:
            n = round(length/300)
            stations = [start+40+i*(length-80)/(n-1) for i in range(n)]
        for s in stations:
            # A stub beside a backing plate takes its screw at the far end instead.
            for station in (s,start+10,end-10):
                point = (round(station),cross) if axis=="X" else (cross,round(station))
                if not any(a-6<point[0]<b+6 and c-6<point[1]<e+6 for a,b,c,e in plates):
                    break
            else:
                raise ValueError(f"no base screw station for {name}")
            points.append(point)
    return points

def base():
    item("BASE-P", "底板木芯", "886×1076×9", "裁切/自制",
         "9mm 九厘海洋胶合板 外用桦木船板", "", "叠在底钢板上面，照钢板的孔钻 Ø6 过孔。与钢板只用螺钉连接，不整面胶合。背板位反面铣深 5，八个厚垫圈位置开 Ø23 让位孔；两面和四边封漆防潮。")
    item("BASE-S", "底钢板", "886×1076×1，全部孔位激光切出", "外包激光切割喷塑",
         "1mm 镀锌钢板 激光切割 喷塑", "", "朝地面一侧，挡潮气并承接螺钉头。孔位由激光切割保证，兼作木芯钻孔模板。副架 M8 穿栓处开 Ø20 检修孔。")
    item("BASE-R", "满铺密实防滑底橡胶", "886×1076×2", "自制裁切",
         "2mm 密实防滑橡胶片 耐磨 平整", "", "地面 z−2，贴在底钢板下面。螺钉头和穿栓处冲孔让位。实际摩擦和地面平整度需测试。")
    bottom = [bevel_rect(x-35.12,x+35.12,709.88,1060.12,-1,BACKING_TOP,4.12) for x in POSTS]
    bottom.extend(cyl(x,y,11.5,-1,11) for x,y in BASE_BOLTS)
    fix = base_fix_points()
    CHECKS["base_screw_count"] = len(fix)
    bottom.extend(cyl(x,y,3,-1,10.1) for x,y in fix)
    # Screw heads bear on the steel sheet and hide inside the rubber thickness.
    sheet = [cyl(x,y,2.75,-1,2) for x,y in fix]+[cyl(x,y,BASE_ACCESS_D/2,-1,2) for x,y in BASE_BOLTS]
    pad = [cyl(x,y,6.5,-3,1) for x,y in fix]+[cyl(x,y,11,-3,1) for x,y in BASE_BOLTS]
    add("Base_Plywood","BASE-P",remove(box(2,888,2,1078,BASE_STEEL,10),bottom),"ply","base","Base")
    add("Base_Steel_Sheet","BASE-S",remove(box(2,888,2,1078,0,BASE_STEEL),sheet),"galv","basesteel","Base")
    add("Base_Rubber","BASE-R",remove(box(2,888,2,1078,-2,0),pad),"rubber","floor","Base")
    for i,(x,y) in enumerate(fix,1):
        screw = cyl(x,y,4.75,-1.3,0).fuse(cyl(x,y,2.5,0,14)).clean()
        add(f"Base_Screw_{i}","M5-B",screw,"zinc","base","Base",(0,0,-90))
        add(f"Base_TNut_{i}","T-M5",nut_bottom(x,y),"zinc","join","Base")

def soft_head_shape(u,v):
    return tip(u,v,4.75,4.1,FSR_TOP,BUTTON_TOP)

def module_hardware(module, side, label, u, v, top, position_up):
    bottom = 25.85
    local_screw = screw_model(u,v,3,bottom,top-0.8,top,4.6)
    add(f"{module}_{side}_{label}_Screw","M3-F",local(local_screw,module,side),"zinc",
        "carrier" if label=="FSR" else "stop",module,(0,0,position_up))
    nut = remove(rect(u,v,9,10,25.8,28.6),[cyl(u,v,1.55,25,29)])
    add(f"{module}_{side}_{label}_TNut","T-M3",local(nut,module,side),"zinc","join",module)

def module_fastener_axis(module, side):
    return 7 if (module,side) in (("L","W"),("R","E")) else 0

def make_arrow_items():
    item("AR-PC","透光箭头踏板",f"274×274×10，四角 {PC_CORNER_CUT}×{PC_CORNER_CUT} / 45°","板材直切/去毛刺",
         "实心透光聚碳酸酯 10mm 阻燃/耐磨规格试样","1","四边加四切角，整板等厚。按二维轮廓报价，PC 无孔、无浅槽。")
    item("AR-GFX","箭头灯箱贴图","矢量箭头示意，选透射背贴","印刷外包",
         "透光灯箱膜 丝印 PC 背贴 跳舞机箭头","1 套","图形在预览里示意；印刷需避开挡块和压头接触区，不能垫高。")
    item("FS-TR","FSR 金属平托片","30×33×0.8，桥跨槽口","激光切割/整平",
         "304 0.8mm 薄板 激光切割 沉孔","3","齐平螺钉偏开传感圆；木板下铣让位。")
    item("FS-AD","FSR 粘贴定位膜","0.10，外径18 背胶","自制裁切",
         "0.1mm 薄双面胶 PET 离型带","8","只粘背面。避免夹紧敏感区及封死通气路径。")
    item("FS-R","FSR402 标准长尾圆片","Ø18 / 有效区约 Ø14.7，厚 0.375，圆心到尾端约 47","购买",
         "FSR402 长尾 18mm 圆形 薄膜 压力传感器","4–8","圆心居各边中轴，尾片名义斜向 45° 平躺越过并轨型材顶面，焊脚落在梁间腔。尾长按下单件校核。")
    item("FS-A","软硅胶压头","Ø9.5→8.2，高1.5","成品/裁切",
         "软硅胶圆点 Ø9 1.5mm 无背胶 30A 40A","8","与有效区同心，压头硬度以触发回差和力校。安装方式与有效高度实测。")
    item("RET","独立回位件","16×14×3，自粘微孔弹性体","自制裁切",
         "3mm PORON 微孔聚氨酯 慢回弹样品/EPDM 泡棉","8","选低压缩永久变形且回弹足够的样材。试验所需回位力，预压在实配中设定。")
    item("HS-CROSS", "十字撑二级限挠钢垫", "30×18×1.9，有 5.9 宽导向舌", "外包铣削 / 实配",
         "304 精铣 钢垫片 槽6 导向", "4", "留 1.1 mm 空载间隙；名义全行程 0.5 后再留 0.6 mm 板挠，做样级标定。")
    item("HS-23","钢硬挡块","40×26×2.30，4 角 R1","外包切割研磨",
         "304 精密薄板 2.3mm 磨平 齐平 M3","4","8/箭头；整块落在格线型材和并轨型材顶面。上边打圆；螺钉只定位，压力靠平接触。")
    item("HS-SH","硬挡块独立钢垫片","40×26×0.20（名义），独立可调","购买片材/切割",
         "不锈钢调整垫片 0.05 0.1 0.2 mm","1 套","模型每挡 1 片，备多档。不能用松动叠片横跨铝槽承受冲击。")
    item("LAT","侧向定位垫","16×5.2×8 黑色 POM，PC 面距格线 2.2","自制/加工",
         "POM 耐磨条 低摩擦 定位垫","8","按可换口袋实配，名义每侧 0.8 间隙。接触面倒边，先测试热胀。")
    item("LAT-E","外围低位定位垫","16×5.2×7.6，黑色 POM","自制/加工",
         "POM 定位垫 低摩擦","4","上边 z41.8，低于边带钢面下表面，钢边条无需为定位垫开口。")
    item("ANTI","菱形防掀压片",f"{CLIP_SIZE}×{CLIP_SIZE}×1，304，统一转 45°","方片下料/打孔",
         "304 1mm 不锈钢方片 M4 沉孔","3","仅用于四个交错内角，边缘去毛刺。相邻两片 PC 共用。")
    item("ANTI-E","外角三角压片",f"等腰直角三角形，两腿 {OUTER_TRIANGLE_LEG}×1，304，M3沉孔","激光直切/打孔",
         "304 1mm 三角片 M3 沉孔","2","斜边沿 PC 切角，压片与螺钉顶面齐平，外露边手工倒钝。")
    item("ANTI-EF","外角隐藏平底座","24×14×1.5，304，2 个 M3 沉孔","矩形下料/打孔",
         "304 不锈钢片 1.5mm 加工 M3沉头","2","左/右镜像孔位见装配；固定在 2020 顶槽，完全在运动面下。")
    item("ANTI-EP","外角压片支柱","Ø6×11，M3 双通","购买/实配",
         "M3 双通圆形隔离柱 外径6","3","高度 11，实际长度需用实物校验，允许短支柱加金属薄垫补齐。")
    item("ANTI-EB","外角支柱底部沉头螺钉","M3×6，低头","购买",
         "M3×6 低头 沉头螺丝","4","由底座下面装入支柱，螺钉头齐底。")
    item("ANTI-ET","外角三角压片沉头螺钉","M3×8，低头","购买",
         "M3×8 低头 沉头螺丝","4","经 1 mm 垫片锁到双通支柱，样件核实上下螺钉不顶死。")
    item("ANTI-W3","外角压片平垫片","Ø6×1，Ø3.2 通孔","购买",
         "M3 精密平垫片 3.2×6×1","4","紧贴支柱顶面，提高压片 1 mm，不压在 PC 上。")
    item("ANTI-W4","内交点压片平垫片","Ø10×1，Ø4.3 通孔","购买",
         "M4 精密平垫片 4.3×10×1","4","紧贴铝撑顶面，提高压片 1 mm。")
    item("ANTI-S","交点方形顶撑",f"{CLIP_BLOCK_SIZE}×{CLIP_BLOCK_SIZE}×12.5，6061，M4通孔","方料直切/钻孔",
         "6061 方铝条 12mm 直切","3","方块坐在 2020 槽口两侧；螺钉套合后压住，顶面齐平。")
    item("ANTI-I","压片 M4 槽螺母","9.6×9.6×2.95，M4 槽6","购买",
         "欧标2020 槽6 M4 薄型 T 螺母","4","装配前按实际槽型和端部距离试装。")
    item("ANTI-B","压片沉头螺钉","M4×20，头与压片齐平","购买",
         "M4×20 低头 沉头螺丝","4","垫片与压片合装后校核槽螺母咬合和螺端净空。")


def cross_backstops(module,x,y):
    # Secondary protection engages only after additional PC flex beyond flat hard-stop travel.
    for i,(dx,dy) in enumerate([(0,0),(-72,0),(72,0),(0,-72),(0,72)],1):
        a,b=x+dx,y+dy
        face=bevel_rect(a-9,a+9,b-15,b+15,30,31.9,.8)
        tongue=rect(a,b,5.9,26,28.9,30)
        pad=face.fuse(tongue).clean()
        pad=remove(pad,drill_cs(a,b,3.2,4.8,28.7,31.03,31.95))
        screw=screw_model(a,b,3,25.85,31.1,31.9,4.6)
        nut=remove(rect(a,b,9,9,25.8,28.6),[cyl(a,b,1.55,25,29)])
        if dx:
            pad=pad.rotate((a,b,0),(a,b,1),90)
        tag=f"{module}_Cross_Backstop_{i}"
        add(tag,"HS-CROSS",pad,"304","stop",module,(0,0,113))
        add(tag+"_Screw","M3-F",screw,"zinc","stop",module,(0,0,154))
        add(tag+"_TNut","T-M3",nut,"zinc","join",module)


def pc_outline(x,y):
    half = PC_SIZE/2
    leg = half-PC_CORNER_CUT
    return [(x+dx,y+dy) for dx,dy in [
        (-leg,-half),(leg,-half),(half,-leg),(half,leg),
        (leg,half),(-leg,half),(-half,leg),(-half,-leg)
    ]]


def retainer_nodes():
    nodes = {}
    for module,(x,y) in ARROWS.items():
        half = PITCH//2
        for dx,dy in [(-half,-half),(half,-half),(half,half),(-half,half)]:
            nodes.setdefault((x+dx,y+dy),[]).append(module)
    return nodes


def square_retainer(x,y):
    # Shared caps sit over the intersection of two arrow corners.
    fasten_x = x
    tag = f"Corner_{x}_{y}"

    def square(z0,z1,clearance=0):
        width = CLIP_SIZE+2*clearance
        return rect(x,y,width,width,z0,z1).rotate((x,y,0),(x,y,1),45)

    shoulder = RETAINER_TOP-1.5
    holes = drill_cs(fasten_x,y,4.25,7.4,29.95,shoulder-.02,RETAINER_TOP+.08)
    blank = cq.Workplane("XY").newObject([square(RETAINER_BOTTOM,RETAINER_TOP)])
    cap = remove(blank.faces(">Z").edges().chamfer(.22).val(),holes)
    support = remove(rect(x,y,CLIP_BLOCK_SIZE,CLIP_BLOCK_SIZE,RAIL_TOP,RETAINER_SEAT_TOP),holes)
    shim = remove(cyl(x,y,5,RETAINER_SEAT_TOP,RETAINER_BOTTOM),holes)
    screw = screw_model(fasten_x,y,4,RETAINER_TOP-20,shoulder,RETAINER_TOP,7.05)
    nut = remove(rect(fasten_x,y,9.6,9.6,25.7,28.65),
                 [cyl(fasten_x,y,2.05,25.5,28.8)])
    add(tag+"_Cover","ANTI",cap,"304","clip","Retainers")
    add(tag+"_Support","ANTI-S",support,"al6061","clipshim","Retainers")
    add(tag+"_Shim","ANTI-W4",shim,"304","clipshim","Retainers",(0,0,307))
    add(tag+"_Screw","ANTI-B",screw,"zinc","fixing","Retainers")
    add(tag+"_Nut","ANTI-I",nut,"zinc","join","Retainers")
    block_opening = CLIP_BLOCK_SIZE+0.5
    WOOD_RELIEFS.append(rect(x,y,block_opening,block_opening,29.95,42.05))
    STEEL_RELIEFS.append(square(41.99,44.1,CLIP_CLEARANCE))


def outer_retainer(x,y,module):
    # The triangle fits on the moving-panel side of both grid lines. Its
    # hidden base follows the T-slot perpendicular to the perimeter strip.
    ax,ay = ARROWS[module]
    sx,sy = (1 if ax>x else -1),(1 if ay>y else -1)
    long_side = x in (GRID_X,GRID_X+3*PITCH)

    def world(u,v):
        return (x+sx*u,y+sy*v) if long_side else (x+sx*v,y+sy*u)

    def prism(u0,u1,v0,v1,z0,z1):
        a,b = world(u0,v0),world(u1,v1)
        return box(min(a[0],b[0]),max(a[0],b[0]),min(a[1],b[1]),max(a[1],b[1]),z0,z1)

    inset = 0.7
    end = inset+OUTER_TRIANGLE_LEG
    outline = [world(inset,inset),world(end,inset),world(inset,end)]
    px,py = world(3.85,3.85)
    tx,ty = world(17,0)
    shoulder = RETAINER_TOP-.8
    blank = cq.Workplane("XY").newObject([poly(outline,RETAINER_BOTTOM,RETAINER_TOP)])
    cover = blank.edges("|Z").fillet(.65).faces(">Z").edges().chamfer(.22).val()
    cover = remove(cover,drill_cs(px,py,3.2,4.8,RETAINER_BOTTOM-.1,shoulder-.04,RETAINER_TOP+.04))
    post = remove(cyl(px,py,3,OUTER_FOOT_TOP,RETAINER_SEAT_TOP),
                  [cyl(px,py,1.56,OUTER_FOOT_TOP-.1,RETAINER_SEAT_TOP+.1)])
    shim = remove(cyl(px,py,3,RETAINER_SEAT_TOP,RETAINER_BOTTOM),
                  [cyl(px,py,1.6,RETAINER_SEAT_TOP-.1,RETAINER_BOTTOM+.1)])
    foot_holes = drill_cs(tx,ty,3.2,4.8,29.95,OUTER_FOOT_TOP-.84,OUTER_FOOT_TOP+.05)
    foot_holes.extend([cyl(px,py,1.62,29.95,OUTER_FOOT_TOP+.05),tip(px,py,2.4,1.6,29.96,30.85)])
    foot = remove(prism(.7,24.7,-6,8,30,OUTER_FOOT_TOP),foot_holes)
    top_screw = screw_model(px,py,3,RETAINER_TOP-8,shoulder,RETAINER_TOP,4.6)
    bottom_screw = tip(px,py,2.3,1.5,30,30.8).fuse(cyl(px,py,1.5,30.8,36)).clean()
    mount_screw = screw_model(tx,ty,3,OUTER_FOOT_TOP-6,OUTER_FOOT_TOP-.8,OUTER_FOOT_TOP,4.6)
    nut = remove(rect(tx,ty,9,9,25.8,28.6),[cyl(tx,ty,1.55,25,29)])

    tag = f"Corner_{x}_{y}"
    add(tag+"_Cover","ANTI-E",cover,"304","clip","Retainers")
    add(tag+"_Foot","ANTI-EF",foot,"304","clipshim","Retainers",(0,0,284))
    add(tag+"_Post","ANTI-EP",post,"zinc","clipshim","Retainers",(0,0,305))
    add(tag+"_Shim","ANTI-W3",shim,"304","clipshim","Retainers",(0,0,315))
    add(tag+"_Screw","ANTI-ET",top_screw,"zinc","fixing","Retainers")
    add(tag+"_Post_Screw","ANTI-EB",bottom_screw,"zinc","clipshim","Retainers",(0,0,264))
    add(tag+"_Mount_Screw","M3-F",mount_screw,"zinc","clipshim","Retainers",(0,0,298))
    add(tag+"_Mount_Nut","T-M3",nut,"zinc","join","Retainers")
    # Where required this relief touches only the underside of the fixed cell.
    WOOD_RELIEFS.append(prism(.45,24.95,-6.25,8.25,29.95,OUTER_FOOT_TOP+.15))


def arrow_modules():
    make_arrow_items()
    for (x,y),modules in retainer_nodes().items():
        if len(modules)==2:
            square_retainer(x,y)
        else:
            outer_retainer(x,y,modules[0])
    for module,(x,y) in ARROWS.items():
        cross_backstops(module,x,y)
        for side in SIDES:
            slot_v = module_fastener_axis(module,side)
            transform = lambda shape: local(shape,module,side)
            fsr_screw = (-10,slot_v)
            fsr_cut = drill_cs(*fsr_screw,3.2,5.0,29.8,30.0,30.85)
            plate = bevel_rect(-15,15,-8,25,30,30.8,1)
            plate = remove(plate,fsr_cut)
            add(f"{module}_{side}_FSR_Carrier","FS-TR",transform(plate),"304","carrier",module)
            module_hardware(module,side,"FSR",*fsr_screw,30.8,158)
            glue = cyl(0,SENSOR_V,9,30.8,30.9)
            disc = cyl(0,SENSOR_V,9,30.9,FSR_TOP)
            # The head stays on the edge centerline while its tail runs toward the open bay.
            tail = rect(0,SENSOR_V+26,7.5,42,30.9,FSR_TOP)
            tail = tail.rotate((0,SENSOR_V,0),(0,SENSOR_V,1),FSR_TAIL_ANGLE)
            add(f"{module}_{side}_FSR_Adhesive","FS-AD",transform(glue),"rubber","fsr",module,(0,0,115))
            add(f"{module}_{side}_FSR","FS-R",transform(disc.fuse(tail).clean()),"fsr","fsr",module)
            add(f"{module}_{side}_Silicone","FS-A",transform(soft_head_shape(0,SENSOR_V)),
                "silicone","return",module,(0,0,155))
            add(f"{module}_{side}_Return","RET",transform(rect(RETURN_U,8,16,14,30,33)),"spring",
                "return",module)
            WOOD_RELIEFS.append(transform(rect(0,8.5,32,35,29.99,31.12)))
            for i,u in enumerate(STOP_US,1):
                # Two eccentric screws keep usable bearing area under the PC and span the slot.
                fasteners = [(u-12,slot_v),(u+12,slot_v)]
                stop = bevel_rect(u-20,u+20,-8,18,30.2,STOP_TOP,1)
                shim = bevel_rect(u-20,u+20,-8,18,30,30.2,1)
                for j,(a,b) in enumerate(fasteners,1):
                    stop = remove(stop,drill_cs(a,b,3.2,4.8,29.99,31.7,32.6))
                    shim = remove(shim,[cyl(a,b,1.65,29.9,30.3)])
                    module_hardware(module,side,f"Stop_{i}_{j}",a,b,STOP_TOP,174)
                add(f"{module}_{side}_Stop_Shim_{i}","HS-SH",transform(shim),"304","stopshim",module)
                add(f"{module}_{side}_Hard_Stop_{i}","HS-23",transform(stop),"304","stop",module)
                WOOD_RELIEFS.append(transform(rect(u,4,40.4,26.5,29.99,32.8)))
            outer = side==OUTER_GUIDE_SIDES[module]
            guide_top = 41.8 if outer else 42.2
            for i,u in enumerate(GUIDE_US,1):
                guide = bevel_rect(u-8,u+8,-3,2.2,34.2,guide_top,0.35)
                add(f"{module}_{side}_Wear_Guide_{i}","LAT-E" if outer else "LAT",transform(guide),
                    "pOM","guide",module)
                WOOD_RELIEFS.append(transform(rect(u,-0.4,16.35,5.65,34,42.1)))
                if not outer:
                    STEEL_RELIEFS.append(transform(rect(u,-0.4,16.35,5.65,41.99,42.35)))
        pc = poly(pc_outline(x,y),PC_Z,PC_TOP)
        add(f"{module}_Polycarbonate","AR-PC",pc,"pc" if module in ("F","B") else "pc2","pc",module)
    UNMODELED["AR-GFX"] = 4

def top_deck():
    item("FX-W","固定格海洋板","276×276×12，R1.5","CNC/自制",
         "海洋板12mm 276×276 桦木","", "共 5，其中正中整格可拆。局部取孔和让位见模型。")
    item("FX-S","固定格喷塑钢面","278×278×2，R1.5","外包激光切割喷塑",
         "304 2mm 细纹防滑喷塑 CNC 沉孔","","内交错角开菱形缺口，单边名义间隙 0.65 mm；外部三角压片位于 PC 角内。露边倒钝。")
    item("BD-W-S","左右上边带木芯","22×1076×12","CNC/自制",
         "12mm 海洋板 细板条","","螺固到外框；侧面 USB 铣暗槽。")
    item("BD-S-S","左右上边带钢面","22×1076×2","外包切割喷塑",
         "304 2mm 细纹防滑 条板","","外露长边倒钝、与侧包边接缝穿鞋检查。")
    item("BD-W-F","前上边带木芯","841×78.5×12","CNC/自制",
         "12mm 海洋板 封边","","前导轨和 y56 补横梁作支承；两侧留 0.5 缝。")
    item("BD-S-F","前上边带钢面","841×78.5×2","外包切割喷塑",
         "304 2mm 细纹防滑 条板")
    item("BD-W-R1","后上边带前半木芯","841×115×12","CNC/自制",
         "12mm 海洋板 扶手孔 仿形铣槽")
    item("BD-W-R2","后上边带后半木芯","841×39.25×12","CNC/自制",
         "12mm 海洋板 扶手孔 仿形铣槽")
    item("BD-S-R1","后上边带前半钢面","841×115×2","外包切割喷塑",
         "304 2mm 细纹防滑 扶手孔")
    item("BD-S-R2","后上边带后半钢面","841×39.25×2","外包切割喷塑",
         "304 2mm 细纹防滑 扶手孔")
    item("EYE", "底板穿栓检修塞（选配）", "适配 Ø20 薄板孔，低头", "购买/实配",
         "20mm 黑色橡胶封孔塞 齐平 薄板","4","塞顶需藏在橡胶厚度内，按实物选配。")
    UNMODELED["EYE"] = 8
    # At each M8 anchor the board relief keeps the preload path through metal.
    for x,y in BASE_BOLTS:
        WOOD_RELIEFS.append(cyl(x,y,9,29.9,41.8))
    # Representative covered wire crossover at an unloaded rail/wood interface, four mouths.
    for x,y in ((413,362),(477,642),(305,534),(585,470)):
        cross = rect(x,y,9 if x not in (305,585) else 30,
                     30 if x not in (305,585) else 9,29.95,32.2)
        WOOD_RELIEFS.append(cross)
    for k,(x,y) in FIXED.items():
        wh,sh = deck_holes(DECK_SCREWS[k])
        wood = bevel_rect(x-138,x+138,y-138,y+138,30,42,1.5)
        if k=="FR":
            wh.append(box(839,864,USB_Y-19,USB_Y+19,29.9,41.0))
        steel = bevel_rect(x-139,x+139,y-139,y+139,42,44,1.5)
        add(f"{k}_Plywood","FX-W",pocketed(wood,WOOD_RELIEFS+wh),"ply","wood",k)
        add(f"{k}_Stainless_Surface","FX-S",pocketed(steel,STEEL_RELIEFS+sh),"coat","top",k)
        add_deck_hardware(k,DECK_SCREWS[k])
    rear_wood, rear_steel = [], []
    for x in POSTS:
        rear_wood.extend([bevel_rect(x-51,x+51,FLANGE_FRONT-1,FLANGE_BACK+1,29.9,FLANGE_TOP+.4,5.5),
                          cyl(x,POST_Y,25,29.9,44.2)])
        rear_steel.append(cyl(x,POST_Y,22,41.9,44.2))
    profiles = {
        "Edge_L":((2,24,2,1078),"BD-W-S","BD-S-S"),
        "Edge_R":((866,888,2,1078),"BD-W-S","BD-S-S"),
        "Edge_F":((24.5,865.5,2.5,81),"BD-W-F","BD-S-F"),
        "Edge_B1":((24.5,865.5,922.75,POST_Y-.25),"BD-W-R1","BD-S-R1"),
        "Edge_B2":((24.5,865.5,POST_Y+.25,1077.5),"BD-W-R2","BD-S-R2"),
    }
    for group,(bounds,wsku,ssku) in profiles.items():
        wh,sh = deck_holes(DECK_SCREWS[group])
        if group=="Edge_R":
            wh.append(box(842,888.1,USB_Y-19,USB_Y+19,29.9,41.0))
        if group.startswith("Edge_B"):
            wh += rear_wood
            sh += rear_steel
        wood = bevel_rect(*bounds,30,42,0.8)
        steel = bevel_rect(*bounds,42,44,0.8)
        add(f"{group}_Plywood",wsku,pocketed(wood,WOOD_RELIEFS+wh),"ply","wood",group)
        feature_cuts = filt_cuts(steel,STEEL_RELIEFS)
        CHECKS.setdefault("perimeter_steel_relief_count",{})[group] = len(feature_cuts)
        assert not feature_cuts, f"Retainer or guide relief in edge band {group}"
        add(f"{group}_Top",ssku,pocketed(steel,sh),"coat","top",group)
        add_deck_hardware(group,DECK_SCREWS[group])




def case():
    item("CASE-S","左右可拆侧围","1080×44×2，304","钣金下料/去锐角",
         "304 2mm 激光切割 拉丝不锈钢 边条","","右侧 USB 开孔与埋入式法兰待按实物。")
    item("CASE-E","前后可拆侧围","885.4×44×2，304","钣金下料/去锐角",
         "304 2mm 激光切割 拉丝不锈钢 边条","","按 886 名义内距减两端 0.3 缝。")
    item("USB-P","侧面 USB 短延长组件","侧壳内藏，长 0.5–0.8 m，外嵌法兰 35×11 待定","购买/实配",
         "USB-C 面板座 公对母 短延长 数据 面板嵌入螺栓","","以实物定壳孔、插头拔出距离。")
    rails_fastened = {
        "L":[(0,y,20) for y in (49,155,276,394,509,637,752,880,995,1054)],
        "R":[(890,y,20) for y in (49,155,276,394,509,637,752,880,995,1054)],
        "F":[(x,0,20) for x in (64,174,278,382,507,612,735,827)],
        "B":[(x,1080,20) for x in (64,174,278,382,507,612,735,827)],
    }
    bodies = {
        "L": ((0,2,0,D),(-245,0,24)),
        "R": ((W-2,W,0,D),(245,0,24)),
        "F": ((2.3,W-2.3,0,2),(0,-238,21)),
        "B": ((2.3,W-2.3,D-2,D),(0,245,35)),
    }
    for side,points in rails_fastened.items():
        bounds,shift = bodies[side]
        skin = bevel_rect(*bounds,0,44,0.1)
        cuts = []
        if side=="R":
            cuts += [box(887.9,890.1,USB_Y-10.1,USB_Y+10.1,32.2,40.6),
                     box(889.48,890.1,USB_Y-17.6,USB_Y+17.6,30.9,42.1)]
            for dy in (-14,14):
                cuts.append(side_turn(cyl(0,0,1.55,-0.1,3),(890,USB_Y+dy,36.5),side))
        for i,point in enumerate(points,1):
            cuts.extend(side_turn(h,point,side) for h in (
                cyl(0,0,2.85,0.8,2.1), tip(0,0,4.9,2.7,0,1.88)))
            screw = tip(0,0,4.7,2.45,0,1.8).fuse(cyl(0,0,2.45,1.8,5.9))
            add(f"Case_{side}_Screw_{i}","M5-S",side_turn(screw,point,side),"zinc","fixing",
                f"Case_{side}",tuple(d*1.2 for d in shift))
            nut = remove(rect(0,0,9.6,9.6,3.3,5.35),[cyl(0,0,2.56,3.1,5.5)])
            add(f"Case_{side}_TNut_{i}","T-M5",side_turn(nut,point,side),"zinc","join",f"Case_{side}")
        add(f"Case_{side}_Skin","CASE-S" if side in ("L","R") else "CASE-E",
            remove(skin,cuts),"304","skin",f"Case_{side}",shift)
    flange = box(889.5,890,USB_Y-17.5,USB_Y+17.5,31,42)
    socket = box(855,889.5,USB_Y-9.9,USB_Y+9.9,32.35,40.45)
    plug_hole = box(884.5,891,USB_Y-4.6,USB_Y+4.6,35,38)
    usb = remove(flange.fuse(socket),[plug_hole])
    add("USB_C_Panel_Socket","USB-P",usb,"pcb","skin","Case_R",(275,0,73))
    consumable("USB-M3",2,"USB 面板安装小螺钉","M3+螺母，依购入座","购买","USB C 面板座 配套螺丝","2")

def box_overlap(bounds, other):
    return all(min(bounds[i+1],other[i+1])-max(bounds[i],other[i])>0.004 for i in (0,2))

def frame_joiners():
    occupied = [r[5] for r in RAILS]
    rear_members = [(REAR_LEFT,REAR_RIGHT,REAR_FRONT,REAR_BACK)]
    rear_members += [(x-20,x+20,ARM_Y0,REAR_FRONT) for x in POSTS]
    rear_members += [(x0,x1,SEAT_FRONT,REAR_FRONT) for x0,x1 in SEAT_STUBS]
    taken, joints, blocked = [], [], []
    # The y=82 rail takes the only free side beside the front arrow before y=45 does.
    for name,axis,start,end,cross,_,group in sorted(RAILS,key=lambda r:r[0].startswith("Grid_45")):
        for point,sign in ((start,1),(end,-1)):
            p = (point-sign*0.03,cross) if axis=="X" else (cross,point-sign*0.03)
            mates = [r for r in occupied+rear_members if r[0]<p[0]<r[1] and r[2]<p[1]<r[3]]
            if not mates:
                continue
            against_steel = any(m in rear_members for m in mates)
            # The nine-cell lattice is bracketed into one self-supporting frame. Rails
            # inside a cell are held by the base screws instead.
            if not (name.startswith(("Outer_","Grid_")) or group=="Rear" or against_steel):
                continue
            bracket_sizes = ((12,1),(12,-1)) if "Stop_Outer_Rail" in name else ((17,1),(17,-1),(12,1),(12,-1))
            if name == "Grid_long_L":
                # Mirror the right spine: its brackets sit outboard, clear of the front arrow bay.
                bracket_sizes = ((17,-1),(17,1),(12,-1),(12,1))
            for width,other_side in bracket_sizes:
                def at(u,v):
                    return (point+sign*v,cross+other_side*u) if axis=="X" else (cross+other_side*u,point+sign*v)
                outline = [at(u,v) for u,v in ((10,0),(10+width,0),(10+width,3),(13,3),(13,width),(10,width))]
                xs,ys = zip(*outline)
                envelope = (min(xs),max(xs),min(ys),max(ys))
                if not (2 <= envelope[0] and envelope[1] <= 888 and 2 <= envelope[2] and envelope[3] <= 1078):
                    continue
                if any(box_overlap(envelope,r) for r in occupied+rear_members+taken):
                    continue
                cutters = []
                for (u,v),(du,dv) in (((10+(width+1)//2,0),(0,1)),((10,(width+1)//2),(1,0))):
                    x,y = at(u,v)
                    px,py = at(u+du,v+dv)
                    direction = cq.Vector(px-x,py-y,0)
                    cutters.append(cq.Solid.makeCylinder(2.2,5,cq.Vector(x,y,20)-direction,direction))
                bracket = remove(poly(outline,12.5,27.5),cutters)
                add(f"{name}_Bracket_{point}","ANGLE" if width==17 else "ANGLE-S",bracket,"al","join",group)
                taken.append(envelope)
                joints.append((name,point,"钢侧螺纹连接待实配" if against_steel else "双槽螺母"))
                BRACKETED[name] += 1
                break
            else:
                blocked.append((name,point))
    UNMODELED["ANGLE-FIX"] = len(joints)*2
    CHECKS["bracket_joints"] = joints
    CHECKS["bracket_unplaced"] = blocked

def led_cradle():
    outer = bevel_rect(-8,8,-47,47,0,5,1.4)
    return remove(outer,[box(-5.2,5.2,-47.1,47.1,1.7,5.1)])

def electronics():
    item("LIGHT-TR","LED 灯带托槽","16×94×5，10.4 线槽开口","打印 PETG",
         "PETG 1.75mm，见 print/LED-tray.stl","2","平底朝下，四道壁，0.2层高，无支撑。用薄型双面胶。")
    item("LIGHT-DF","LED 乳白扩散条","16×92×1","裁切",
         "1mm PC 乳白扩散片 LED","4","两端胶点或薄胶固定。扩散件上表面 z16。")
    item("LIGHT-LED","WS2812B 5V 灯条","60灯/m，5灯/段，约83.3×10","购买裁切",
         "WS2812B 5V 60灯每米 10mm 裸板 IP30","至少 4 段","16段共80像素，依实际分段点落刀。")
    item("PCB-TR","中格电子托板","166×78×1.5，4个 M3 孔，PC/PETG 可选","外包切/自制",
         "阻燃绝缘 PC板 1.5mm 电子安装底板","","绝缘托板随中格提起，留余线/可拔插。")
    item("TR-SP","电子托板隔柱","M3×10，外径5.5","购买",
         "M3 10 尼龙双通隔离柱","4","实物定螺钉和隔柱尺寸。")
    item("RP-ZERO","RP2040-Zero 模块","18×23.5，USB-C 方向朝右包络","购买",
         "Waveshare RP2040-Zero USB-C","1","仅包络，GP26–29 依次对应 F/L/R/B。")
    item("MUX","TMUX1204 通道小板包络","26×22×5 初设，实际载板待定","购买/自制电路",
         "TI TMUX1204 4:1 analog multiplexer 转接 载板","1","4 个 IC，每 IC 采一键的 4 FSR。")
    cradle = led_cradle()
    for module,(x,y) in ARROWS.items():
        for i,(dx,dy) in enumerate([(a,b) for a in (-68,68) for b in (-61,61)],1):
            ox,oy=x+dx,y+dy
            add(f"{module}_LED_Tray_{i}","LIGHT-TR",translate(cradle,ox,oy,10),"petg","led",module)
            add(f"{module}_LED_Strip_{i}","LIGHT-LED",rect(ox,oy,10,83.33,11.7,13.2),"led","led",module,(0,0,73))
            add(f"{module}_LED_Diffuser_{i}","LIGHT-DF",rect(ox,oy,16,92,15,16),"diff","diff",module)
    tx,ty=445,502
    screws=[(tx+dx,ty+dy) for dx in (-77,77) for dy in (-33,33)]
    tray=bevel_rect(tx-83,tx+83,ty-39,ty+39,18.5,20,2)
    tray=remove(tray,[cyl(x,y,1.65,18.4,20.1) for x,y in screws])
    add("Center_Electronics_Tray","PCB-TR",tray,"petg","electronics","Center")
    for i,(x,y) in enumerate(screws,1):
        post=remove(cyl(x,y,2.75,20,30),[cyl(x,y,1.45,19.9,30.1)])
        add(f"Center_Tray_Standoff_{i}","TR-SP",post,"zinc","electronics","Center")
    add("Center_RP2040_Zero","RP-ZERO",rect(480,502,23.5,18,12.7,18.5),
        "pcb","electronics","Center",(0,0,76))
    for i,(x,y) in enumerate([(392,483),(392,521),(431,483),(431,521)],1):
        add(f"Center_TMUX1204_{i}","MUX",rect(x,y,26,22,13.5,18.5),
            "pcb","electronics","Center",(0,0,76))
    consumable("PCB-FIX",8,"中格托板上下固定螺钉","M3短螺钉×4，木用固定×4","购买",
               "M3 尼龙隔柱固定 短 M3 螺丝 木螺丝","4")
    consumable("WIRE-F",16,"FSR 尾部软连接/引线","柔性尾片连接 2线；防呆标线","购买",
               "FSR 402 长尾2P 配套插座 28AWG","4")
    consumable("WIRE-L",1,"灯光电源/数据分支线束","24AWG 信号/分支，电源线按电流定","购买自制",
               "5V WS2812B 线束 硅胶线 防拔","")
    consumable("WIRE-CL",1,"线束护线与应力释放","一套小 P 夹、薄胶带、开边护套","购买",
               "尼龙 P夹 小线夹 聚酰亚胺胶带","1 套")
    consumable("ADH-L",1,"灯槽与扩散片固定","薄型背胶，预留返修","购买","薄双面胶 LED 灯槽")
    consumable("ADH-D",1,"喷塑钢面与木板粘接","薄或局部沉铣，计入 14 mm 叠厚","购买",
               "木板 不锈钢 结构胶 薄胶层")
    consumable("PWR",1,"LED 5V 电源与保护","限流设计后按最大电流选独立供电","购买",
               "5V LED 电源 保险丝 带过流保护","")

def build():
    rail_hardware_items()
    frame()
    rear_frame()
    frame_joiners()
    arrow_modules()
    base()
    top_deck()
    case()
    electronics()

def assemble(title, parts, exploded=False):
    asm=cq.Assembly(name=title)
    groups={}
    for p in parts:
        key = p.group or p.layer
        if key not in groups:
            groups[key]=cq.Assembly(name="Group_"+key)
        c=tuple(int(MATERIALS[p.material][1][i:i+2],16)/255 for i in (1,3,5))
        loc=cq.Location(cq.Vector(*(p.offset if exploded else (0,0,0))))
        groups[key].add(p.shape,name=p.name,color=cq.Color(*c),loc=loc)
    for group in groups.values():
        asm.add(group)
    return asm

if __name__=="__main__":
    import sys
    sys.modules["design"] = sys.modules[__name__]
    from deliver import run
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("check","export","all"), default="all")
    args=parser.parse_args()
    build()
    run(args.mode)
