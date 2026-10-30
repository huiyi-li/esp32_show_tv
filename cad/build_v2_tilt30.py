#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
棱镜小电视（方案二）—— v2 倾斜版原型结构

改动要点（相对 v1 直立版）：
  1. 棱镜 + 屏幕整体**后仰 TILT 度**，出射光相对水平抬升 TILT，
     正好对上坐在桌前的人眼观察仰角（30° 或 45°）。
  2. 底部空间加大：外壳 44×44，内腔 40×40，主板 38×36（v1 只有 30×32）。
  3. 后壁留 USB-C 插电口。

为什么必须整体后仰（关键物理约束）：
  分光棱镜的 45° 分光面是**做死在立方体里的**，屏幕又必须紧贴并平行于棱镜底面。
  所以剩下唯一的自由度就是"屏幕+棱镜一起转"。设整体后仰 α（绕 X 轴转 R_x(-α)）：
      入射 d = (0,0,1)（屏幕朝上发光）
      分光面法线 n = (0,1,1)/√2
      出射 r = d - 2(d·n)n = (0,-1,0)
  旋转后 r_world = R_x(-α)·(0,-1,0) = (0,-cosα, +sinα)
  → 出射光抬高 α 度，且**正好垂直于棱镜"正面"**，所以人眼是正对着看的，不斜视。

运行：
    DISPLAY=:1 freecad cad/build_prototype.py
    freecadcmd cad/build_prototype.py --no-render
"""

import os
import sys
import csv
import math
import time

import FreeCAD
import Part
import Mesh
from FreeCAD import Vector

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
# 1. 参数表（全部 mm / 度）
# ================================================================
P = {
    # ---------- 光学倾角 ----------
    "TILT": 30.0,            # ★ 整体后仰角 = 人眼观察仰角（30 或 45）

    # ---------- 底座外壳 ----------
    "BASE_W": 44.0,          # X 方向外廓
    "BASE_D": 44.0,          # Y 方向外廓
    "WALL": 2.0,
    "FLOOR": 2.0,

    # ---------- 主板 ----------
    "PCB_MAIN_W": 38.0,
    "PCB_MAIN_D": 36.0,
    "PCB_MAIN_T": 1.0,
    "PCB_MAIN_Z": 2.0,
    "PCB_MAIN_Y0": -16.5,    # 主板前端 y

    # ---------- 光学头（自身局部坐标，之后整体旋转）----------
    "HEAD_W": 27.0,          # 局部 X 宽度
    "HEAD_YH": 13.5,         # 局部 ±Y 半深
    "HL_PCB_T": 0.8,         # 屏幕板
    "HL_PANEL_T": 1.0,       # 显示面板
    "HL_SHIELD_T": 0.5,      # 遮光框（同时充当屏幕↔棱镜的间隔）
    "HL_GAP": 0.0,           # 额外间隔（遮光框本身已提供间隔，置 0）
    "PRISM": 25.0,
    "HL_FRAME_T": 1.0,       # 顶部压框
    "HL_MIN": 3.6,           # 光学头最低点距桌面高度（要高于主板元件）

    # ---------- 棱镜卡座 / 护角 ----------
    "LIP": 0.55,             # 卡座托边宽度
    "GAP": 0.05,             # 卡座内口单边余量
    "CORNER_W": 2.0,
    "CORNER_OFF": 13.6,      # 护角中心距头中心

    # ---------- 屏幕有效区 ----------
    "ACTIVE": 23.4,
}

P["HL_Z_PCB"] = 0.0
P["HL_Z_PANEL"] = P["HL_PCB_T"]
P["HL_Z_SHIELD"] = P["HL_Z_PANEL"] + P["HL_PANEL_T"]
P["HL_Z_PRISM"] = P["HL_Z_SHIELD"] + P["HL_SHIELD_T"] + P["HL_GAP"]
P["HL_Z_FRAME"] = P["HL_Z_PRISM"] + P["PRISM"]
P["HEAD_T"] = P["HL_Z_FRAME"] + P["HL_FRAME_T"]        # 光学头沿自身轴的厚度

TILT = math.radians(P["TILT"])
S, C = math.sin(TILT), math.cos(TILT)

# 光学头最低点在世界 z = P["HL_MIN"]；头局部原点（底面中心）的世界 z
P["HEAD_Z0"] = P["HL_MIN"] + P["HEAD_YH"] * S
# 头底面"最前缘"的世界 z
P["HEAD_Z_FRONT"] = P["HEAD_Z0"] + P["HEAD_YH"] * S
# 卡座内口
P["HOLDER_ID"] = P["PRISM"] + 2 * P["GAP"]
P["LIP_ID"] = P["PRISM"] - 2 * P["LIP"]
# 头的最低点在世界 y（= 头底面最后缘）
P["HEAD_Y_LOW"] = P["HEAD_YH"] * C

# 底座高度：让前缘托肩平面刚好托住头底面
P["SHOULDER_Y"] = -P["HEAD_YH"] * C - 0.5
P["SHOULDER_Z"] = P["HEAD_Z_FRONT"] - 0.5 * math.tan(TILT)
P["BASE_H"] = P["SHOULDER_Z"]

# 头在世界坐标里的 y 偏移：让头底面最前缘落在 y = -19.5
P["HEAD_Y0"] = -19.5 + P["HEAD_YH"] * C

# 整机包围盒估算
_head_y_max = P["HEAD_Y0"] + P["HEAD_YH"] * C + P["HEAD_T"] * S
P["TOTAL_H"] = P["HEAD_Z0"] + P["HEAD_YH"] * S + P["HEAD_T"] * C


# ================================================================
# 2. 材料
# ================================================================
MAT = {
    "PETG_Matt_Black": dict(rgb=(0.075, 0.075, 0.085), tr=0,
                            note="外壳/卡座/压框/护角，哑光黑 3D 打印"),
    "FR4_Dark": dict(rgb=(0.030, 0.050, 0.040), tr=0, note="PCB，黑色阻焊 FR4"),
    "Alu_Shield": dict(rgb=(0.760, 0.770, 0.790), tr=0,
                       note="ESP32 模块屏蔽罩 / USB-C 外壳，镀镍金属"),
    "Copper": dict(rgb=(0.720, 0.450, 0.200), tr=0,
                   note="M2 铜柱 / 触摸铜箔 / PCB 天线"),
    "BK7_Glass": dict(rgb=(0.860, 0.930, 0.975), tr=72,
                      note="分光棱镜本体，BK7 光学玻璃"),
    "Coating_Half": dict(rgb=(0.300, 0.720, 1.000), tr=45,
                         note="45° 50:50 分光介质膜"),
    "LCD_Glass": dict(rgb=(0.050, 0.060, 0.080), tr=12,
                      note='1.3" 240x240 IPS 面板玻璃'),
    "LCD_Emissive": dict(rgb=(0.000, 0.930, 1.000), tr=0, note="显示发光面（示意）"),
    "Silicone_Black": dict(rgb=(0.020, 0.020, 0.025), tr=0, note="遮光框黑色硅胶/泡棉"),
    "Plastic_Black": dict(rgb=(0.060, 0.060, 0.065), tr=0,
                          note="连接器 / 轻触键 / 器件黑色塑封"),
}

PART_MAT = {}


def make_material(m, name=""):
    try:
        import Materials
        mt = Materials.Material()
        for attr, val in (("Name", name), ("Description", m.get("note", ""))):
            try:
                setattr(mt, attr, val)
            except Exception:
                pass
        return mt
    except Exception as e:
        log("  ! Materials.Material() 失败:", e)
        return None


def add(name, shape, mat, note=""):
    o = doc.addObject("Part::Feature", name)
    o.Shape = shape
    m = MAT[mat]
    try:
        o.ViewObject.ShapeColor = m["rgb"]
        o.ViewObject.Transparency = m["tr"]
        o.ViewObject.LineColor = tuple(min(1.0, c * 0.45 + 0.08) for c in m["rgb"])
    except Exception as e:
        log("  ! color", name, e)
    mt = make_material(m, mat)
    if mt is not None:
        try:
            o.ShapeMaterial = mt
        except Exception as e:
            log("  ! material", name, e)
    PART_MAT[name] = mat
    log("  + %-16s %-16s %s" % (name, mat, note))
    return o


# ================================================================
# 3. 建模
# ================================================================
log("=" * 66)
log("Prism TV  v2 倾斜版   FreeCAD", ".".join(FreeCAD.Version()[:3]))
log("=" * 66)
log("[参数] TILT=%.0f°  BASE_H=%.2f  HEAD_Z0=%.2f  整机高=%.2f mm"
    % (P["TILT"], P["BASE_H"], P["HEAD_Z0"], P["TOTAL_H"]))
log("[参数] 光学头沿轴厚 HEAD_T=%.2f mm，最低点 z=%.2f" % (P["HEAD_T"], P["HL_MIN"]))

doc = FreeCAD.newDocument("PrismTV_v2_tilted")
try:
    doc.addProperty("App::PropertyString", "Parameters", "Base", "参数快照")
    doc.Parameters = "; ".join("%s=%s" % (k, v) for k, v in sorted(P.items()))
except Exception:
    pass

objs = {}


def xform_head(shape):
    """把光学头局部零件变换到世界坐标：先绕 X 轴后仰 TILT，再平移。"""
    s = shape.copy()
    s.rotate(Vector(0, 0, 0), Vector(1, 0, 0), -P["TILT"])
    s.translate(Vector(0, P["HEAD_Y0"], P["HEAD_Z0"]))
    return s


# ---------------------------------------------------------------- 外壳底座
W, D, wl, fl = P["BASE_W"], P["BASE_D"], P["WALL"], P["FLOOR"]
BH = P["BASE_H"]
outer = Part.makeBox(W, D, BH, Vector(-W / 2, -D / 2, 0))
cav = Part.makeBox(W - 2 * wl, D - 2 * wl, 60,
                   Vector(-(W / 2 - wl), -(D / 2 - wl), fl))
base = outer.cut(cav)

# 前部托肩：斜面与光学头底面共面（30°），托住头的前下缘
sh = Part.makeBox(W - 2 * wl, 8.0, 60,
                  Vector(-(W / 2 - wl), -(D / 2 - wl), fl))
cutter = Part.makeBox(160, 160, 160, Vector(-80, -80, P["SHOULDER_Z"]))
cutter.rotate(Vector(0, P["SHOULDER_Y"], P["SHOULDER_Z"]), Vector(1, 0, 0), -P["TILT"])
shoulder = sh.cut(cutter)
base = base.fuse(shoulder)

# 后面 USB-C 插电口（贯穿后壁）
usb = Part.makeBox(9.5, wl + 4, 3.4, Vector(-4.75, D / 2 - wl - 2, 2.4))
base = base.cut(usb)
# 侧面 BH1750 环境光透光孔（φ3）
lp = Part.makeCylinder(1.5, wl + 4, Vector(W / 2 - wl - 2, -5.0, 4.0), Vector(1, 0, 0))
base = base.cut(lp)
# 底脚避空（四角 R 圆角略）

objs["外壳底座"] = add("外壳底座", base, "PETG_Matt_Black",
                       "%.0fx%.0fx%.1f 壁%.1f 底%.1f" % (W, D, BH, wl, fl))

# ---------------------------------------------------------------- 主板（水平）
mw, md, mt = P["PCB_MAIN_W"], P["PCB_MAIN_D"], P["PCB_MAIN_T"]
my0 = P["PCB_MAIN_Y0"]
mz = P["PCB_MAIN_Z"]
main = Part.makeBox(mw, md, mt, Vector(-mw / 2, my0, mz))
for dx in (-1, 1):
    for dy in (0, 1):
        main = main.cut(Part.makeCylinder(
            1.1, mt + 2, Vector(dx * 15.0, my0 + 3.0 + dy * 30.0, mz - 1)))
objs["主板"] = add("主板", main, "FR4_Dark", "%.0fx%.0fx%.1f" % (mw, md, mt))

zt = mz + mt

# ESP32-PICO-D4 模块（前部）
objs["ESP32模块"] = add("ESP32模块",
                        Part.makeBox(7.0, 7.0, 1.0, Vector(-9.5, my0 + 6.0, zt)),
                        "Alu_Shield", "PICO-D4 7x7x1.0")
# 板载天线净空区（前左）
objs["PCB天线"] = add("PCB天线",
                      Part.makeBox(4.0, 8.0, 0.12, Vector(8.0, my0 + 1.0, zt)),
                      "Copper", "15x8 净空区")
# USB-C 母座（后缘，正对后壁开口）
usbc = Part.makeBox(9.0, 7.5, 3.2, Vector(-4.5, my0 + md - 7.5, zt - 0.6))
objs["USB_C座"] = add("USB_C座", usbc, "Alu_Shield", "USB-C 16P 后向")
# 板对板连接器（屏幕板→主板），放中后部
btb = Part.makeBox(7.0, 2.5, 2.0, Vector(-3.5, 6.0, zt))
objs["连接器14P"] = add("连接器14P", btb, "Plastic_Black", "0.4mm 14P")
# 轻触键
for i, x in enumerate((-13.0, 13.0)):
    objs["轻触键%d" % (i + 1)] = add(
        "轻触键%d" % (i + 1),
        Part.makeBox(3.0, 2.5, 1.5, Vector(x - 1.5, my0 + 2.0, zt)),
        "Plastic_Black", "SW 3x2.5")
# MPU6050
objs["MPU6050"] = add("MPU6050",
                      Part.makeBox(4.0, 4.0, 0.9, Vector(-6.0, -6.0, zt)),
                      "Plastic_Black", "QFN-24 4x4")
# BH1750（靠 +X 侧壁）
objs["BH1750"] = add("BH1750",
                     Part.makeBox(2.6, 2.4, 0.9, Vector(14.5, -6.2, zt)),
                     "Plastic_Black", "WSOF6I")
# 电源电感 / Buck
objs["电源模块"] = add("电源模块",
                       Part.makeBox(6.0, 5.0, 1.5, Vector(4.0, -12.0, zt)),
                       "Plastic_Black", "Buck+SOC")
# 触摸铜箔（贴前内壁）
objs["触摸铜箔"] = add("触摸铜箔",
                       Part.makeBox(8.0, 0.1, 5.0, Vector(-4.0, -D / 2 + wl, 3.0)),
                       "Copper", "8x8 内壁触摸条")

# ---------------------------------------------------------------- 光学头（局部→世界）
HW, YH = P["HEAD_W"], P["HEAD_YH"]
act = P["ACTIVE"]

# 屏幕板
pcb = Part.makeBox(HW, 2 * YH, P["HL_PCB_T"], Vector(-HW / 2, -YH, P["HL_Z_PCB"]))
for dx in (-1, 1):
    for dy in (-1, 1):
        pcb = pcb.cut(Part.makeCylinder(
            1.05, P["HL_PCB_T"] + 2,
            Vector(dx * 11.5, dy * (YH - 1.5), P["HL_Z_PCB"] - 1)))
objs["屏幕板"] = add("屏幕板", xform_head(pcb), "FR4_Dark",
                     "%.1fx%.1fx%.1f" % (HW, 2 * YH, P["HL_PCB_T"]))
# FPC 座
objs["FPC座"] = add("FPC座",
                    xform_head(Part.makeBox(11.0, 3.0, 1.0,
                                            Vector(-5.5, -YH + 0.6, P["HL_Z_PCB"] + P["HL_PCB_T"]))),
                    "Plastic_Black", "0.5mm 8P")
# 板对板公座
objs["连接器14P_公"] = add("连接器14P_公",
                           xform_head(Part.makeBox(7.0, 2.5, 1.5,
                                                   Vector(-3.5, 5.0, P["HL_Z_PCB"] - 1.5))),
                           "Plastic_Black", "公座")

# 显示面板
plw = 24.8
objs["显示面板"] = add("显示面板",
                       xform_head(Part.makeBox(plw, plw, P["HL_PANEL_T"],
                                               Vector(-plw / 2, -plw / 2, P["HL_Z_PANEL"]))),
                       "LCD_Glass", "%.1fx%.1f" % (plw, plw))
objs["显示发光面"] = add("显示发光面",
                        xform_head(Part.makeBox(act, act, 0.12,
                                                Vector(-act / 2, -act / 2,
                                                       P["HL_Z_PANEL"] + P["HL_PANEL_T"]))),
                        "LCD_Emissive", "有效区 %.1f" % act)

# 遮光框（同时充当屏幕↔棱镜的 0.5mm 间隔）
plw = 25.0
shd = Part.makeBox(plw, plw, P["HL_SHIELD_T"],
                   Vector(-plw / 2, -plw / 2, P["HL_Z_SHIELD"]))
shd = shd.cut(Part.makeBox(act, act, P["HL_SHIELD_T"] + 2,
                           Vector(-act / 2, -act / 2, P["HL_Z_SHIELD"] - 1)))
objs["遮光框"] = add("遮光框", xform_head(shd), "Silicone_Black",
                     "外%.1f 内%.1f" % (plw, act))

# 分光棱镜
ps = P["PRISM"]
prism = Part.makeBox(ps, ps, ps, Vector(-ps / 2, -ps / 2, P["HL_Z_PRISM"]))
objs["分光棱镜"] = add("分光棱镜", xform_head(prism), "BK7_Glass", "25x25x25 50:50")

# 分光膜：局部坐标下平面 y + z = 0（过棱镜中心），前上棱→后下棱
pcz = P["HL_Z_PRISM"] + ps / 2.0
diag = ps * math.sqrt(2.0)
plate = Part.makeBox(ps, diag, 0.15, Vector(-ps / 2, -diag / 2, -0.075))
plate.rotate(Vector(0, 0, 0), Vector(1, 0, 0), -45.0)
plate.translate(Vector(0, 0, pcz))
objs["分光膜"] = add("分光膜", xform_head(plate), "Coating_Half", "45° 50/50")

# 棱镜卡座（环形，托住棱镜底部并遮光；外径与光学头齐平 27）
hid, lid, lip = P["HOLDER_ID"], P["LIP_ID"], P["LIP"]
hold_t = 1.6
ow = P["HEAD_W"]
hz0 = P["HL_Z_SHIELD"]
hb = Part.makeBox(ow, ow, hold_t, Vector(-ow / 2, -ow / 2, hz0))
hb = hb.cut(Part.makeBox(hid, hid, hold_t + 2, Vector(-hid / 2, -hid / 2, hz0)))
# 下半段收成 23.9，形成 0.55 托边（不遮显示窗）
hb = hb.cut(Part.makeBox(lid, lid, 0.6 + 1, Vector(-lid / 2, -lid / 2, hz0 - 1)))
objs["棱镜卡座"] = add("棱镜卡座", xform_head(hb), "PETG_Matt_Black",
                       "环形 外%.0f 内口%.2f 托边%.2f" % (ow, hid, lip))

# 棱镜护角 ×4（沿头轴，卡住棱镜四角）
cw = P["CORNER_W"]
co = P["CORNER_OFF"]
corn_z0 = P["HL_Z_PRISM"]
corn_h = P["PRISM"] + P["HL_FRAME_T"]
for i, (dx, dy) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
    cp = Part.makeBox(cw, cw, corn_h,
                      Vector(dx * co - cw / 2, dy * co - cw / 2, corn_z0))
    objs["棱镜护角%d" % (i + 1)] = add("棱镜护角%d" % (i + 1), xform_head(cp),
                                       "PETG_Matt_Black", "%.1fx%.1f" % (cw, cw))

# 顶部压框
hz = P["HL_Z_FRAME"]
tf = Part.makeBox(HW, 2 * YH, P["HL_FRAME_T"], Vector(-HW / 2, -YH, hz))
tf = tf.cut(Part.makeBox(hid, hid, P["HL_FRAME_T"] + 2, Vector(-hid / 2, -hid / 2, hz - 1)))
objs["顶部压框"] = add("顶部压框", xform_head(tf), "PETG_Matt_Black", "内口%.2f" % hid)

doc.recompute()
log("[model] 零件数 =", len(objs))

bb = None
for o in objs.values():
    b = o.Shape.BoundBox
    bb = b if bb is None else bb.united(b)
log("[bbox] X: %.2f   Y: %.2f   Z: %.2f  →  整机 %.1f × %.1f × %.1f mm"
    % (bb.XLength, bb.YLength, bb.ZLength, bb.XLength, bb.YLength, bb.ZLength))

# 不同倾角的高度预算，方便选型
log("---- 倾角 vs 整机高度预算（同样头厚 %.1f）----" % P["HEAD_T"])
for t in (20, 25, 30, 35, 45):
    tr = math.radians(t)
    h_min = P["HL_MIN"]
    base_h = h_min + 2 * P["HEAD_YH"] * math.sin(tr)
    tot = h_min + 2 * P["HEAD_YH"] * math.sin(tr) + P["HEAD_T"] * math.cos(tr)
    log("   TILT=%2d°  → 底座高≈%.1f  整机高≈%.1f mm" % (t, base_h, tot))

# ================================================================
# 4. 材质卡 / 参数表
# ================================================================
try:
    for mname, m in MAT.items():
        mo = doc.addObject("App::MaterialObject", "MAT_" + mname)
        r, g, b = m["rgb"]
        mo.Material = {"name": mname, "Color": "(%f,%f,%f,1.0)" % (r, g, b),
                       "Description": m["note"]}
        mo.Label = mname
except Exception as e:
    log("! MaterialObject:", e)

try:
    ss = doc.addObject("Spreadsheet::Sheet", "参数表")
    ss.set("A1", "参数"); ss.set("B1", "数值")
    r = 2
    for k, v in sorted(P.items(), key=lambda kv: str(kv[0])):
        ss.set("A%d" % r, str(k)); ss.set("B%d" % r, str(v)); r += 1
    ss.set("D1", "零件"); ss.set("E1", "材料"); ss.set("F1", "说明")
    r = 2
    for name, mat in PART_MAT.items():
        ss.set("D%d" % r, name); ss.set("E%d" % r, mat)
        ss.set("F%d" % r, MAT[mat]["note"]); r += 1
    doc.recompute()
except Exception as e:
    log("! Spreadsheet:", e)

# ================================================================
# 5. 导出
# ================================================================
doc.saveAs(os.path.join(OUT, "PrismTV_v2_tilt%d.FCStd" % int(P["TILT"])))
log("[save] FCStd ok")
try:
    Part.export(list(objs.values()),
                os.path.join(OUT, "PrismTV_v2_tilt%d.step" % int(P["TILT"])))
    log("[save] STEP ok")
except Exception as e:
    log("! STEP:", e)
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
        b = o.Shape.BoundBox
        w.writerow([i, name, PART_MAT[name], MAT[PART_MAT[name]]["note"],
                    "%.1f x %.1f x %.1f" % (b.XLength, b.YLength, b.ZLength)])
with open(os.path.join(OUT, "PARAMS.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["参数", "数值(mm/deg)"])
    for k, v in sorted(P.items(), key=lambda kv: str(kv[0])):
        w.writerow([k, v])
log("[save] CSV ok")

# ================================================================
# 6. 渲染
# ================================================================
if "--no-render" in sys.argv:
    doc.save(); LOG.close(); raise SystemExit(0)

try:
    import FreeCADGui
    from pivy import coin
except ImportError as e:
    log("! 无 GUI，跳过渲染:", e)
    doc.save(); LOG.close(); raise SystemExit(0)

gui_doc = FreeCADGui.ActiveDocument
vw = gui_doc.ActiveView
cam = vw.getCameraNode()
try:
    pr = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View")
    pr.SetBool("Gradient", False)
    pr.SetBool("ShowAxisCross", False)
except Exception:
    pass

CZ = P["TOTAL_H"] / 2.0
EYE_DIR = Vector(0, -C, S)          # 从设备指向人眼（出射光方向）
EYE_DIR.normalize()


def look_at(pos, target=(0, 0, CZ), up=(0, 0, 1)):
    px, py, pz = pos
    tx, ty, tz = target
    zx, zy, zz = px - tx, py - ty, pz - tz
    n = math.sqrt(zx * zx + zy * zy + zz * zz)
    zx, zy, zz = zx / n, zy / n, zz / n
    ux, uy, uz = up
    xx, xy, xz = uy * zz - uz * zy, uz * zx - ux * zz, ux * zy - uy * zx
    n = math.sqrt(xx * xx + xy * xy + xz * xz)
    xx, xy, xz = (1, 0, 0) if n < 1e-9 else (xx / n, xy / n, xz / n)
    yx, yy, yz = zy * xz - zz * xy, zz * xx - zx * xz, zx * xy - zy * xx
    m = coin.SbMatrix(xx, xy, xz, 0, yx, yy, yz, 0, zx, zy, zz, 0, 0, 0, 0, 1)
    r = coin.SbRotation(); r.setValue(m)
    cam.position.setValue(px, py, pz); cam.orientation.setValue(r)


def shot(fname, pos, target=(0, 0, CZ), w=1000, h=900):
    look_at(pos, target)
    FreeCADGui.updateGui(); time.sleep(0.15)
    vw.fitAll(); FreeCADGui.updateGui(); time.sleep(0.25)
    vw.saveImage(os.path.join(RENDER, fname), w, h, "White")
    log("[render]", fname)


def vis(names, st):
    for n in names:
        if n in objs:
            objs[n].ViewObject.Visibility = st


ALL = list(objs.keys())
HOUSING = ["外壳底座"]
PRISM = ["分光棱镜", "分光膜"]
HEAD = [n for n in ALL if n not in HOUSING]

# 人眼方向上的相机位置（正对棱镜正面）
eye_pos = (EYE_DIR.x * 320, EYE_DIR.y * 320, CZ + EYE_DIR.z * 320)

shot("01_装配总览_等距.png", (95, -115, 110))
shot("02_用户视角_正对棱镜.png", eye_pos, w=1000, h=1000)
shot("03_侧视_30度仰角.png", (300, 0, CZ))
shot("04_俯视.png", (0.001, 0, 320))

vis(HOUSING, False)
shot("05_光学头_内部.png", (110, -130, 105))
vis(HOUSING, True)
vis(PRISM, False)
shot("06_显示与遮光层.png", (85, -100, 95))
vis(PRISM, True)

# 主板元件面（只隐藏外壳和"光学头里的光学件"，保留主板上的元件）
OPTICAL = ["屏幕板", "FPC座", "连接器14P_公", "显示面板", "显示发光面",
           "遮光框", "棱镜卡座", "分光棱镜", "分光膜",
           "棱镜护角1", "棱镜护角2", "棱镜护角3", "棱镜护角4", "顶部压框"]
vis(HOUSING, False)
vis(OPTICAL, False)
shot("07_主板元件面.png", (62, -74, 165), target=(0, 1, 3))
vis(OPTICAL, True)
vis(HOUSING, True)

# 爆炸图：光学头沿自身轴散开，底座沿 Z
EXPLODE = {
    "连接器14P_公": 4, "屏幕板": 6, "FPC座": 6, "连接器14P": 0,
    "显示面板": 11, "显示发光面": 11, "遮光框": 15,
    "棱镜卡座": 20, "分光棱镜": 34, "分光膜": 34,
    "棱镜护角1": 40, "棱镜护角2": 40, "棱镜护角3": 40, "棱镜护角4": 40,
    "顶部压框": 56,
}
AXIS = Vector(0, S, C)          # 光学头自身轴（世界方向）
AXIS.normalize()
orig = {}
for n, o in objs.items():
    orig[n] = FreeCAD.Vector(o.Placement.Base)
    if n in EXPLODE:
        o.Placement.Base = orig[n] + AXIS * EXPLODE[n]
    elif n != "外壳底座":
        o.Placement.Base = orig[n] + Vector(0, 0, 10)
shot("08_爆炸图.png", (165, -185, 165), target=(0, 0, CZ + 22), w=1100, h=900)
for n, o in objs.items():
    o.Placement.Base = orig[n]

# 剖视 + 光路（沿 Y-Z 面剖开）
cut = Part.makeBox(400, 400, 400, Vector(0, -200, -200))
parts = []
for o in objs.values():
    try:
        s = o.Shape.cut(cut)
        if s and not s.isNull() and s.Volume > 1e-6:
            parts.append(s)
    except Exception as e:
        log("  ! section %s: %s" % (o.Label, e))
secobj = doc.addObject("Part::Feature", "SECTION_view")
secobj.Shape = Part.makeCompound(parts)
secobj.ViewObject.ShapeColor = (0.55, 0.57, 0.60)
secobj.ViewObject.LineColor = (0.15, 0.15, 0.15)
log("[section] 保留零件 = %d" % len(parts))

# 光路：屏幕 -> 45°分光面 -> 沿头局部 -Y 出射（变换后即为 EYE_DIR）
rays = []
pc_z = P["HL_Z_PRISM"] + P["PRISM"] / 2.0
scr_z = P["HL_Z_PANEL"] + P["HL_PANEL_T"]
for yl in (-8.0, 0.0, 8.0):
    hit_z = pc_z - yl                    # 与局部 y+z=pc_z 平面的交点
    p0 = Vector(0, yl, scr_z)
    p1 = Vector(0, yl, hit_z)
    p2 = p1 + Vector(0, -1, 0) * 22.0
    for a, b in ((p0, p1), (p1, p2)):
        d = b - a
        rays.append(Part.makeCylinder(0.4, d.Length, a, d.normalize()))
rayobj = doc.addObject("Part::Feature", "OPTICAL_PATH")
rayobj.Shape = Part.makeCompound([xform_head(r) for r in rays])
rayobj.ViewObject.ShapeColor = (1.0, 0.85, 0.1)
try:
    rayobj.ViewObject.ShapeMaterial.EmissiveColor = (0.9, 0.7, 0.0, 1.0)
except Exception:
    pass
doc.recompute()

vis(ALL, False)
secobj.ViewObject.Visibility = True
rayobj.ViewObject.Visibility = True
shot("09_剖视_光路.png", (330, 0, CZ), w=1100, h=900)
for n in ("外壳底座",):
    objs[n].ViewObject.Visibility = True
shot("10_光路_用户视角.png", eye_pos, w=1000, h=1000)

# ---- 人眼观察示意（+ 桌面）----
def head_to_world(pt):
    x, y, z = pt.x, pt.y, pt.z
    return FreeCAD.Vector(x, y * C + z * S + P["HEAD_Y0"], -y * S + z * C + P["HEAD_Z0"])


pc_w = head_to_world(Vector(0, 0, P["HL_Z_PRISM"] + P["PRISM"] / 2.0))
exit_w = head_to_world(Vector(0, -P["PRISM"] / 2.0, P["HL_Z_PRISM"] + P["PRISM"] / 2.0))
eye_tip = exit_w + EYE_DIR * 115.0

extra = []
# 人眼视线（从棱镜正面沿 30° 仰角射向人眼）
d = eye_tip - exit_w
extra.append(Part.makeCylinder(1.0, d.Length, exit_w, d.normalize()))
# 眼睛标记
extra.append(Part.makeSphere(4.5, eye_tip))
eyeobj = doc.addObject("Part::Feature", "EYE_VIEW")
eyeobj.Shape = Part.makeCompound(extra)
eyeobj.ViewObject.ShapeColor = (1.0, 0.55, 0.1)
# 桌面
deskobj = doc.addObject("Part::Feature", "DESK")
deskobj.Shape = Part.makeBox(190, 190, 1.2, Vector(-95, -95, -1.2))
deskobj.ViewObject.ShapeColor = (0.72, 0.68, 0.62)
doc.recompute()

rayobj.ViewObject.Visibility = False
vis(ALL, True)
eyeobj.ViewObject.Visibility = True
deskobj.ViewObject.Visibility = True
shot("11_人眼观察示意.png", (420, -60, 60), target=(0, -35, 30), w=1100, h=800)
eyeobj.ViewObject.Visibility = False
deskobj.ViewObject.Visibility = False
doc.removeObject("EYE_VIEW")
doc.removeObject("DESK")

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
