#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 PrismTV_Assembly.FCStd 生成工程图（PNG）
  - 零件图：P01 外壳底座、P02 棱镜托台（三视图 + 尺寸 + 标题栏）
  - 装配图：三视图 + 等轴测 + 明细表

投影优先用 TechDraw.projectEx（带消隐），失败则退化为普通边投影。
"""

import os
import math

import FreeCAD as App
import Part
import TechDraw
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
DWG = os.path.join(OUT, "图纸")
os.makedirs(DWG, exist_ok=True)

FONTS = [
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Light.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-DemiLight.ttc",
]


def font(sz):
    for p in FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz, index=0)
            except Exception:
                pass
    return ImageFont.load_default()


# ---------------------------------------------------------------- 投影
def project_edges(shape, direction, hidden=False):
    """返回 [(pts2d, is_hidden), ...]；已修正 TechDraw 投影的坐标轴"""
    d = App.Vector(*direction)
    vis = hid = None
    try:
        r = TechDraw.projectEx(shape, d)
        if isinstance(r, (tuple, list)) and len(r) >= 2:
            vis, hid = r[0], r[1]
        else:
            vis = r
    except Exception:
        try:
            vis = TechDraw.project(shape, d)
        except Exception:
            vis = shape

    # FRONT/SIDE 投影里 projX = -worldZ、projY = 另一水平轴 → 换成 (水平, 竖直)
    swap = tuple(direction) in ((0, -1, 0), (-1, 0, 0))

    out = []
    for shp, is_h in ((vis, False), (hid, True)):
        if shp is None or shp.isNull():
            continue
        if is_h and not hidden:
            continue
        for e in shp.Edges:
            try:
                if e.Length > 90:      # 过滤退化/异常边
                    continue
                pts = e.discretize(24)
            except Exception:
                continue
            if len(pts) < 2:
                continue
            if swap:
                p2 = [(p.y, -p.x) for p in pts]
            else:
                p2 = [(p.x, p.y) for p in pts]
            # 过滤掉投影产生的杂散超长线
            xs = [q[0] for q in p2]; ys = [q[1] for q in p2]
            if max(max(xs) - min(xs), max(ys) - min(ys)) > 120:
                continue
            out.append((p2, is_h))
    return out


def bbox2d(polys):
    xs = [x for pl, _ in polys for x, y in pl]
    ys = [y for pl, _ in polys for x, y in pl]
    if not xs:
        return 0, 0, 1, 1
    return min(xs), min(ys), max(xs), max(ys)


def world_to_screen(vi, wx, wy):
    s, ox, oy = vi[0], vi[1], vi[2]
    return (ox + wx * s, oy - wy * s)


# ---------------------------------------------------------------- 图框
class Sheet:
    def __init__(self, w, h, title, sub=""):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (w, h), "white")
        self.d = ImageDraw.Draw(self.img)
        self.title = title
        self.sub = sub

    def frame(self):
        d = self.d
        d.rectangle([12, 12, self.w - 12, self.h - 12], outline=(40, 40, 40), width=2)
        # 标题栏
        tb_w, tb_h = 430, 96
        x0, y0 = self.w - 12 - tb_w, self.h - 12 - tb_h
        d.rectangle([x0, y0, self.w - 12, self.h - 12], outline=(40, 40, 40), width=2)
        d.line([x0, y0 + 40, self.w - 12, y0 + 40], fill=(40, 40, 40), width=1)
        d.line([x0, y0 + 68, self.w - 12, y0 + 68], fill=(40, 40, 40), width=1)
        d.text((x0 + 10, y0 + 8), self.title, font=font(22), fill=(20, 20, 20))
        d.text((x0 + 10, y0 + 46), self.sub, font=font(14), fill=(70, 70, 70))
        d.text((x0 + 10, y0 + 72), "比例 1:1   单位 mm   第三角投影", font=font(13),
               fill=(70, 70, 70))
        d.text((self.w - 12 - 150, self.h - 12 - 22), "PrismTV", font=font(13),
               fill=(120, 120, 120))

    def view(self, polys, box, label, scale=None, hidden=False):
        """把投影画进 box=(x,y,w,h)，自动缩放居中"""
        bx, by, bw, bh = box
        x0, y0, x1, y1 = bbox2d(polys)
        sw, sh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        s = scale or min((bw - 26) / sw, (bh - 30) / sh)
        ox = bx + (bw - sw * s) / 2 - x0 * s
        oy = by + (bh - sh * s) / 2 + y1 * s
        for pl, is_h in polys:
            if is_h and not hidden:
                continue
            pts = [(ox + x * s, oy - y * s) for x, y in pl]
            if is_h:
                for i in range(0, len(pts) - 1, 2):
                    self.d.line([pts[i], pts[i + 1]], fill=(165, 165, 165), width=1)
            else:
                self.d.line(pts, fill=(20, 20, 20), width=2)
        # 视图名
        tw = self.d.textlength(label, font=font(16))
        self.d.text((bx + (bw - tw) / 2, by + bh - 4), label, font=font(16),
                    fill=(0, 110, 140))
        return s, ox, oy, x0, y0, x1, y1

    def note(self, x, y, lines, sz=14):
        for i, t in enumerate(lines):
            self.d.text((x, y + i * (sz + 6)), t, font=font(sz), fill=(50, 50, 50))

    def dim(self, p1, p2, text, off=28, vert=False):
        """在两点之间画尺寸线（已换算成图纸像素坐标）"""
        d = self.d
        x1, y1 = p1; x2, y2 = p2
        if vert:
            x = x1 + off
            d.line([(x1, y1), (x, y1)], fill=(110, 110, 110), width=1)
            d.line([(x2, y2), (x, y2)], fill=(110, 110, 110), width=1)
            d.line([(x, y1), (x, y2)], fill=(30, 30, 30), width=1)
            for yy, sgn in ((y1, 1), (y2, -1)):
                d.polygon([(x, yy), (x + 7 * sgn, yy - 4), (x + 7 * sgn, yy + 4)],
                          fill=(30, 30, 30))
            d.text((x + 10, (y1 + y2) / 2 - 9), text, font=font(14), fill=(20, 20, 20))
        else:
            y = y1 + off
            d.line([(x1, y1), (x1, y)], fill=(110, 110, 110), width=1)
            d.line([(x2, y2), (x2, y)], fill=(110, 110, 110), width=1)
            d.line([(x1, y), (x2, y)], fill=(30, 30, 30), width=1)
            for xx, sgn in ((x1, 1), (x2, -1)):
                d.polygon([(xx, y), (xx - 4 * sgn, y - 7 * sgn), (xx + 4 * sgn, y - 7 * sgn)],
                          fill=(30, 30, 30))
            tw = d.textlength(text, font=font(14))
            d.text(((x1 + x2) / 2 - tw / 2, y - 22), text, font=font(14), fill=(20, 20, 20))

    def save(self, name):
        p = os.path.join(DWG, name)
        self.img.save(p, quality=95)
        print("saved", p, self.img.size)


# ---------------------------------------------------------------- 取零件
doc = App.openDocument(os.path.join(OUT, "PrismTV_Assembly.FCStd"))


def by_label(lb):
    for o in doc.Objects:
        if o.Label == lb:
            return o
    return None


FRONT = (0, -1, 0)
SIDE = (-1, 0, 0)
TOP = (0, 0, 1)
ISO = (1, -1, 0.9)

# ================================================================
# 零件图：P01 外壳底座
# ================================================================
p01 = by_label("P01 外壳底座")
p02 = by_label("P02 棱镜托台")

if p01:
    sh = Sheet(1684, 1190, "P01 外壳底座", "楔形外壳，暖米白 PETG")
    sh.frame()
    v1 = sh.view(project_edges(p01.Shape, FRONT), (40, 40, 780, 470), "主视图（前）")
    v2 = sh.view(project_edges(p01.Shape, SIDE), (860, 40, 500, 470), "左视图")
    v3 = sh.view(project_edges(p01.Shape, TOP), (40, 540, 780, 470), "俯视图")
    v4 = sh.view(project_edges(p01.Shape, ISO), (860, 540, 500, 470), "等轴测")
    # 尺寸
    bb = p01.Shape.BoundBox
    sh.dim(world_to_screen(v1, bb.XMin, bb.ZMax), world_to_screen(v1, bb.XMax, bb.ZMax),
           "%.2f" % bb.XLength, off=-44)
    sh.dim(world_to_screen(v1, bb.XMax, 0), world_to_screen(v1, bb.XMax, bb.ZMax),
           "%.2f" % bb.ZLength, off=44, vert=True)
    sh.dim(world_to_screen(v2, bb.YMin, bb.ZMax), world_to_screen(v2, bb.YMax, bb.ZMax),
           "%.2f" % bb.YLength, off=-44)
    sh.note(1420, 60, [
        "技术要求：",
        "1. 材料 PETG，哑光暖米白",
        "2. 未注圆角 R0.5",
        "3. 四角 R5，包边四角 R2.5",
        "4. 3D 打印层高 0.2，壁厚≥2",
        "",
        "关键尺寸：",
        "  外形 33 × 40",
        "  前高 18.75 / 后平台 6.0",
        "  腔体 29 × 31 × 深",
        "  正面盲槽 22 × 6 × 6",
        "  USB-C 口 9.5 × 3.4",
        "  透光孔 φ3",
    ])
    sh.save("P01_外壳底座_零件图.png")

if p02:
    sh = Sheet(1684, 1190, "P02 棱镜托台", "阶梯内口，粘接 25.4 棱镜")
    sh.frame()
    v1 = sh.view(project_edges(p02.Shape, FRONT), (40, 40, 780, 470), "主视图（前）")
    v2 = sh.view(project_edges(p02.Shape, SIDE), (860, 40, 500, 470), "左视图")
    v3 = sh.view(project_edges(p02.Shape, TOP), (40, 540, 780, 470), "俯视图")
    v4 = sh.view(project_edges(p02.Shape, ISO), (860, 540, 500, 470), "等轴测")
    bb2 = p02.Shape.BoundBox
    sh.dim(world_to_screen(v1, bb2.XMin, bb2.ZMax), world_to_screen(v1, bb2.XMax, bb2.ZMax),
           "%.2f" % bb2.XLength, off=-44)
    sh.dim(world_to_screen(v2, bb2.YMin, bb2.ZMax), world_to_screen(v2, bb2.YMax, bb2.ZMax),
           "%.2f" % bb2.YLength, off=-44)
    sh.note(1420, 60, [
        "技术要求：",
        "1. 材料 PETG，与外框同色",
        "2. 上口 25.6 与棱镜 25.4 单边间隙 0.1",
        "3. 下口 28.2 让开屏幕板",
        "4. 顶面与棱镜底面齐平（30° 视线限制）",
        "5. 背面开口，从后向前装入光学头",
        "",
        "关键尺寸：",
        "  外形 32 × 32",
        "  上口 25.6 / 下口 28.2",
        "  内台阶 z = 0.8",
        "  四角 R2.5",
    ])
    sh.save("P02_棱镜托台_零件图.png")

# ================================================================
# 装配图
# ================================================================
parts = [o for o in doc.Objects
         if o.Label and (o.Label.startswith("P0") or o.Label.startswith("C"))]


def multi_project(shapes, direction):
    """逐件投影再叠加：避免 compound 投影的杂散线，且所有零件都画出来"""
    out = []
    for s in shapes:
        out += project_edges(s, direction)
    return out


# —— 剖视：x=0 切开，保留 x<0
cutter = Part.makeBox(200, 400, 400, App.Vector(0, -200, -100))
sec_shapes = []
for o in parts:
    try:
        c = o.Shape.cut(cutter)
        if c and not c.isNull() and c.Volume > 1e-6:
            sec_shapes.append(c)
    except Exception:
        pass

# —— 爆炸：光学头零件沿自身轴分开，主板元件沿 Z 抬起
TILT = 30.0 * math.pi / 180.0
AX = App.Vector(0, math.sin(TILT), math.cos(TILT))
OFF = {
    "P02 棱镜托台": 0, "P03 屏幕板": 5, "P04 显示面板": 10,
    "P05 遮光框": 14, "P06 光学胶": 17, "P07 分光棱镜": 28, "P08 分光膜": 28,
}
exp_shapes = []
for o in parts:
    s = o.Shape.copy()
    if o.Label in OFF:
        s.translate(AX * OFF[o.Label])
    elif o.Label.startswith("P09") or o.Label.startswith("C"):
        s.translate(App.Vector(0, 0, 6))
    exp_shapes.append(s)

sh = Sheet(2000, 1400, "PrismTV 总装图", "棱镜小电视 方案二 · 25.4 棱镜 · 后仰 30° · 全零件")
sh.frame()
sh.view(multi_project([o.Shape for o in parts], FRONT), (40, 40, 620, 520), "主视图")
sh.view(multi_project([o.Shape for o in parts], SIDE), (680, 40, 620, 520), "左视图")
if sec_shapes:
    sh.view(multi_project(sec_shapes, SIDE), (40, 590, 620, 520), "剖视图 A-A（x=0 切开）")
if exp_shapes:
    sh.view(multi_project(exp_shapes, ISO), (680, 590, 620, 520), "爆炸等轴测")

# 明细表
tx, ty = 1340, 60
sh.d.rectangle([tx, ty, tx + 620, ty + 34], outline=(40, 40, 40), width=2)
sh.d.text((tx + 8, ty + 6), "明细表 BOM", font=font(16), fill=(20, 20, 20))
rows = [
    ("P01", "外壳底座", "1", "PETG 暖米白"),
    ("P02", "棱镜托台", "1", "PETG 暖米白"),
    ("P03", "屏幕板", "1", "FR4"),
    ("P04", "显示面板", "1", "1.3\" IPS"),
    ("P05", "遮光框", "1", "黑色硅胶"),
    ("P06", "光学胶", "1", "UV 胶"),
    ("P07", "分光棱镜", "1", "BK7 25.4³"),
    ("P08", "分光膜", "1", "介质膜"),
    ("P09", "主板", "1", "FR4 28×28"),
    ("C01-11", "电子元件", "11", "—"),
]
hh = 30
for i, r in enumerate(rows, start=1):
    y = ty + 34 + (i - 1) * hh
    sh.d.rectangle([tx, y, tx + 620, y + hh], outline=(120, 120, 120), width=1)
    for j, (w, v) in enumerate(zip((80, 240, 70, 230), r)):
        xx = tx + sum((80, 240, 70, 230)[:j])
        sh.d.text((xx + 8, y + 6), v, font=font(14), fill=(30, 30, 30))
    sh.d.line([tx + 80, y, tx + 80, y + hh], fill=(170, 170, 170), width=1)
    sh.d.line([tx + 320, y, tx + 320, y + hh], fill=(170, 170, 170), width=1)
    sh.d.line([tx + 390, y, tx + 390, y + hh], fill=(170, 170, 170), width=1)

sh.note(tx, ty + 34 + 10 * hh + 16, [
    "装配关系：",
    "· P07 棱镜用 UV 胶（P06）粘在 P05 遮光框上，",
    "  再一起装入 P02 托台，托台粘/卡在 P01 上；",
    "· P03 屏幕板 + P04 面板 装在 P02 内台阶上，",
    "  板边引出 12P FPC 接到 P09 主板；",
    "· P09 主板水平置于 P01 腔体内（z = 2 → 3），",
    "  USB-C 座正对后壁 9.5×3.4 开口；",
    "· 光学头整体后仰 30°（= 人眼观察仰角），",
    "  出射光垂直于棱镜正面射向人眼。",
], sz=14)

sh.save("装配图.png")
print("done")
import sys
sys.stdout.flush()
os._exit(0)
