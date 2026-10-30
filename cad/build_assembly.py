#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
棱镜小电视（方案二）—— 零件 / 装配体结构版

设计思路（重要）：
  不再"用脚本熔出一个整体"，而是建成**标准机械结构**，方便后续在 FreeCAD GUI 里改：
    PrismTV_总装 (App::Part)
      ├── ASM_外壳       →  P01_外壳底座      （草图 → 拉伸 → 挖腔 → 开槽 → 倒圆）
      ├── ASM_光学头     →  P02_棱镜托台 / P03_屏幕板 / P04_显示面板
      │                     P05_遮光框 / P06_光学胶 / P07_分光棱镜 / P08_分光膜
      └── ASM_主板       →  P09_主板 + 各元件

  每个零件都是**独立对象**，尺寸尽量绑到 "参数" 电子表格（别名），
  改表格 → 模型跟着变；也可以在属性栏 / 草图里单独改某个特征。

  光学头整体后仰 TILT 度：挂在 ASM_光学头 的 Placement 上，改这一个就能换角度。

运行：
    freecadcmd cad/build_assembly.py          # 只建模型 + 导出
    DISPLAY=:1 freecad cad/build_assembly.py  # 顺便渲染
"""

import os
import sys
import math
import csv

import FreeCAD as App
import Part
import Mesh
import Sketcher
from FreeCAD import Vector, Rotation, Placement

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
STL = os.path.join(OUT, "stl")
os.makedirs(STL, exist_ok=True)

LOG = open(os.path.join(OUT, "build_assembly.log"), "w")


def log(*a):
    m = " ".join(str(x) for x in a)
    LOG.write(m + "\n"); LOG.flush()
    print(m)


# ================================================================
# 1. 参数
# ================================================================
P = [
    # (别名, 值, 说明)
    ("TILT",      30.0,  "光学头后仰角 = 人眼仰角 (°)"),
    ("BW",        33.0,  "外壳宽 X"),
    ("BD",        40.0,  "外壳深 Y"),
    ("WALL",       2.0,  "壁厚"),
    ("FLOOR",      2.0,  "底板厚"),
    ("BASE_H",    18.7546, "外壳前部高度"),
    ("LEDGE_Z",    6.0,  "后平台高度"),
    ("KNEE_Y",     2.09, "斜面与平台交点 Y"),
    ("CORNER_R",   5.0,  "外壳四角倒圆"),
    ("SLOT_W",    22.0,  "正面盲槽宽"),
    ("SLOT_H",     6.0,  "正面盲槽高"),
    ("SLOT_D",     6.0,  "正面盲槽深"),
    ("SLOT_Z",     7.0,  "正面盲槽中心 Z"),
    ("USBC_W",     9.5,  "USB-C 开口宽"),
    ("USBC_Z",     4.4,  "USB-C 开口中心 Z"),
    ("PRISM",     25.4,  "分光棱镜边长"),
    ("YH",        14.0,  "光学头半深"),
    ("PCB_T",      0.8,  "屏幕板厚"),
    ("PANEL_T",    1.0,  "显示面板厚"),
    ("SHIELD_T",   0.5,  "遮光框厚"),
    ("GLUE_T",     0.1,  "光学胶层厚"),
    ("PLINTH_H",   3.4,  "托台顶面到棱镜底面"),
    ("MAIN_W",    28.0,  "主板宽"),
    ("MAIN_D",    28.0,  "主板深"),
    ("MAIN_T",     1.0,  "主板厚"),
    ("MAIN_Z",     2.0,  "主板底面 Z"),
    ("MAIN_Y0",  -11.0,  "主板前端 Y"),
]
PV = {k: v for k, v, _ in P}

TILT = math.radians(PV["TILT"])
S, C = math.sin(TILT), math.cos(TILT)
YH = PV["YH"]

# 光学头局部原点（底面中心）的世界坐标
HEAD_Z0 = 3.6 + YH * S
HEAD_Y0 = -18.0 + YH * C
HL_PRISM_Z = PV["PCB_T"] + PV["PANEL_T"] + PV["SHIELD_T"] + PV["GLUE_T"]
HEAD_T = HL_PRISM_Z + PV["PRISM"]
TOTAL_H = HEAD_Z0 + YH * S + HEAD_T * C

log("=" * 64)
log("PrismTV 装配结构版   TILT=%.0f°  整机高≈%.2f mm" % (PV["TILT"], TOTAL_H))
log("=" * 64)

doc = App.newDocument("PrismTV_Assembly")


# ================================================================
# 2. 参数表（带别名，可被表达式引用）
# ================================================================
ss = doc.addObject("Spreadsheet::Sheet", "参数")
ss.set("A1", "参数"); ss.set("B1", "数值"); ss.set("C1", "说明")
for i, (k, v, note) in enumerate(P, start=2):
    ss.set("A%d" % i, k)
    ss.set("B%d" % i, str(v))
    ss.set("C%d" % i, note)
    try:
        ss.setAlias("B%d" % i, k)
    except Exception:
        try:
            ss.setAlias(k, "B%d" % i)
        except Exception as e:
            log("! alias", k, e)
ss.set("E1", "表达式说明")
ss.set("E2", "改 B 列数值，模型自动更新（已绑定的尺寸）")


def box(name, L, W, H, x, y, z, mat="", label=None):
    """独立可编辑的方块零件"""
    o = doc.addObject("Part::Box", name)
    o.Length, o.Width, o.Height = L, W, H
    o.Placement = Placement(Vector(x, y, z), Rotation())
    if label:
        o.Label = label
    return o


def cut(name, base, tool, label=None):
    o = doc.addObject("Part::Cut", name)
    o.Base = base
    o.Tool = tool
    if label:
        o.Label = label
    return o


# ================================================================
# 3. P01 外壳底座  ——  草图 → 拉伸 → 挖腔 → 开槽 → 倒圆
# ================================================================
# 3.1 侧剖面草图（落在 YZ 平面：草图局部 X→世界 Y，Y→世界 Z）
sk = doc.addObject("Sketcher::SketchObject", "SK_外壳轮廓")
sk.Label = "SK 外壳侧剖面"
sk.Placement = Placement(Vector(0, 0, 0), Rotation(Vector(1, 1, 1), 120))
prof = [(-20.0, 0.0), (20.0, 0.0), (20.0, 6.0), (2.09, 6.0), (-20.0, 18.7546), (-20.0, 0.0)]
for i in range(len(prof) - 1):
    sk.addGeometry(Part.LineSegment(Vector(prof[i][0], prof[i][1], 0),
                                    Vector(prof[i + 1][0], prof[i + 1][1], 0)), False)
doc.recompute()

# 3.2 拉伸
ex = doc.addObject("Part::Extrusion", "EX_外壳毛坯")
ex.Label = "EX 外壳毛坯"
ex.Base = sk
ex.Dir = Vector(1, 0, 0)
ex.LengthFwd = PV["BW"]
ex.Solid = True
ex.Placement.Base.x = -PV["BW"] / 2.0
doc.recompute()

# 3.3 内腔
b_cav = box("BOX_内腔", PV["BW"] - 2 * PV["WALL"],
            (PV["BD"] / 2 - (-13.0)) - PV["WALL"], 60,
            -(PV["BW"] / 2 - PV["WALL"]), -13.0, PV["FLOOR"])
try:
    b_cav.setExpression("Length", "参数.BW - 2 * 参数.WALL")
except Exception:
    pass
op = cut("CUT_内腔", ex, b_cav, "CUT 内腔")

# 3.4 正面圆角盲槽（用旋转过的圆角方块近似：先方块，后单独做圆角零件也可）
b_slot = box("BOX_前槽", PV["SLOT_W"], PV["SLOT_D"], PV["SLOT_H"],
             -PV["SLOT_W"] / 2, -PV["BD"] / 2 - 0.5, PV["SLOT_Z"])
op2 = cut("CUT_前槽", op, b_slot, "CUT 前槽")

# 3.5 USB-C 开口
b_usb = box("BOX_USBC", PV["USBC_W"], PV["WALL"] + 4, 3.4,
            -PV["USBC_W"] / 2, PV["BD"] / 2 - PV["WALL"] - 2, PV["USBC_Z"] - 1.7)
op3 = cut("CUT_USBC", op2, b_usb, "CUT USB-C")

# 3.6 侧壁透光孔
cy = doc.addObject("Part::Cylinder", "CYL_透光孔")
cy.Radius, cy.Height = 1.5, PV["WALL"] + 4
cy.Placement = Placement(Vector(PV["BW"] / 2 - PV["WALL"] - 2, -6.0, 4.2),
                         Rotation(Vector(0, 1, 0), 90))
op4 = cut("CUT_透光孔", op3, cy, "CUT 透光孔")

# 3.7 四角倒圆（Part::Fillet，保持可编辑）
p01 = op4
doc.recompute()
log("[P01] op4 体积 %.0f  bbox %s" % (op4.Shape.Volume, op4.Shape.BoundBox))
try:
    sh = op4.Shape
    vz = []
    for i, e in enumerate(sh.Edges):
        if len(e.Vertexes) != 2:
            continue
        p0, p1 = e.Vertexes[0].Point, e.Vertexes[1].Point
        if (abs(abs(p0.x) - PV["BW"] / 2) < 1e-6 and abs(abs(p0.y) - PV["BD"] / 2) < 1e-6
                and abs(p0.z - p1.z) > 1.0):
            vz.append(i + 1)
    log("[P01] 候选角边 %d 条" % len(vz))
    if len(vz) == 4:
        fl = doc.addObject("Part::Fillet", "P01_外壳底座")
        fl.Label = "P01 外壳底座"
        fl.Base = op4
        fl.Edges = [(i, PV["CORNER_R"], PV["CORNER_R"]) for i in vz]
        doc.recompute()
        if fl.Shape.isValid():
            p01 = fl
            log("[P01] 倒圆 OK")
except Exception as e:
    log("! P01 倒圆失败:", e)
    p01 = op4
p01.Label = "P01 外壳底座"

# ================================================================
# 4. 光学头零件（局部坐标，由 ASM_光学头 的 Placement 统一后仰）
# ================================================================
# P02 棱镜托台（阶梯：下口 28.2 让开屏幕板 / 上口 25.6 贴紧棱镜）
p02_outer = box("BOX_托台", 32.0, 32.0, PV["PLINTH_H"] + 0.5, -16.0, -16.0, -0.5)
p02_in1 = box("BOX_托台下口", 2 * YH + 0.2, 2 * YH + 0.2, 3.0,
              -(2 * YH + 0.2) / 2, -(2 * YH + 0.2) / 2, -1.5)
p02_c1 = cut("CUT_托台下口", p02_outer, p02_in1)
p02_in2 = box("BOX_托台上口", PV["PRISM"] + 0.2, PV["PRISM"] + 0.2, PV["PLINTH_H"] + 1.0,
              -(PV["PRISM"] + 0.2) / 2, -(PV["PRISM"] + 0.2) / 2, PV["PCB_T"])
p02_c2 = cut("CUT_托台上口", p02_c1, p02_in2)
p02_bk = box("BOX_托台开口", 34.0, 18.0, PV["PLINTH_H"] + 3.0, -17.0, 2.5, -1.5)
p02 = cut("P02_棱镜托台", p02_c2, p02_bk, "P02 棱镜托台")

# P03 屏幕板
p03 = box("P03_屏幕板", 2 * YH, 2 * YH, PV["PCB_T"], -YH, -YH, 0.0, label="P03 屏幕板")
try:
    p03.setExpression("Length", "参数.YH * 2")
    p03.setExpression("Width", "参数.YH * 2")
    p03.setExpression("Height", "参数.PCB_T")
except Exception:
    pass

# P04 显示面板
p04 = box("P04_显示面板", 24.8, 24.8, PV["PANEL_T"], -12.4, -12.4, PV["PCB_T"], label="P04 显示面板")

# P05 遮光框
p05_o = box("BOX_遮光框", PV["PRISM"], PV["PRISM"], PV["SHIELD_T"],
            -PV["PRISM"] / 2, -PV["PRISM"] / 2, PV["PCB_T"] + PV["PANEL_T"])
p05_i = box("BOX_遮光窗", 23.4, 23.4, PV["SHIELD_T"] + 2, -11.7, -11.7,
            PV["PCB_T"] + PV["PANEL_T"] - 1)
p05 = cut("P05_遮光框", p05_o, p05_i, "P05 遮光框")

# P06 光学胶（环形）
p06_o = box("BOX_光学胶", PV["PRISM"], PV["PRISM"], PV["GLUE_T"],
            -PV["PRISM"] / 2, -PV["PRISM"] / 2, HL_PRISM_Z - PV["GLUE_T"])
p06_i = box("BOX_胶内孔", PV["PRISM"] - 1.2, PV["PRISM"] - 1.2, PV["GLUE_T"] + 2,
            -(PV["PRISM"] - 1.2) / 2, -(PV["PRISM"] - 1.2) / 2, HL_PRISM_Z - PV["GLUE_T"] - 1)
p06 = cut("P06_光学胶", p06_o, p06_i, "P06 光学胶")

# P07 分光棱镜
p07 = box("P07_分光棱镜", PV["PRISM"], PV["PRISM"], PV["PRISM"],
          -PV["PRISM"] / 2, -PV["PRISM"] / 2, HL_PRISM_Z, label="P07 分光棱镜")
try:
    p07.setExpression("Length", "参数.PRISM")
    p07.setExpression("Width", "参数.PRISM")
    p07.setExpression("Height", "参数.PRISM")
except Exception:
    pass

# P08 分光膜（45°，局部 y+z=中心）
p08 = box("P08_分光膜", PV["PRISM"], PV["PRISM"] * math.sqrt(2), 0.15,
          -PV["PRISM"] / 2, -PV["PRISM"] * math.sqrt(2) / 2, -0.075, label="P08 分光膜")
p08.Placement = Placement(
    Vector(0, 0, HL_PRISM_Z + PV["PRISM"] / 2),
    Rotation(Vector(1, 0, 0), -45))

# ================================================================
# 5. 主板与元件（世界坐标，水平）
# ================================================================
MW, MD, MT, MY0, MZ = PV["MAIN_W"], PV["MAIN_D"], PV["MAIN_T"], PV["MAIN_Y0"], PV["MAIN_Z"]
p09 = box("P09_主板", MW, MD, MT, -MW / 2, MY0, MZ, label="P09 主板")
try:
    p09.setExpression("Length", "参数.MAIN_W")
    p09.setExpression("Width", "参数.MAIN_D")
    p09.setExpression("Height", "参数.MAIN_T")
except Exception:
    pass
ZT = MZ + MT

comp = []
comp.append(box("C01_ESP32模块", 7.0, 7.0, 1.0, -8.0, MY0 + 5.0, ZT, label="C01 ESP32-PICO-D4"))
comp.append(box("C02_USBC座", 9.0, 7.5, 3.2, -4.5, MY0 + MD - 7.5, ZT - 0.6, label="C02 USB-C 16P"))
comp.append(box("C03_连接器12P", 6.0, 2.5, 2.0, -3.0, MY0 + 14.0, ZT, label="C03 12P 连接器"))
comp.append(box("C04_轻触键1", 3.0, 2.5, 1.5, -13.0, MY0 + 1.0, ZT, label="C04 轻触键"))
comp.append(box("C05_轻触键2", 3.0, 2.5, 1.5, 10.0, MY0 + 1.0, ZT, label="C05 轻触键"))
comp.append(box("C06_MPU6050", 4.0, 4.0, 0.9, -5.0, -4.0, ZT, label="C06 MPU6050"))
comp.append(box("C07_BH1750", 2.6, 2.4, 0.9, 11.5, -7.2, ZT, label="C07 BH1750"))
comp.append(box("C08_电源模块", 6.0, 5.0, 1.5, 3.0, -1.0, ZT, label="C08 Buck"))
comp.append(box("C09_PCB天线", 4.0, 8.0, 0.12, 3.0, MY0 + 1.0, ZT, label="C09 PCB 天线"))
comp.append(box("C10_触摸铜箔", 0.12, 9.0, 3.0, -PV["BW"] / 2 + PV["WALL"] - 0.12,
                1.0, 2.6, label="C10 触摸铜箔"))
for i, x in enumerate((-9.0, 9.0)):
    comp.append(box("C1%d_后支撑" % (i + 1), 5.0, 5.0, 0.6, x - 2.5, 2.9, ZT,
                    label="C1%d 后支撑柱" % (i + 1)))

# ================================================================
# 6. 装配结构
# ================================================================
asm = doc.addObject("App::Part", "PrismTV_总装")
asm.Label = "PrismTV 总装"

a_shell = doc.addObject("App::Part", "ASM_外壳")
a_shell.Label = "ASM-01 外壳组件"
a_head = doc.addObject("App::Part", "ASM_光学头")
a_head.Label = "ASM-02 光学头组件"
a_main = doc.addObject("App::Part", "ASM_主板")
a_main.Label = "ASM-03 主板组件"

for a in (a_shell, a_head, a_main):
    asm.addObject(a)

a_shell.addObject(p01)
for o in (p02, p03, p04, p05, p06, p07, p08):
    a_head.addObject(o)
a_main.addObject(p09)
for o in comp:
    a_main.addObject(o)

# 光学头整体后仰 + 平移（改这一个就能换角度）
a_head.Placement = Placement(
    Vector(0, HEAD_Y0, HEAD_Z0),
    Rotation(Vector(1, 0, 0), -PV["TILT"]))
try:
    a_head.setExpression("Placement.Base.y", "参数.YH")
except Exception:
    pass

doc.recompute()
log("[asm] 树：")
for o in doc.Objects:
    if o.TypeId in ("App::Part",):
        log("  %-18s %s" % (o.Name, [c.Name for c in o.Group]))

# ================================================================
# 7. 明细表
# ================================================================
bom = doc.addObject("Spreadsheet::Sheet", "BOM")
bom.set("A1", "序号"); bom.set("B1", "名称"); bom.set("C1", "数量"); bom.set("D1", "材料")
rows = [
    ("P01", "外壳底座", 1, "PETG 暖米白（3D 打印）"),
    ("P02", "棱镜托台", 1, "PETG 暖米白"),
    ("P03", "屏幕板", 1, "FR4 黑色阻焊"),
    ("P04", "显示面板", 1, "1.3\" IPS 240×240"),
    ("P05", "遮光框", 1, "黑色硅胶泡棉"),
    ("P06", "光学胶", 1, "UV 胶 0.1mm"),
    ("P07", "分光棱镜", 1, "BK7 25.4³ 50:50"),
    ("P08", "分光膜", 1, "介质膜（镀在棱镜内）"),
    ("P09", "主板", 1, "FR4 28×28"),
    ("C01-C11", "电子元件", 11, "—"),
]
for i, r in enumerate(rows, start=2):
    for j, v in enumerate(r):
        bom.set("%s%d" % ("ABCD"[j], i), str(v))

# ================================================================
# 8. 导出
# ================================================================
FC = os.path.join(OUT, "PrismTV_Assembly.FCStd")
doc.saveAs(FC)
log("[save]", FC)

tops = [p01, p02, p03, p04, p05, p06, p07, p08, p09] + comp
try:
    Part.export(tops, os.path.join(OUT, "PrismTV_Assembly.step"))
    log("[save] STEP ok")
except Exception as e:
    log("! STEP:", e)

for o in tops:
    try:
        Mesh.export([o], os.path.join(STL, o.Label.replace(" ", "_") + ".stl"))
    except Exception as e:
        log("! STL %s: %s" % (o.Name, e))
log("[save] STL ok")

# ================================================================
# 9. 可选渲染
# ================================================================
if "--no-render" in sys.argv:
    LOG.close()
    sys.stdout.flush()
    os._exit(0)

try:
    import FreeCADGui
    from pivy import coin
except ImportError:
    log("[render] 无 GUI，跳过")
    LOG.close()
    sys.stdout.flush()
    os._exit(0)

RENDER = os.path.join(OUT, "render")
os.makedirs(RENDER, exist_ok=True)
vw = FreeCADGui.ActiveDocument.ActiveView
cam = vw.getCameraNode()
try:
    prm = App.ParamGet("User parameter:BaseApp/Preferences/View")
    prm.SetBool("Gradient", False); prm.SetBool("ShowAxisCross", False)
except Exception:
    pass

import time


def look_at(pos, target, up=(0, 0, 1)):
    px, py, pz = pos; tx, ty, tz = target
    zx, zy, zz = px - tx, py - ty, pz - tz
    n = math.sqrt(zx * zx + zy * zy + zz * zz); zx, zy, zz = zx / n, zy / n, zz / n
    ux, uy, uz = up
    xx, xy, xz = uy * zz - uz * zy, uz * zx - ux * zz, ux * zy - uy * zx
    n = math.sqrt(xx * xx + xy * xy + xz * xz)
    xx, xy, xz = (1, 0, 0) if n < 1e-9 else (xx / n, xy / n, xz / n)
    yx, yy, yz = zy * xz - zz * xy, zz * xx - zx * xz, zx * xy - zy * xx
    m = coin.SbMatrix(xx, xy, xz, 0, yx, yy, yz, 0, zx, zy, zz, 0, 0, 0, 0, 1)
    r = coin.SbRotation(); r.setValue(m)
    cam.position.setValue(px, py, pz); cam.orientation.setValue(r)


CZ = TOTAL_H / 2
EYE = Vector(0, -C, S); EYE.normalize()


def shot(name, pos, target=(0, 0, CZ), w=1000, h=900):
    look_at(pos, target)
    FreeCADGui.updateGui(); time.sleep(0.15)
    vw.fitAll(); FreeCADGui.updateGui(); time.sleep(0.25)
    vw.saveImage(os.path.join(RENDER, name), w, h, "White")
    log("[render]", name)


shot("A01_等距.png", (95, -110, 105))
shot("A02_用户视角.png", (EYE.x * 300, EYE.y * 300, CZ + EYE.z * 300), w=1000, h=1000)
shot("A03_侧视.png", (300, 0, CZ))
scan = []
for o in doc.Objects:
    if o.TypeId == "Part::Box" and o.Name.startswith("BOX_"):
        scan.append(o)
for o in scan:
    o.ViewObject.Visibility = False
shot("A04_隐藏工艺块.png", (100, -115, 105))
for o in scan:
    o.ViewObject.Visibility = True

log("[done]")
LOG.close()
sys.stdout.flush()
os._exit(0)
