#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
棱镜小电视（方案二）—— v3 楔形美学版

相对 v2 的改动：
  1. **棱镜直接粘接、完全裸露**：去掉卡座 / 护角 / 顶部压框，棱镜四个侧面 + 顶面全外露，
     只在底面用 0.1mm 光学胶粘在遮光框上。
  2. **底座收窄**：44×44 → **32×40**，宽向只比棱镜(25)多 3.5mm。
  3. **楔形造型**：顶面 = 30° 斜面 + 后部水平台面；四角大 R 倒圆，哑光黑一体感。
  4. 后壁 6mm 高，依然留 USB-C 开口朝后插电。

物理约束（决定了造型为什么"前高后低"）：
  棱镜 45° 分光面做死在立方体里，屏幕必须紧贴并平行于棱镜底面。
  要让出射光抬高 α（= 人眼仰角）射向坐姿的人眼，只能把"屏幕+棱镜"整体绕 X 后仰 α。
  于是屏幕法线变成 (0, sinα, cosα)：**前缘高、后缘低**，
  所以支撑它的底座顶面必然是一条向后下倾 30° 的斜面 —— 这就是楔形的由来。

    d = (0,0,1)         屏幕朝上发光
    n = (0,1,1)/√2      45° 分光面法线
    r = d − 2(d·n)n = (0,−1,0)        反射到"正面"
    整体后仰 α 后：r_world = (0, −cosα, +sinα)   ← 抬高 α 度射向人眼，且垂直于棱镜正面

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
    LOG.write(msg + "\n"); LOG.flush()
    try:
        print(msg)
    except Exception:
        pass


# ================================================================
# 1. 参数（mm / 度）
# ================================================================
P = {
    "TILT": 30.0,            # ★ 整体后仰角 = 人眼观察仰角

    # ---- 底座（楔形）----
    "BW": 33.0,              # 宽（棱镜 25.4 + 两侧各 3.8）
    "BD": 40.0,              # 深
    "WALL": 2.0,
    "FLOOR": 2.0,
    "LEDGE_Z": 6.0,          # 后部水平台面高度
    "WEDGE_Y0": -20.0,       # 前部实心楔起点
    "WEDGE_Y1": -13.0,       # 前部实心楔终点（其后为腔体）
    "CORNER_R": 5.0,         # 四角倒圆
    "RIM_WALL": 1.5,         # 棱镜包边壁厚（上段）
    "RIM_H": 6.2,            # 棱镜包边高度（沿光学头轴）
    "RIM_COVER": 0.0,        # 包边与棱镜底面齐平（30° 视线下前唇不能更高，否则挡画面）
    "SHELF_Z": 4.5,          # 光学头托板底面高度（托板下方走主板）
    "SHELF_Y1": 2.0,         # 托板后端 y

    # ---- 主板 ----
    "PCB_W": 28.0,
    "PCB_D": 28.0,
    "PCB_T": 1.0,
    "PCB_Z": 2.0,
    "PCB_Y0": -11.0,

    # ---- 光学头（局部坐标，随后整体后仰）----
    "YH": 14.0,              # ±Y 半深（头 28×28）
    "T_PCB": 0.8,            # 屏幕板
    "T_PANEL": 1.0,          # 显示面板
    "T_SHIELD": 0.5,         # 遮光框
    "T_GLUE": 0.1,           # 光学胶层
    "PRISM": 25.4,           # ★ 分光棱镜边长 25.4
    "HL_MIN": 3.6,           # 光学头最低点离桌面高度

    "ACTIVE": 23.4,          # 显示有效区
    "SHIELD_W": 25.4,        # 遮光框外径（= 棱镜，当粘接面）
    "GLUE_MARGIN": 0.0,      # 胶层不外溢（藏在遮光框内）
}

P["HL_Z_PCB"] = 0.0
P["HL_Z_PANEL"] = P["T_PCB"]
P["HL_Z_SHIELD"] = P["HL_Z_PANEL"] + P["T_PANEL"]
P["HL_Z_GLUE"] = P["HL_Z_SHIELD"] + P["T_SHIELD"]
P["HL_Z_PRISM"] = P["HL_Z_GLUE"] + P["T_GLUE"]
P["HEAD_T"] = P["HL_Z_PRISM"] + P["PRISM"]

TILT = math.radians(P["TILT"])
S, C = math.sin(TILT), math.cos(TILT)
T30 = math.tan(TILT)
YH = P["YH"]

# 光学头最低点 = 底面最后缘；头局部原点（底面中心）的世界高度
P["HEAD_Z0"] = P["HL_MIN"] + YH * S
P["HEAD_Z_FRONT"] = P["HEAD_Z0"] + YH * S          # 头底面最前缘
P["FRONT_Y"] = -18.0                                # 头底面最前缘落在 y=-18
P["HEAD_Y0"] = P["FRONT_Y"] + YH * C                # 头局部原点世界 y
P["LOW_Y"] = P["HEAD_Y0"] + YH * C                  # 最低点（= 底面最后缘）的 y

# 底座顶面（前段）= 光学头底面所在平面
P["ROOF_FRONT_Z"] = P["HEAD_Z_FRONT"] + (P["FRONT_Y"] - P["WEDGE_Y0"]) * T30
P["KNEE_Y"] = P["FRONT_Y"] + (P["HEAD_Z_FRONT"] - P["LEDGE_Z"]) / T30
P["TOTAL_H"] = P["HEAD_Z0"] + YH * S + P["HEAD_T"] * C

# 不同倾角的高度预算
HEIGHT_TABLE = []
for t in (20, 25, 30, 35, 45):
    tr = math.radians(t)
    HEIGHT_TABLE.append((t,
                         P["HL_MIN"] + 2 * YH * math.sin(tr),
                         P["HL_MIN"] + 2 * YH * math.sin(tr) + P["HEAD_T"] * math.cos(tr)))

# ================================================================
# 2. 材料
# ================================================================
MAT = {
    "PETG_Beige": dict(rgb=(0.830, 0.770, 0.690), tr=0,
                       note="外壳，暖米白哑光（3D 打印 / 注塑）"),
    "FR4_Dark": dict(rgb=(0.030, 0.050, 0.040), tr=0, note="PCB，黑色阻焊 FR4"),
    "Alu_Shield": dict(rgb=(0.760, 0.770, 0.790), tr=0,
                       note="ESP32 模块屏蔽罩 / USB-C 外壳"),
    "Copper": dict(rgb=(0.720, 0.450, 0.200), tr=0, note="触摸铜箔 / PCB 天线"),
    "BK7_Glass": dict(rgb=(0.870, 0.935, 0.980), tr=74,
                      note="分光棱镜本体，BK7 光学玻璃"),
    "Coating_Half": dict(rgb=(0.300, 0.720, 1.000), tr=45,
                         note="45° 50:50 分光介质膜"),
    "LCD_Glass": dict(rgb=(0.050, 0.060, 0.080), tr=12,
                      note='1.3" 240x240 IPS 面板玻璃'),
    "LCD_Emissive": dict(rgb=(0.000, 0.930, 1.000), tr=0, note="显示发光面（示意）"),
    "Silicone_Black": dict(rgb=(0.020, 0.020, 0.025), tr=0, note="黑色遮光框"),
    "UV_Glue": dict(rgb=(0.820, 0.900, 0.960), tr=62, note="UV 光学胶（棱镜粘接）"),
    "Plastic_Black": dict(rgb=(0.060, 0.060, 0.065), tr=0,
                          note="连接器 / 按键 / 器件黑色塑封"),
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
    except Exception:
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
        except Exception:
            pass
    PART_MAT[name] = mat
    log("  + %-16s %-16s %s" % (name, mat, note))
    return o


# ================================================================
# 3. 建模
# ================================================================
log("=" * 68)
log("Prism TV  v3 楔形美学版   FreeCAD", ".".join(FreeCAD.Version()[:3]))
log("=" * 68)
log("[关键] TILT=%.0f°  头厚 HEAD_T=%.2f  头最低点 z=%.2f  整机高≈%.2f mm"
    % (P["TILT"], P["HEAD_T"], P["HL_MIN"], P["TOTAL_H"]))
log("[底座] 宽 %.0f × 深 %.0f   前顶 z=%.2f  膝点 y=%.2f  后平台 z=%.2f"
    % (P["BW"], P["BD"], P["ROOF_FRONT_Z"], P["KNEE_Y"], P["LEDGE_Z"]))

doc = FreeCAD.newDocument("PrismTV_v3_wedge")
try:
    doc.addProperty("App::PropertyString", "Parameters", "Base", "参数快照")
    doc.Parameters = "; ".join("%s=%s" % (k, v) for k, v in sorted(P.items()))
except Exception:
    pass

objs = {}


def head_xform(shape):
    s = shape.copy()
    s.rotate(Vector(0, 0, 0), Vector(1, 0, 0), -P["TILT"])
    s.translate(Vector(0, P["HEAD_Y0"], P["HEAD_Z0"]))
    return s


def head_to_world(pt):
    x, y, z = pt.x, pt.y, pt.z
    return Vector(x, y * C + z * S + P["HEAD_Y0"], -y * S + z * C + P["HEAD_Z0"])


# ---------------------------------------------------------------- 底座（楔形）
BW, BD, WL, FL = P["BW"], P["BD"], P["WALL"], P["FLOOR"]
y0, y1, yk = P["WEDGE_Y0"], P["WEDGE_Y1"], P["KNEE_Y"]
zf, lz = P["ROOF_FRONT_Z"], P["LEDGE_Z"]

# 用 Y-Z 剖面拉出楔形外形（前高后低）；末尾必须回到起点，否则前面竖边会丢
prof_pts = [Vector(0, y0, 0), Vector(0, BD / 2, 0),
            Vector(0, BD / 2, lz), Vector(0, yk, lz), Vector(0, y0, zf),
            Vector(0, y0, 0)]
face = Part.Face(Part.Wire(Part.makePolygon(prof_pts).Edges))
base = face.extrude(Vector(BW, 0, 0)).translate(Vector(-BW / 2, 0, 0))

# 掏腔（前部 y<y1 保持实心楔，用来托光学头）
cav = Part.makeBox(BW - 2 * WL, (BD / 2 - y1) - WL, 60,
                   Vector(-(BW / 2 - WL), y1, FL))
base = base.cut(cav)

# 光学头托板：z=SHELF_Z 以上、沿 30° 屋面，一直延伸到 y=SHELF_Y1
# 作用：给包边/棱镜一个实心支承，同时下方仍留出主板空间
shelf = Part.makeBox(BW - 2 * WL, (P["SHELF_Y1"] - y1), 40,
                     Vector(-(BW / 2 - WL), y1, P["SHELF_Z"]))
roof_cut = Part.makeBox(300, 300, 300, Vector(-150, -150, 0))
roof_cut.translate(Vector(0, 0, zf))
roof_cut.rotate(Vector(0, y0, zf), Vector(1, 0, 0), -P["TILT"])
shelf = shelf.cut(roof_cut)
base = base.fuse(shelf)
log("[base] 光学头托板已加入（z≥%.1f，y≤%.1f）" % (P["SHELF_Z"], P["SHELF_Y1"]))

# 后壁 USB-C 开口
base = base.cut(Part.makeBox(9.5, WL + 4, 3.4,
                             Vector(-4.75, BD / 2 - WL - 2, 2.7)))
# 右侧壁 BH1750 透光孔
base = base.cut(Part.makeCylinder(1.5, WL + 4,
                                  Vector(BW / 2 - WL - 2, -6.0, 4.2), Vector(1, 0, 0)))
# 前部圆角盲槽（参考图造型：底座正面一个大圆角凹槽）
pocket = Part.makeBox(22.0, 6.0, 6.0, Vector(-11.0, -20.5, 7.0))
try:
    pe = [e for e in pocket.Edges
          if len(e.Vertexes) == 2
          and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-6
          and abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) < 1e-6
          and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) > 1.0]
    pocket = pocket.makeFillet(2.2, pe)
    log("[base] 前部凹槽圆角 OK")
except Exception as e:
    log("! 凹槽圆角失败:", e)
base = base.cut(pocket)

# 四角倒圆：只选最外层 4 条竖直边（要在融合包边之前做，否则拓扑变复杂会失败）
try:
    vz = [e for e in base.Edges
          if len(e.Vertexes) == 2
          and abs(abs(e.Vertexes[0].Point.x) - BW / 2) < 1e-6
          and abs(abs(e.Vertexes[0].Point.y) - BD / 2) < 1e-6
          and abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1.0]
    log("[base] 外层竖边 %d 条" % len(vz))
    if len(vz) == 4:
        base = base.makeFillet(P["CORNER_R"], vz)
        log("[base] 四角 R%.1f 倒圆 OK" % P["CORNER_R"])
except Exception as e:
    log("! 倒圆失败（不影响功能）:", e)

# 棱镜包边：底座侧壁向上延续，与外壳齐平（阶梯内口，下段让开屏幕板、上段贴紧棱镜）
# 注意：30° 视线下前唇不能太高，否则会挡住画面下沿（RIM_COVER 已限制在 1mm）
rim_out = BW - 1.0                          # 32.0：略收进外壳，避免外凸
rim_in_low = 2 * YH + 0.2                   # 28.2 —— 让开 28mm 屏幕板
rim_in_up = P["PRISM"] + 0.2                # 25.6 —— 贴紧 25.4 棱镜
z_low = -0.5
z_mid = P["T_PCB"]                          # 0.8：屏幕板顶面，形成内部台阶
z_top = P["HL_Z_PRISM"] + P["RIM_COVER"]    # 3.4
rim_y1 = 2.5                                # 背面开口位置


def _rbox(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, Vector(x0, y0, z0))


_o = rim_out / 2.0
rim = _rbox(-_o, _o, -_o, _o, z_low, z_top)
# 包边外轮廓四角倒圆（与外壳 R5 呼应，避免方角顶出圆角轮廓）
try:
    ve = [e for e in rim.Edges
          if len(e.Vertexes) == 2
          and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-6
          and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-6
          and abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1.0]
    rim = rim.makeFillet(2.5, ve)
    log("[base] 包边四角 R2.5 OK")
except Exception as e:
    log("! 包边四角倒圆失败:", e)
rim = rim.cut(_rbox(-rim_in_low / 2, rim_in_low / 2,
                    -rim_in_low / 2, rim_in_low / 2, z_low - 1, z_mid))
rim = rim.cut(_rbox(-rim_in_up / 2, rim_in_up / 2,
                    -rim_in_up / 2, rim_in_up / 2, z_mid, z_top + 1))
# 背面开口（便于从后向前装入光学头）
rim = rim.cut(_rbox(-_o - 1, _o + 1, rim_y1, _o + 1, z_low - 1, z_top + 1))
try:
    base = base.fuse(head_xform(rim))
    base = base.removeSplitter()
    log("[base] 阶梯包边已融合（外%.1f / 下口%.1f / 上口%.1f / 高%.1f）"
        % (rim_out, rim_in_low, rim_in_up, z_top - z_low))
except Exception as e:
    log("! 包边融合失败:", e)

objs["外壳底座"] = add("外壳底座", base, "PETG_Beige",
                       "楔形 %.0fx%.0f 前高%.1f 后%.1f" % (BW, BD, zf, lz))

# ---------------------------------------------------------------- 主板
pw, pd_, pt = P["PCB_W"], P["PCB_D"], P["PCB_T"]
py0, pz = P["PCB_Y0"], P["PCB_Z"]
main = Part.makeBox(pw, pd_, pt, Vector(-pw / 2, py0, pz))
for dx in (-1, 1):
    for dy in (-1, 1):
        main = main.cut(Part.makeCylinder(
            1.1, pt + 2, Vector(dx * 11.0, py0 + 3.5 + (dy + 1) / 2 * (pd_ - 7), pz - 1)))
objs["主板"] = add("主板", main, "FR4_Dark", "%.0fx%.0fx%.1f" % (pw, pd_, pt))
zt = pz + pt

objs["ESP32模块"] = add("ESP32模块",
                        Part.makeBox(7.0, 7.0, 1.0, Vector(-8.0, py0 + 5.0, zt)),
                        "Alu_Shield", "PICO-D4 7x7x1.0")
objs["PCB天线"] = add("PCB天线",
                      Part.makeBox(4.0, 8.0, 0.12, Vector(3.0, py0 + 1.0, zt)),
                      "Copper", "15x8 净空区")
# USB-C：贴后缘，正对后壁开口
objs["USB_C座"] = add("USB_C座",
                      Part.makeBox(9.0, 7.5, 3.2, Vector(-4.5, py0 + pd_ - 7.5, zt - 0.6)),
                      "Alu_Shield", "USB-C 16P 后向")
objs["连接器12P"] = add("连接器12P",
                        Part.makeBox(6.0, 2.5, 2.0, Vector(-3.0, py0 + 14.0, zt)),
                        "Plastic_Black", "0.5mm 12P（接屏幕板 FPC）")
for i, x in enumerate((-11.5, 11.5)):
    objs["轻触键%d" % (i + 1)] = add(
        "轻触键%d" % (i + 1),
        Part.makeBox(3.0, 2.5, 1.5, Vector(x - 1.5, py0 + 1.0, zt)),
        "Plastic_Black", "SW 3x2.5")
objs["MPU6050"] = add("MPU6050",
                      Part.makeBox(4.0, 4.0, 0.9, Vector(-5.0, -4.0, zt)),
                      "Plastic_Black", "QFN-24 4x4")
objs["BH1750"] = add("BH1750",
                     Part.makeBox(2.6, 2.4, 0.9, Vector(11.5, -7.2, zt)),
                     "Plastic_Black", "WSOF6I")
objs["电源模块"] = add("电源模块",
                       Part.makeBox(6.0, 5.0, 1.5, Vector(3.0, -1.0, zt)),
                       "Plastic_Black", "Buck + 保护")
# 触摸铜箔（贴 -X 内壁，避开 +X 的 BH1750 透光孔正对面）
objs["触摸铜箔"] = add("触摸铜箔",
                       Part.makeBox(0.12, 9.0, 3.0, Vector(-BW / 2 + WL - 0.12, 1.0, 2.6)),
                       "Copper", "9x3 内壁触摸条")
# 光学头后支撑（2 根矮柱，撑住头的最低点）
for i, x in enumerate((-9.0, 9.0)):
    objs["后支撑%d" % (i + 1)] = add(
        "后支撑%d" % (i + 1),
        Part.makeCylinder(2.5, P["HL_MIN"] - zt, Vector(x, P["LOW_Y"], zt)),
        "Copper", "Φ5 支撑柱 h%.1f" % (P["HL_MIN"] - zt))

# ---------------------------------------------------------------- 光学头
act = P["ACTIVE"]

pcb = Part.makeBox(2 * YH, 2 * YH, P["T_PCB"], Vector(-YH, -YH, P["HL_Z_PCB"]))
objs["屏幕板"] = add("屏幕板", head_xform(pcb), "FR4_Dark",
                     "%.0fx%.0fx%.1f" % (2 * YH, 2 * YH, P["T_PCB"]))
objs["FPC座"] = add("FPC座",
                    head_xform(Part.makeBox(10.0, 2.5, 0.8,
                                            Vector(-5.0, -YH + 0.4, P["HL_Z_PCB"] + P["T_PCB"]))),
                    "Plastic_Black", "0.5mm 8P")

plw = 24.8
objs["显示面板"] = add("显示面板",
                       head_xform(Part.makeBox(plw, plw, P["T_PANEL"],
                                               Vector(-plw / 2, -plw / 2, P["HL_Z_PANEL"]))),
                       "LCD_Glass", "%.1fx%.1f" % (plw, plw))
objs["显示发光面"] = add("显示发光面",
                        head_xform(Part.makeBox(act, act, 0.12,
                                                Vector(-act / 2, -act / 2,
                                                       P["HL_Z_PANEL"] + P["T_PANEL"]))),
                        "LCD_Emissive", "有效区 %.1f" % act)

# 遮光框（也是棱镜的粘接基面）
sw = P["SHIELD_W"]
shd = Part.makeBox(sw, sw, P["T_SHIELD"], Vector(-sw / 2, -sw / 2, P["HL_Z_SHIELD"]))
shd = shd.cut(Part.makeBox(act, act, P["T_SHIELD"] + 2,
                           Vector(-act / 2, -act / 2, P["HL_Z_SHIELD"] - 1)))
objs["遮光框"] = add("遮光框", head_xform(shd), "Silicone_Black",
                     "外%.1f 内%.1f 环宽%.2f" % (sw, act, (sw - act) / 2))

# 光学胶层（棱镜直接粘接，不用任何卡扣）
gm = P["GLUE_MARGIN"]
glue = Part.makeBox(sw + 2 * gm, sw + 2 * gm, P["T_GLUE"],
                    Vector(-(sw / 2 + gm), -(sw / 2 + gm), P["HL_Z_GLUE"]))
glue = glue.cut(Part.makeBox(sw - 0.6, sw - 0.6, P["T_GLUE"] + 2,
                             Vector(-(sw - 0.6) / 2, -(sw - 0.6) / 2, P["HL_Z_GLUE"] - 1)))
objs["光学胶"] = add("光学胶", head_xform(glue), "UV_Glue",
                     "环形外溢 %.1f（粘接）" % gm)

# 分光棱镜（完全裸露）
ps = P["PRISM"]
prism = Part.makeBox(ps, ps, ps, Vector(-ps / 2, -ps / 2, P["HL_Z_PRISM"]))
objs["分光棱镜"] = add("分光棱镜", head_xform(prism), "BK7_Glass",
                       "%.1fx%.1fx%.1f 50:50" % (ps, ps, ps))

# 分光膜（局部 y+z = 过棱镜中心）
pcz = P["HL_Z_PRISM"] + ps / 2.0
diag = ps * math.sqrt(2.0)
plate = Part.makeBox(ps, diag, 0.15, Vector(-ps / 2, -diag / 2, -0.075))
plate.rotate(Vector(0, 0, 0), Vector(1, 0, 0), -45.0)
plate.translate(Vector(0, 0, pcz))
objs["分光膜"] = add("分光膜", head_xform(plate), "Coating_Half", "45° 50/50")

doc.recompute()
log("[model] 零件数 =", len(objs))
bb = None
for o in objs.values():
    b = o.Shape.BoundBox
    bb = b if bb is None else bb.united(b)
log("[bbox] X %.1f  Y %.1f  Z %.2f  →  整机 %.1f × %.1f × %.2f mm"
    % (bb.XLength, bb.YLength, bb.ZLength, bb.XLength, bb.YLength, bb.ZLength))
log("---- 倾角 vs 整机高度 ----")
for t, bh, tot in HEIGHT_TABLE:
    log("   TILT=%2d°  底座前高≈%.1f  整机高≈%.1f mm" % (t, bh, tot))

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
FCSTD = os.path.join(OUT, "PrismTV_v3_wedge.FCStd")
doc.saveAs(FCSTD)
log("[save] FCStd ok")
try:
    Part.export(list(objs.values()), os.path.join(OUT, "PrismTV_v3_wedge.step"))
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
    log("! 无 GUI，跳过渲染:", e); doc.save(); LOG.close(); raise SystemExit(0)

vw = FreeCADGui.ActiveDocument.ActiveView
cam = vw.getCameraNode()
try:
    pr = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View")
    pr.SetBool("Gradient", False); pr.SetBool("ShowAxisCross", False)
except Exception:
    pass

CZ = P["TOTAL_H"] / 2.0
EYE_DIR = Vector(0, -C, S); EYE_DIR.normalize()


def look_at(pos, target=(0, 0, CZ), up=(0, 0, 1)):
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
OPTICS = ["屏幕板", "FPC座", "显示面板", "显示发光面", "遮光框",
          "光学胶", "分光棱镜", "分光膜"]
COMP = [n for n in ALL if n not in OPTICS and n != "外壳底座"]
eye_pos = (EYE_DIR.x * 300, EYE_DIR.y * 300, CZ + EYE_DIR.z * 300)

shot("01_整机_等距.png", (95, -110, 105))
shot("02_整机_用户视角.png", eye_pos, w=1000, h=1000)
shot("03_整机_侧视.png", (300, 0, CZ))
shot("04_棱镜特写.png", (110, -130, 120), target=(0, -1, 26))
vis(["分光棱镜", "分光膜"], False)
shot("05_去掉棱镜_看显示.png", (100, -120, 100))
vis(["分光棱镜", "分光膜"], True)
vis(OPTICS, False)
shot("06_主板元件面.png", (70, -85, 165), target=(0, 1, 3))
vis(OPTICS, True)

# 爆炸图（沿光学头轴）
AXIS = Vector(0, S, C); AXIS.normalize()
EXPLODE = {"FPC座": 3, "屏幕板": 4, "显示面板": 9, "显示发光面": 9,
           "遮光框": 13, "光学胶": 16, "分光棱镜": 26, "分光膜": 26}
orig = {}
for n, o in objs.items():
    orig[n] = FreeCAD.Vector(o.Placement.Base)
    if n in EXPLODE:
        o.Placement.Base = orig[n] + AXIS * EXPLODE[n]
    elif n == "外壳底座":
        pass
    else:
        o.Placement.Base = orig[n] + Vector(0, 0, 9)
shot("07_爆炸图.png", (150, -170, 155), target=(0, 0, CZ + 18), w=1100, h=900)
for n, o in objs.items():
    o.Placement.Base = orig[n]

# 剖视 + 光路
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

rays = []
pc_z = P["HL_Z_PRISM"] + P["PRISM"] / 2.0
scr_z = P["HL_Z_PANEL"] + P["T_PANEL"]
for yl in (-8.0, 0.0, 8.0):
    hit_z = pc_z - yl
    p0 = Vector(0, yl, scr_z); p1 = Vector(0, yl, hit_z)
    p2 = p1 + Vector(0, -1, 0) * 20.0
    for a, b in ((p0, p1), (p1, p2)):
        d = b - a
        rays.append(Part.makeCylinder(0.4, d.Length, a, d.normalize()))
rayobj = doc.addObject("Part::Feature", "OPTICAL_PATH")
rayobj.Shape = Part.makeCompound([head_xform(r) for r in rays])
rayobj.ViewObject.ShapeColor = (1.0, 0.85, 0.1)
try:
    rayobj.ViewObject.ShapeMaterial.EmissiveColor = (0.9, 0.7, 0.0, 1.0)
except Exception:
    pass

# 人眼 + 桌面
exit_w = head_to_world(Vector(0, -P["PRISM"] / 2, pc_z))
eye_tip = exit_w + EYE_DIR * 115.0
d = eye_tip - exit_w
eyeobj = doc.addObject("Part::Feature", "EYE_VIEW")
eyeobj.Shape = Part.makeCompound([Part.makeCylinder(1.0, d.Length, exit_w, d.normalize()),
                                  Part.makeSphere(4.5, eye_tip)])
eyeobj.ViewObject.ShapeColor = (1.0, 0.55, 0.1)
deskobj = doc.addObject("Part::Feature", "DESK")
deskobj.Shape = Part.makeBox(180, 180, 1.2, Vector(-90, -90, -1.2))
deskobj.ViewObject.ShapeColor = (0.72, 0.68, 0.62)
doc.recompute()

vis(ALL, False)
secobj.ViewObject.Visibility = True
rayobj.ViewObject.Visibility = True
shot("08_剖视_光路.png", (330, 0, CZ), w=1100, h=900)

vis(ALL, True)
eyeobj.ViewObject.Visibility = True
deskobj.ViewObject.Visibility = True
shot("09_人眼观察示意.png", (400, -70, 62), target=(0, -32, 28), w=1100, h=800)

secobj.ViewObject.Visibility = False
rayobj.ViewObject.Visibility = False
eyeobj.ViewObject.Visibility = False
deskobj.ViewObject.Visibility = False
for n in ("SECTION_view", "OPTICAL_PATH", "EYE_VIEW", "DESK"):
    doc.removeObject(n)
doc.recompute()
doc.save()
log("[done] 全部完成")
LOG.close()
os._exit(0)
