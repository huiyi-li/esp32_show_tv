#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把棱镜小电视的结构从 FreeCAD 迁移到 SolidCraft（原生参数化时间线）

产出：
    cad/solidcraft/prismtv.json        命令脚本（可读、可再生成）
    cad/solidcraft/prismtv.solidcraft  原生设计文件（SolidCraft 里可编辑）
    cad/solidcraft/prismtv.step        STEP AP242
    cad/solidcraft/prismtv.png         预览

用法：
    python3 cad/build_solidcraft.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "solidcraft")
os.makedirs(OUT, exist_ok=True)

C = []


def cmd(command_name, **p):
    C.append({"command": command_name, "params": p})


def par(name, expr, unit=None, comment=None, favorite=False):
    p = {"name": name, "expression": expr}
    if unit:
        p["unit"] = unit
    if comment:
        p["comment"] = comment
    if favorite:
        p["favorite"] = True
    cmd("parameters.add", **p)


def box(name, L, W, H, cx, cy, cz, op=None, targets=None):
    p = {"length": L, "width": W, "height": H, "center": [cx, cy, cz], "body_name": name}
    if op:
        p["operation"] = op
    if targets:
        p["targets"] = targets
    cmd("solid.box", **p)


# ================================================================
# 1. 参数（按依赖顺序）
# ================================================================
# —— 外壳
par("BW", "33 mm", comment="外壳宽 X", favorite=True)
par("BD", "40 mm", comment="外壳深 Y", favorite=True)
par("WALL", "2 mm", comment="壁厚", favorite=True)
par("FLOOR", "2 mm", comment="底板厚")
par("BASE_H", "18.7546 mm", comment="外壳前部高度")
par("LEDGE_Z", "6 mm", comment="后平台高度")
par("KNEE_Y", "2.09 mm", comment="斜面/平台交点 Y")
par("CORNER_R", "4 mm", comment="外壳四角圆角（SolidCraft 上限 4：后壁仅 6 高）", favorite=True)

# —— 正面盲槽
par("SLOT_W", "22 mm", comment="盲槽宽", favorite=True)
par("SLOT_H", "6 mm", comment="盲槽高")
par("SLOT_D", "6 mm", comment="盲槽深")
par("SLOT_CZ", "10 mm", comment="盲槽中心 Z")

# —— USB-C
par("USBC_W", "9.5 mm", comment="USB-C 开口宽", favorite=True)
par("USBC_H", "3.4 mm", comment="USB-C 开口高")
par("USBC_CZ", "4.4 mm", comment="USB-C 开口中心 Z")

# —— 光学
par("PRISM", "25.4 mm", comment="分光棱镜边长", favorite=True)
par("YH", "14 mm", comment="光学头半深（屏幕板 28）", favorite=True)
par("TILT", "30 deg", comment="光学头后仰角 = 人眼仰角", favorite=True)
par("PCB_T", "0.8 mm", comment="屏幕板厚")
par("PANEL_T", "1 mm", comment="显示面板厚")
par("SHIELD_T", "0.5 mm", comment="遮光框厚")
par("GLUE_T", "0.1 mm", comment="光学胶厚")
par("HL_Z", "PCB_T + PANEL_T + SHIELD_T + GLUE_T", comment="棱镜底面（头局部 Z）")
par("HEAD_T", "HL_Z + PRISM", comment="光学头沿轴总厚")
par("HY", "-18 mm + YH * cos(TILT)", comment="头局部原点世界 Y（随 TILT 变）")
par("HZ", "3.6 mm + YH * sin(TILT)", comment="头局部原点世界 Z（随 TILT 变）")
par("TOTAL_H", "HZ + YH * sin(TILT) + HEAD_T * cos(TILT)", comment="整机高度")

# —— 托台
par("PL_OUT", "32 mm", comment="托台外轮廓")
par("PL_UP", "PRISM + 0.2 mm", comment="托台上口（贴棱镜）")
par("PL_LO", "YH * 2 + 0.2 mm", comment="托台下口（让屏幕板）")
par("PL_H", "HL_Z + 1 mm", comment="托台总高")

# —— 主板
par("MAIN_W", "28 mm", comment="主板宽", favorite=True)
par("MAIN_D", "28 mm", comment="主板深", favorite=True)
par("MAIN_T", "1 mm", comment="主板厚")
par("MAIN_Z", "2 mm", comment="主板底面 Z")
par("MAIN_Y0", "-11 mm", comment="主板前端 Y")

# ================================================================
# 2. P01 外壳底座：草图 → 对称拉伸 → 挖腔 → 开槽 → 倒圆
# ================================================================
cmd("sketch.create", plane="YZ", name="SK_外壳轮廓")
cmd("sketch.line",
    points=[[-20.0, 0.0], [20.0, 0.0], [20.0, 6.0], [2.09, 6.0], [-20.0, 18.7546]],
    closed=True, ids=["l1", "l2", "l3", "l4", "l5"])
cmd("sketch.finish")
cmd("solid.extrude", distance="BW", direction="symmetric", body_name="P01_外壳底座")

# 内腔（前部 y<-13 保持实心）
box("P01_外壳底座", "BW - 2 * WALL", "31 mm", "38 mm",
    "0 mm", "2.5 mm", "21 mm", op="cut", targets=["P01_外壳底座"])
# 正面圆角盲槽
box("P01_外壳底座", "SLOT_W", "SLOT_D", "SLOT_H",
    "0 mm", "-17.5 mm", "SLOT_CZ", op="cut", targets=["P01_外壳底座"])
# 盲槽四角 R2（SolidCraft 里再补圆角，FreeCAD 版是直接倒角）
cmd("solid.fillet",
    edges=[[11, -17, 7], [-11, -17, 7], [11, -17, 13], [-11, -17, 13]],
    radius="2 mm", body="P01_外壳底座")
# USB-C 开口
box("P01_外壳底座", "USBC_W", "4 mm", "USBC_H",
    "0 mm", "18 mm", "USBC_CZ", op="cut", targets=["P01_外壳底座"])
# 侧壁透光孔
cmd("solid.cylinder", diameter="3 mm", height="8 mm",
    base=["12.5 mm", "-6 mm", "4.2 mm"], axis="X",
    operation="cut", targets=["P01_外壳底座"])
# 四角 R5
cmd("solid.fillet", edges=[[16.5, 20, 3], [-16.5, 20, 3], [16.5, -20, 3], [-16.5, -20, 3]],
    radius="CORNER_R", body="P01_外壳底座")

# ================================================================
# 3. 光学头零件（先按局部坐标建，最后整体后仰）
# ================================================================
HEAD = []

# P02 托台
box("P02_棱镜托台", "PL_OUT", "PL_OUT", "PL_H", "0 mm", "0 mm", "PL_H * 0.5 - 0.5 mm")
HEAD.append("P02_棱镜托台")
box("P02_棱镜托台", "PL_LO", "PL_LO", "1.8 mm",
    "0 mm", "0 mm", "-0.1 mm", op="cut", targets=["P02_棱镜托台"])
box("P02_棱镜托台", "PL_UP", "PL_UP", "4.2 mm",
    "0 mm", "0 mm", "2.9 mm", op="cut", targets=["P02_棱镜托台"])
box("P02_棱镜托台", "34 mm", "14.5 mm", "6 mm",
    "0 mm", "9.75 mm", "1.5 mm", op="cut", targets=["P02_棱镜托台"])
cmd("solid.fillet", edges=[[16, -16, 1], [-16, -16, 1]],
    radius="1.5 mm", body="P02_棱镜托台")

# P03 屏幕板
box("P03_屏幕板", "YH * 2", "YH * 2", "PCB_T",
    "0 mm", "0 mm", "PCB_T * 0.5")
HEAD.append("P03_屏幕板")
# P04 显示面板
box("P04_显示面板", "24.8 mm", "24.8 mm", "PANEL_T",
    "0 mm", "0 mm", "PCB_T + PANEL_T * 0.5")
HEAD.append("P04_显示面板")
# P05 遮光框
box("P05_遮光框", "PRISM", "PRISM", "SHIELD_T",
    "0 mm", "0 mm", "PCB_T + PANEL_T + SHIELD_T * 0.5")
HEAD.append("P05_遮光框")
box("P05_遮光框", "23.4 mm", "23.4 mm", "2.5 mm",
    "0 mm", "0 mm", "PCB_T + PANEL_T + SHIELD_T * 0.5", op="cut", targets=["P05_遮光框"])
# P06 光学胶（环）
box("P06_光学胶", "PRISM", "PRISM", "GLUE_T",
    "0 mm", "0 mm", "HL_Z - GLUE_T * 0.5")
HEAD.append("P06_光学胶")
box("P06_光学胶", "24.2 mm", "24.2 mm", "2 mm",
    "0 mm", "0 mm", "HL_Z - GLUE_T * 0.5", op="cut", targets=["P06_光学胶"])
# P07 分光棱镜
box("P07_分光棱镜", "PRISM", "PRISM", "PRISM",
    "0 mm", "0 mm", "HL_Z + PRISM * 0.5")
HEAD.append("P07_分光棱镜")
# P08 分光膜（45° 平面）
box("P08_分光膜", "PRISM", "PRISM * sqrt(2)", "0.15 mm", "0 mm", "0 mm", "0 mm")
HEAD.append("P08_分光膜")
cmd("solid.move", bodies=["P08_分光膜"], axis=[1, 0, 0], angle="-45 deg",
    translate=["0 mm", "0 mm", "HL_Z + PRISM * 0.5"])

# 光学头整体后仰（改 TILT 即整体旋转）
cmd("solid.move", bodies=HEAD, axis=[1, 0, 0], angle="0 - TILT",
    translate=["0 mm", "HY", "HZ"])

# ================================================================
# 4. 主板与元件（世界坐标、水平）
# ================================================================
box("P09_主板", "MAIN_W", "MAIN_D", "MAIN_T",
    "0 mm", "MAIN_Y0 + MAIN_D * 0.5", "MAIN_Z + MAIN_T * 0.5")


def comp(name, L, W, H, x, y, z):
    """x,y,z = 角点（与 FreeCAD 版一致），这里转成中心"""
    box(name, f"{L} mm", f"{W} mm", f"{H} mm",
        f"{x + L / 2} mm", f"{y + W / 2} mm", f"{z + H / 2} mm")


comp("C01_ESP32模块", 7.0, 7.0, 1.0, -8.0, -6.0, 3.0)
comp("C02_USBC座", 9.0, 7.5, 3.2, -4.5, 9.5, 2.4)
comp("C03_连接器12P", 6.0, 2.5, 2.0, -3.0, 3.0, 3.0)
comp("C04_轻触键1", 3.0, 2.5, 1.5, -13.0, -10.0, 3.0)
comp("C05_轻触键2", 3.0, 2.5, 1.5, 10.0, -10.0, 3.0)
comp("C06_MPU6050", 4.0, 4.0, 0.9, -5.0, -4.0, 3.0)
comp("C07_BH1750", 2.6, 2.4, 0.9, 11.5, -7.2, 3.0)
comp("C08_电源模块", 6.0, 5.0, 1.5, 3.0, -1.0, 3.0)
comp("C09_PCB天线", 4.0, 8.0, 0.12, 3.0, -10.0, 3.0)
comp("C10_触摸铜箔", 0.12, 9.0, 3.0, -16.38, 1.0, 2.6)
comp("C11_后支撑1", 5.0, 5.0, 0.6, -11.5, 2.9, 3.0)
comp("C12_后支撑2", 5.0, 5.0, 0.6, 6.5, 2.9, 3.0)

# ================================================================
# 5. 浏览器分组（零件归类）
# ================================================================
cmd("browser.group", folder="bodies", name="01 外壳组件", items=["P01_外壳底座"])
cmd("browser.group", folder="bodies", name="02 光学头组件",
    items=["P02_棱镜托台", "P03_屏幕板", "P04_显示面板",
           "P05_遮光框", "P06_光学胶", "P07_分光棱镜", "P08_分光膜"])
cmd("browser.group", folder="bodies", name="03 主板与元件",
    items=["P09_主板", "C01_ESP32模块", "C02_USBC座", "C03_连接器12P",
           "C04_轻触键1", "C05_轻触键2", "C06_MPU6050", "C07_BH1750",
           "C08_电源模块", "C09_PCB天线", "C10_触摸铜箔",
           "C11_后支撑1", "C12_后支撑2"])

# ================================================================
# 6. 输出
# ================================================================
script_path = os.path.join(OUT, "prismtv.json")
with open(script_path, "w", encoding="utf-8") as f:
    json.dump({"commands": C}, f, ensure_ascii=False, indent=1)
print("script:", script_path, "commands:", len(C))

design = os.path.join(OUT, "prismtv.solidcraft")
step = os.path.join(OUT, "prismtv.step")
png = os.path.join(OUT, "prismtv.png")

r = subprocess.run(["solidcraft-cli", "run", script_path,
                    "--save", design, "--out", step],
                   capture_output=True, text=True)
print("run rc=%d" % r.returncode)
if r.stdout.strip():
    print(r.stdout[:1500])
if r.returncode != 0:
    print("STDERR:", r.stderr[:3000])
    sys.exit(1)

r = subprocess.run(["solidcraft-cli", "snapshot", design, "--out", png,
                    "--view", "iso", "--width", "1400", "--height", "1100",
                    "--no-grid"],
                   capture_output=True, text=True)
print("snapshot rc=%d" % r.returncode)
if r.returncode != 0:
    print("STDERR:", r.stderr[:2000])

for p in (design, step, png):
    if os.path.exists(p):
        print("  %-46s %8.1f KB" % (os.path.basename(p), os.path.getsize(p) / 1024))

# 另存一份可读的 JSON 设计（同一时间线，纯文本便于 diff / 版本管理）
design_json = os.path.join(OUT, "prismtv.design.json")
r = subprocess.run(["solidcraft-cli", "run", design, "--save", design_json],
                   capture_output=True, text=True)
if r.returncode == 0 and os.path.exists(design_json):
    print("  %-46s %8.1f KB" % (os.path.basename(design_json),
                                os.path.getsize(design_json) / 1024))
else:
    print("json design failed:", r.stderr[:400])
