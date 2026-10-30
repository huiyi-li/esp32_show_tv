#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
棱镜小电视（方案二）—— 初版原型结构 FreeCAD 参数化模型

运行（需要显示，用于 OpenGL 离屏渲染）：
    DISPLAY=:1 freecad cad/build_prototype.py
或只建模型/导文件、不渲染：
    freecadcmd cad/build_prototype.py --no-render

产出：
    cad/out/PrismTV_Prototype_v1.FCStd
    cad/out/PrismTV_Prototype_v1.step
    cad/out/stl/*.stl
    cad/out/render/*.png
    cad/out/BOM.csv
    cad/out/PARAMS.csv
"""

import os
import sys
import csv
import time
import math

import FreeCAD
import Part
import Mesh
from FreeCAD import Vector

# ---------------------------------------------------------------- 路径
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
RENDER = os.path.join(OUT, "render")
STLDIR = os.path.join(OUT, "stl")
for d in (OUT, RENDER, STLDIR):
    os.makedirs(d, exist_ok=True)

LOG = open(os.path.join(OUT, "build.log"), "w")


def log(*a):
    msg = " ".join(str(x) for x in a)
    LOG.write(msg + "\n")
    LOG.flush()
    try:
        print(msg)
    except Exception:
        pass


# ================================================================
# 1. 参数表（全部尺寸，mm）—— 改这里即可重新生成
# ================================================================
P = {
    # ---- 外壳 ----
    "ENV_W": 36.0,          # 外壳外廓宽 (X)
    "ENV_D": 36.0,          # 外壳外廓深 (Y)
    "ENV_H": 9.0,           # 外壳底座高
    "WALL": 2.0,            # 壁厚
    "FLOOR": 2.0,           # 底板厚
    # ---- 主板 ----
    "PCB_MAIN_W": 30.0,
    "PCB_MAIN_D": 32.0,
    "PCB_T": 1.0,
    "PCB_Z": 2.0,           # 主板底面 Z
    # ---- 屏幕板 ----
    "PCB_DISP": 30.0,       # 屏幕板方形边长
    "PCB_DISP_T": 0.8,
    "PCB_DISP_Z": 6.0,
    # ---- 面板 ----
    "LCD_W": 24.8,
    "LCD_T": 1.0,
    "LCD_ACTIVE": 23.4,     # 有效显示区（1.3" 240x240）
    "LCD_Z": 6.8,
    # ---- 遮光框 ----
    "SHIELD_T": 0.8,
    "SHIELD_Z": 7.8,
    # ---- 支撑柱 ----
    "POST_D": 4.0,
    "POST_H": 3.0,
    "POST_XY": 13.5,        # 四角支撑柱中心坐标 ±
    # ---- 棱镜卡座 ----
    "HOLDER_H": 2.0,
    "HOLDER_Z": 9.0,
    "HOLDER_LIP_H": 0.4,    # 阶梯孔：下半段小孔厚度
    "PRISM": 25.0,          # 棱镜边长
    "HOLDER_GAP": 0.05,     # 卡座内口单边余量
    "LIP_GAP": 0.575,       # 阶梯孔下半段单边扩大（= 托边宽度）
    # ---- 棱镜护角 ----
    "CORNER_W": 3.0,
    "CORNER_XY": 14.0,
    # ---- 顶部压框 ----
    "TOPFRAME_T": 2.0,
}

P["PRISM_Z"] = P["HOLDER_Z"] + P["HOLDER_LIP_H"]                 # 9.4
P["PRISM_TOP"] = P["PRISM_Z"] + P["PRISM"]                       # 34.4
P["HOLDER_TOP"] = P["HOLDER_Z"] + P["HOLDER_H"]                  # 11.0
P["CORNER_H"] = P["PRISM_TOP"] - P["HOLDER_TOP"]                 # 23.4
P["TOPFRAME_Z"] = P["PRISM_TOP"]                                 # 34.4
P["ENV_TOP"] = P["TOPFRAME_Z"] + P["TOPFRAME_T"]                 # 36.4

# 棱镜卡座内口：25.05；托边内口：25.05 - 2*0.575 = 23.9
HOLDER_ID = P["PRISM"] + 2 * P["HOLDER_GAP"]                     # 25.05
LIP_ID = P["PRISM"] - 2 * P["LIP_GAP"]                           # 23.85


# ================================================================
# 2. 材料定义
# ================================================================
#   rgb           : 视口颜色
#   a             : 不透明度(1=不透明)
#   transparency  : FreeCAD 视口透明度 0..100
MAT = {
    "PETG_Matt_Black": dict(rgb=(0.075, 0.075, 0.085), transparency=0,
                            note="外壳/卡座/压框，哑光黑 3D 打印"),
    "FR4_Dark": dict(rgb=(0.030, 0.050, 0.040), transparency=0,
                     note="PCB，黑色阻焊 FR4"),
    "Alu_Shield": dict(rgb=(0.760, 0.770, 0.790), transparency=0,
                       note="ESP32 模块屏蔽罩 / USB-C 外壳，镀镍黄铜"),
    "Copper": dict(rgb=(0.720, 0.450, 0.200), transparency=0,
                   note="M2 铜柱 / 触摸铜箔"),
    "Steel": dict(rgb=(0.700, 0.705, 0.720), transparency=0,
                  note="M2 螺钉"),
    "BK7_Glass": dict(rgb=(0.860, 0.930, 0.975), transparency=72,
                      note="分光棱镜本体，BK7 光学玻璃"),
    "Coating_Half": dict(rgb=(0.300, 0.720, 1.000), transparency=45,
                         note="50/50 分光介质膜"),
    "LCD_Glass": dict(rgb=(0.050, 0.060, 0.080), transparency=12,
                      note="1.3\" 240x240 IPS 面板玻璃"),
    "LCD_Emissive": dict(rgb=(0.000, 0.930, 1.000), transparency=0,
                         note="显示发光面（示意）"),
    "Silicone_Black": dict(rgb=(0.020, 0.020, 0.025), transparency=0,
                           note="遮光框黑色硅胶/泡棉"),
    "PC_Clear": dict(rgb=(0.900, 0.940, 0.950), transparency=55,
                     note="导光柱 PC"),
    "Plastic_Black": dict(rgb=(0.060, 0.060, 0.065), transparency=0,
                          note="连接器 / 轻触键 / 器件黑色塑封"),
}

PART_MAT = {}


def make_material(m, name=""):
    """构造 FreeCAD 1.x 新材质框架的 Materials.Material 对象"""
    try:
        import Materials
        mt = Materials.Material()
        for attr, val in (("Name", name or m.get("name", "")),
                          ("Description", m.get("note", ""))):
            try:
                setattr(mt, attr, val)
            except Exception:
                pass
        return mt
    except Exception as e:
        log("  ! Materials.Material() 失败:", e)
        return None


def add(name, shape, mat, matname=None):
    """新建 Part::Feature 并指定材料"""
    o = doc.addObject("Part::Feature", name)
    o.Shape = shape
    m = MAT[mat]
    try:
        o.ViewObject.ShapeColor = m["rgb"]
        o.ViewObject.Transparency = m["transparency"]
        o.ViewObject.LineColor = tuple(min(1.0, c * 0.45 + 0.08) for c in m["rgb"])
    except Exception as e:
        log("  ! ViewObject color failed for", name, e)
    mt = make_material(m, mat)
    if mt is not None:
        try:
            o.ShapeMaterial = mt
        except Exception as e:
            log("  ! ShapeMaterial failed for", name, e)
    PART_MAT[name] = mat
    log("  + %-22s material=%-16s shape=%s" % (name, mat, matname or ""))
    return o


# ================================================================
# 3. 建模
# ================================================================
log("=" * 60)
log("Prism TV prototype build, FreeCAD", ".".join(FreeCAD.Version()[:3]))
log("=" * 60)
log("[params] HOLDER_ID=%.3f LIP_ID=%.3f PRISM_Z=%.3f ENV_TOP=%.3f"
    % (HOLDER_ID, LIP_ID, P["PRISM_Z"], P["ENV_TOP"]))

doc = FreeCAD.newDocument("PrismTV_Prototype_v1")
# 绑定参数表，方便在 FreeCAD 里查看/二次编辑
try:
    doc.addProperty("App::PropertyString", "Parameters", "Base", "参数快照")
    doc.Parameters = "; ".join("%s=%s" % (k, v) for k, v in sorted(P.items()))
except Exception:
    pass

objs = {}

# ---------------------------------------------------------------- 外壳底座
W, D, H, wall, floor = P["ENV_W"], P["ENV_D"], P["ENV_H"], P["WALL"], P["FLOOR"]
shell = Part.makeBox(W, D, H, Vector(-W / 2, -D / 2, 0))
cavity = Part.makeBox(W - 2 * wall, D - 2 * wall, H,
                      Vector(-(W / 2 - wall), -(D / 2 - wall), floor))
shell = shell.cut(cavity)

# USB-C 开口（+Y 后侧壁，贯穿）
usb_slot = Part.makeBox(9.5, wall + 2, 3.6, Vector(-4.75, D / 2 - wall - 1, 2.0))
shell = shell.cut(usb_slot)
# BH1750 环境光透光孔（+X 侧壁，φ3 贯穿）
lp = Part.makeCylinder(1.5, wall + 2, Vector(W / 2 - wall - 1, 8.0, 4.5), Vector(1, 0, 0))
shell = shell.cut(lp)
# 棱镜支撑：外沿 4 个角托（避免遮住显示窗）
#   卡座本就带托边，这里不再额外做内唇
objs["外壳底座"] = add("外壳底座", shell, "PETG_Matt_Black",
                       "%dx%dx%d, 壁%d 底%d" % (W, D, H, wall, floor))

# 底板四角 M2 沉孔（示意）
for sx in (-1, 1):
    for sy in (-1, 1):
        pass  # 略，螺钉从底部锁入铜柱

# ---------------------------------------------------------------- 主板
mw, md, mt, mz = P["PCB_MAIN_W"], P["PCB_MAIN_D"], P["PCB_T"], P["PCB_Z"]
main_pcb = Part.makeBox(mw, md, mt, Vector(-mw / 2, -md / 2, mz))
for sx in (-1, 1):
    for sy in (-1, 1):
        hole = Part.makeCylinder(1.1, mt + 2,
                                 Vector(sx * P["POST_XY"], sy * P["POST_XY"], mz - 1))
        main_pcb = main_pcb.cut(hole)
objs["主板"] = add("主板", main_pcb, "FR4_Dark",
                   "%dx%dx%.1f" % (mw, md, mt))

# ESP32-PICO-D4 模块（7x7x0.94 + 屏蔽罩）
mod = Part.makeBox(7.0, 7.0, 1.0, Vector(-9.0, -6.0, mz + mt))
objs["ESP32模块"] = add("ESP32模块", mod, "Alu_Shield", "PICO-D4 7x7x1.0")
# 板载 PCB 天线（净空区示意）
ant = Part.makeBox(4.0, 8.0, 0.15, Vector(9.0, -4.0, mz + mt))
objs["PCB天线"] = add("PCB天线", ant, "Copper", "15x8 净空区")

# USB-C 母座
usbc = Part.makeBox(9.0, 7.5, 3.2, Vector(-4.5, md / 2 - 7.5, mz + mt - 1.0))
objs["USB_C座"] = add("USB_C座", usbc, "Alu_Shield", "USB-C 16P")
# 板对板连接器 14P（母座，主板顶面）
btb_off = 22.0 - md / 2          # y=22 处
btb = Part.makeBox(7.0, 2.5, 2.0, Vector(-3.5, btb_off - 1.25, mz + mt))
objs["连接器14P"] = add("连接器14P", btb, "Plastic_Black", "0.4mm 14P")

# 两个轻触键
for i, x in enumerate((-11.0, 11.0)):
    sw = Part.makeBox(3.0, 2.5, 1.5, Vector(x - 1.5, -md / 2 + 2.0, mz + mt))
    objs["轻触键%d" % (i + 1)] = add("轻触键%d" % (i + 1), sw, "Plastic_Black", "SW 3x2.5")

# MPU6050 / BH1750 小封装
imu = Part.makeBox(4.0, 4.0, 0.9, Vector(-6.0, 4.0, mz + mt))
objs["MPU6050"] = add("MPU6050", imu, "Plastic_Black", "QFN-24 4x4")
als = Part.makeBox(2.6, 2.4, 0.9, Vector(12.0, 6.8, mz + mt))
objs["BH1750"] = add("BH1750", als, "Plastic_Black", "WSOF6I")
# 触摸铜箔（贴在外壳前内壁，面内 8x8，法线沿 -Y）
foil = Part.makeBox(8.0, 0.1, 5.0, Vector(-4.0, -W / 2 + wall, 3.0))
objs["触摸铜箔"] = add("触摸铜箔", foil, "Copper", "8x8 内壁触摸条")

# ---------------------------------------------------------------- 支撑柱 x4
post_z = mz + mt
for i, (sx, sy) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
    c = Part.makeCylinder(P["POST_D"] / 2, P["POST_H"],
                          Vector(sx * P["POST_XY"], sy * P["POST_XY"], post_z))
    objs["支撑柱%d" % (i + 1)] = add("支撑柱%d" % (i + 1), c, "Copper",
                                     "M2 铜柱 φ%.0fx%.0f" % (P["POST_D"], P["POST_H"]))

# ---------------------------------------------------------------- 屏幕板
dw, dt, dz = P["PCB_DISP"], P["PCB_DISP_T"], P["PCB_DISP_Z"]
disp_pcb = Part.makeBox(dw, dw, dt, Vector(-dw / 2, -dw / 2, dz))
for sx in (-1, 1):
    for sy in (-1, 1):
        disp_pcb = disp_pcb.cut(Part.makeCylinder(
            1.1, dt + 2, Vector(sx * P["POST_XY"], sy * P["POST_XY"], dz - 1)))
# 板对板公座（底面）
btb2 = Part.makeBox(7.0, 2.5, 1.5, Vector(-3.5, btb_off - 1.25, dz - 1.5))
objs["屏幕板"] = add("屏幕板", disp_pcb, "FR4_Dark", "%dx%dx%.1f" % (dw, dw, dt))
objs["连接器14P_公"] = add("连接器14P_公", btb2, "Plastic_Black", "公座")
# FPC 座
fpc = Part.makeBox(12.0, 3.0, 1.0, Vector(-6.0, -dw / 2 + 1.0, dz + dt))
objs["FPC座"] = add("FPC座", fpc, "Plastic_Black", "0.5mm 8P 翻盖")

# ---------------------------------------------------------------- 显示面板
lw, lt, lz = P["LCD_W"], P["LCD_T"], P["LCD_Z"]
lcd = Part.makeBox(lw, lw, lt, Vector(-lw / 2, -lw / 2, lz))
objs["显示面板"] = add("显示面板", lcd, "LCD_Glass", "%.1fx%.1fx%.1f" % (lw, lw, lt))
a = P["LCD_ACTIVE"]
act = Part.makeBox(a, a, 0.12, Vector(-a / 2, -a / 2, lz + lt))
objs["显示发光面"] = add("显示发光面", act, "LCD_Emissive",
                         "有效区 %.1fx%.1f" % (a, a))

# ---------------------------------------------------------------- 遮光框
sz, st = P["SHIELD_Z"], P["SHIELD_T"]
sh = Part.makeBox(lw, lw, st, Vector(-lw / 2, -lw / 2, sz))
sh = sh.cut(Part.makeBox(a, a, st + 2, Vector(-a / 2, -a / 2, sz - 1)))
objs["遮光框"] = add("遮光框", sh, "Silicone_Black",
                     "外%.1f 内%.1f 厚%.1f" % (lw, a, st))

# ---------------------------------------------------------------- 棱镜卡座
hw, hh, hz = P["ENV_W"], P["HOLDER_H"], P["HOLDER_Z"]
holder = Part.makeBox(hw, hw, hh, Vector(-hw / 2, -hw / 2, hz))
# 上半段：25.05 方孔
holder = holder.cut(Part.makeBox(HOLDER_ID, HOLDER_ID, hh,
                                 Vector(-HOLDER_ID / 2, -HOLDER_ID / 2,
                                        hz + P["HOLDER_LIP_H"])))
# 下半段：23.85 方孔（形成 0.575 托边）
holder = holder.cut(Part.makeBox(LIP_ID, LIP_ID, P["HOLDER_LIP_H"] + 1,
                                 Vector(-LIP_ID / 2, -LIP_ID / 2, hz - 1)))
objs["棱镜卡座"] = add("棱镜卡座", holder, "PETG_Matt_Black",
                       "内口%.2f 托边%.2f" % (HOLDER_ID, P["LIP_GAP"]))

# ---------------------------------------------------------------- 分光棱镜
pz, ps = P["PRISM_Z"], P["PRISM"]
prism = Part.makeBox(ps, ps, ps, Vector(-ps / 2, -ps / 2, pz))
objs["分光棱镜"] = add("分光棱镜", prism, "BK7_Glass", "25x25x25 50:50")

# 分光膜面：45°，平面 y+z=0（棱镜局部坐标），从前上棱到后下棱
pc = pz + ps / 2.0
diag = ps * math.sqrt(2.0)
plate = Part.makeBox(ps, diag, 0.15, Vector(-ps / 2, -diag / 2, -0.075))
plate.rotate(Vector(0, 0, 0), Vector(1, 0, 0), -45.0)
plate.translate(Vector(0, 0, pc))
objs["分光膜"] = add("分光膜", plate, "Coating_Half", "45° 50/50 coating")

# ---------------------------------------------------------------- 棱镜护角 x4
for i, (sx, sy) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
    cw = P["CORNER_W"]
    post = Part.makeBox(cw, cw, P["CORNER_H"],
                        Vector(sx * P["CORNER_XY"] - cw / 2,
                               sy * P["CORNER_XY"] - cw / 2,
                               P["HOLDER_TOP"]))
    objs["棱镜护角%d" % (i + 1)] = add("棱镜护角%d" % (i + 1), post,
                                       "PETG_Matt_Black", "3x3x%.1f" % P["CORNER_H"])

# ---------------------------------------------------------------- 顶部压框
tw, tt, tz = P["ENV_W"], P["TOPFRAME_T"], P["TOPFRAME_Z"]
tf = Part.makeBox(tw, tw, tt, Vector(-tw / 2, -tw / 2, tz))
tf = tf.cut(Part.makeBox(HOLDER_ID, HOLDER_ID, tt + 2,
                         Vector(-HOLDER_ID / 2, -HOLDER_ID / 2, tz - 1)))
objs["顶部压框"] = add("顶部压框", tf, "PETG_Matt_Black", "内口%.2f" % HOLDER_ID)

doc.recompute()
log("[model] 零件数 =", len(objs))

# ================================================================
# 4. 材料对象 + 参数/物料表（文档内可见、可编辑）
# ================================================================
try:
    for i, (mname, m) in enumerate(MAT.items()):
        mo = doc.addObject("App::MaterialObject", "MAT_" + mname)
        r, g, b = m["rgb"]
        mo.Material = {"name": mname,
                       "Color": "(%f,%f,%f,1.0)" % (r, g, b),
                       "Density": "1270 kg/m^3",
                       "Description": m["note"]}
        mo.Label = mname
except Exception as e:
    log("! MaterialObject 失败:", e)

try:
    ss = doc.addObject("Spreadsheet::Sheet", "参数表")
    ss.set("A1", "参数");  ss.set("B1", "数值")
    r = 2
    for k, v in sorted(P.items()):
        ss.set("A%d" % r, k)
        ss.set("B%d" % r, str(v))
        r += 1
    ss.set("D1", "零件"); ss.set("E1", "材料"); ss.set("F1", "说明")
    r = 2
    for name, mat in PART_MAT.items():
        ss.set("D%d" % r, name)
        ss.set("E%d" % r, mat)
        ss.set("F%d" % r, MAT[mat]["note"])
        r += 1
    doc.recompute()
except Exception as e:
    log("! Spreadsheet 失败:", e)

# ================================================================
# 5. 导出
# ================================================================
doc.saveAs(os.path.join(OUT, "PrismTV_Prototype_v1.FCStd"))
log("[save] FCStd ok")

try:
    Part.export(list(objs.values()), os.path.join(OUT, "PrismTV_Prototype_v1.step"))
    log("[save] STEP ok")
except Exception as e:
    log("! STEP 失败:", e)

for name, o in objs.items():
    try:
        Mesh.export([o], os.path.join(STLDIR, name + ".stl"))
    except Exception as e:
        log("! STL %s: %s" % (name, e))
log("[save] STL ok")

with open(os.path.join(OUT, "BOM.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["序号", "零件", "材料", "材料说明", "尺寸(bbox mm)"])
    for i, (name, o) in enumerate(objs.items(), 1):
        bb = o.Shape.BoundBox
        w.writerow([i, name, PART_MAT[name], MAT[PART_MAT[name]]["note"],
                    "%.1f x %.1f x %.1f" % (bb.XLength, bb.YLength, bb.ZLength)])
with open(os.path.join(OUT, "PARAMS.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["参数", "数值(mm)"])
    for k, v in sorted(P.items()):
        w.writerow([k, v])
log("[save] CSV ok")

# ================================================================
# 6. 渲染（需要 GUI）
# ================================================================
if "--no-render" in sys.argv:
    log("[render] skipped")
    doc.save()
    LOG.close()
    raise SystemExit(0)

try:
    import FreeCADGui
    from pivy import coin
except ImportError as e:
    log("! 无 GUI，跳过渲染:", e)
    doc.save()
    LOG.close()
    raise SystemExit(0)

gui_doc = FreeCADGui.ActiveDocument
vw = gui_doc.ActiveView
cam = vw.getCameraNode()

# 关闭渐变背景，纯白更好看
try:
    pr = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View")
    pr.SetBool("Gradient", False)
    pr.SetBool("ShowAxisCross", False)
except Exception:
    pass


def look_at(pos, target=(0, 0, 18), up=(0, 0, 1)):
    px, py, pzz = pos
    tx, ty, tz = target
    zx, zy, zz = px - tx, py - ty, pzz - tz
    n = math.sqrt(zx * zx + zy * zy + zz * zz)
    zx, zy, zz = zx / n, zy / n, zz / n
    ux, uy, uz = up
    xx, xy, xz = uy * zz - uz * zy, uz * zx - ux * zz, ux * zy - uy * zx
    n = math.sqrt(xx * xx + xy * xy + xz * xz)
    xx, xy, xz = (1, 0, 0) if n < 1e-9 else (xx / n, xy / n, xz / n)
    yx, yy, yz = zy * xz - zz * xy, zz * xx - zx * xz, zx * xy - zy * xx
    m = coin.SbMatrix(xx, xy, xz, 0, yx, yy, yz, 0, zx, zy, zz, 0, 0, 0, 0, 1)
    r = coin.SbRotation()
    r.setValue(m)
    cam.position.setValue(px, py, pzz)
    cam.orientation.setValue(r)


def shot(fname, pos, target=(0, 0, 18), w=1000, h=900, fit=True):
    look_at(pos, target)
    FreeCADGui.updateGui()
    time.sleep(0.15)
    if fit:
        vw.fitAll()
    FreeCADGui.updateGui()
    time.sleep(0.25)
    path = os.path.join(RENDER, fname)
    vw.saveImage(path, w, h, "White")
    log("[render]", fname)


def vis(names, state):
    for n in names:
        if n in objs:
            objs[n].ViewObject.Visibility = state


ALL = list(objs.keys())
HOUSING = ["外壳底座", "棱镜卡座", "棱镜护角1", "棱镜护角2", "棱镜护角3",
           "棱镜护角4", "顶部压框"]
PRISM = ["分光棱镜", "分光膜"]

# --- 01 装配总览 ---
shot("01_装配总览_等距.png", (95, -110, 95))
# --- 02 正视（观察方向）---
shot("02_正视_观察方向.png", (0, -260, 20), (0, 0, 20))
# --- 03 侧视 ---
shot("03_侧视.png", (260, 0, 20), (0, 0, 20))
# --- 04 俯视 ---
shot("04_俯视.png", (0.001, 0, 300), (0, 0, 18))

# --- 05 隐藏外壳：看内部双板 ---
vis(HOUSING, False)
vis(PRISM, False)
shot("05_内部双板结构.png", (95, -110, 70), (0, 0, 6))

# --- 05b 隐藏屏幕板：看主板元件面 ---
UPPER = ["屏幕板", "连接器14P_公", "FPC座", "显示面板", "显示发光面", "遮光框"]
vis(UPPER, False)
shot("05b_主板元件面.png", (85, -100, 60), (0, 0, 3))
vis(UPPER, True)

vis(HOUSING, True)
vis(PRISM, True)

# --- 06 隐藏棱镜：看显示与遮光 ---
vis(PRISM, False)
shot("06_显示与遮光层.png", (80, -95, 75), (0, 0, 8))
vis(PRISM, True)

# --- 07 爆炸图 ---
EXPLODE = {
    "外壳底座": 0, "主板": 12, "连接器14P": 12, "ESP32模块": 12, "PCB天线": 12,
    "USB_C座": 12, "轻触键1": 12, "轻触键2": 12, "MPU6050": 12, "BH1750": 12,
    "触摸铜箔": 12, "支撑柱1": 18, "支撑柱2": 18, "支撑柱3": 18, "支撑柱4": 18,
    "屏幕板": 24, "连接器14P_公": 24, "FPC座": 24,
    "显示面板": 30, "显示发光面": 30, "遮光框": 35,
    "棱镜卡座": 43, "分光棱镜": 60, "分光膜": 60,
    "棱镜护角1": 68, "棱镜护角2": 68, "棱镜护角3": 68, "棱镜护角4": 68,
    "顶部压框": 86,
}
orig = {}
for n, o in objs.items():
    orig[n] = FreeCAD.Vector(o.Placement.Base)
    o.Placement.Base = orig[n] + Vector(0, 0, EXPLODE.get(n, 0))
shot("07_爆炸图.png", (150, -170, 130), (0, 0, 55))
for n, o in objs.items():
    o.Placement.Base = orig[n]

# --- 08 剖面（Y-Z 面）+ 光路 ---
# 逐件与半空间求交，比整体 compound 更可靠
cutter = Part.makeBox(100, 300, 300, Vector(0, -150, -100))   # 仅覆盖 x>0
sec_parts = []
for o in objs.values():
    try:
        s = o.Shape.cut(cutter)
        if s and not s.isNull() and s.Volume > 1e-6:
            sec_parts.append(s)
    except Exception as e:
        log("  ! section cut %s: %s" % (o.Label, e))
sec = Part.makeCompound(sec_parts)
log("[section] 保留零件数 = %d" % len(sec_parts))
secobj = doc.addObject("Part::Feature", "SECTION_view")
secobj.Shape = sec
secobj.ViewObject.ShapeColor = (0.55, 0.57, 0.60)
secobj.ViewObject.LineColor = (0.15, 0.15, 0.15)

# 光路：屏幕 -> 45° 分光面 -> 正面(-Y)
#  分光面 y+z=0（棱镜局部），屏幕点 (x0,y0) 成像在正面 (x0,-y0)
rays = []
screen_z = P["LCD_Z"] + P["LCD_T"]        # 面板发光面
pc_z = P["PRISM_Z"] + P["PRISM"] / 2.0    # 棱镜中心高度
for y in (-8.0, 0.0, 8.0):
    hit_z = pc_z - y                      # 与该点在分光面上的交点高度
    p0 = Vector(0, y, screen_z)           # 屏幕发光点
    p1 = Vector(0, y, hit_z)              # 打到分光面
    up = p1 - p0
    rays.append(Part.makeCylinder(0.35, up.Length, p0, up.normalize()))
    p2 = Vector(0, -P["PRISM"] / 2 - 6, hit_z)   # 反射后朝 -Y 射出正面
    out = p2 - p1
    rays.append(Part.makeCylinder(0.35, out.Length, p1, out.normalize()))
rayobj = doc.addObject("Part::Feature", "OPTICAL_PATH")
rayobj.Shape = Part.makeCompound(rays)
rayobj.ViewObject.ShapeColor = (1.0, 0.85, 0.1)
try:
    rayobj.ViewObject.ShapeMaterial.EmissiveColor = (0.9, 0.7, 0.0, 1.0)
except Exception:
    pass
doc.recompute()

vis(ALL, False)
secobj.ViewObject.Visibility = True
rayobj.ViewObject.Visibility = True
shot("08_剖视_光路.png", (300, -45, 30), (0, 0, 20), w=1100, h=900)

# 光路 + 半透明外壳总览
for n in ("外壳底座", "棱镜卡座"):
    objs[n].ViewObject.Visibility = True
shot("09_光路_总览.png", (140, -160, 90), (0, 0, 20))

# 收尾：恢复可见性
secobj.ViewObject.Visibility = False
rayobj.ViewObject.Visibility = False
vis(ALL, True)
doc.removeObject("SECTION_view")
doc.removeObject("OPTICAL_PATH")
doc.recompute()
doc.save()
log("[done] 全部完成")

LOG.close()
os._exit(0)
