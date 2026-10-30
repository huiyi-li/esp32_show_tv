#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 cad/out/render/*.png 拼成一张带中文标注和材料图例的总览图。

用法：
    python3 cad/make_contact_sheet.py
输出：
    cad/out/渲染总览.png
"""

import os
import glob
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "out", "render")
OUTFILE = os.path.join(HERE, "out", "渲染总览.png")

# ----------------------------------------------------------------- 字体
FONT_CANDIDATES = [
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Light.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-DemiLight.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/adobe-source-han-serif/SourceHanSerifCN-Bold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def load_font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size, index=0)
            except Exception:
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
    return ImageFont.load_default()


# ----------------------------------------------------------------- 内容
TITLES = {
    "01_整机_等距": "① 整机等距（楔形底座 + 裸露棱镜）",
    "02_整机_用户视角": "② 用户视角（30° 正对棱镜）",
    "03_整机_侧视": "③ 侧视：前高后低楔形",
    "04_棱镜特写": "④ 棱镜特写（完全裸露 / 粘接）",
    "05_去掉棱镜_看显示": "⑤ 去掉棱镜：显示 + 遮光 + 胶层",
    "06_主板元件面": "⑥ 底部主板（28×28）",
    "07_爆炸图": "⑦ 爆炸图（沿 30° 光轴）",
    "08_剖视_光路": "⑧ 剖视 + 光路：屏幕→分光面→人眼",
    "09_人眼观察示意": "⑨ 桌面人眼观察示意（30° 仰角）",
}

ORDER = ["01_整机_等距", "02_整机_用户视角", "03_整机_侧视", "04_棱镜特写",
         "05_去掉棱镜_看显示", "06_主板元件面", "07_爆炸图",
         "08_剖视_光路", "09_人眼观察示意"]

# 材料图例（与 build_prototype.py 的 MAT 一致）
LEGEND = [
    ((0.830, 0.770, 0.690), "PETG 暖米白", "底座外壳 + 棱镜包边（一体哑光）"),
    ((0.030, 0.050, 0.040), "FR4 黑色", "主板 28×28 / 屏幕板 28×28"),
    ((0.760, 0.770, 0.790), "镀镍金属", "ESP32 模块屏蔽罩 / USB-C 座"),
    ((0.720, 0.450, 0.200), "紫铜 / 黄铜", "后支撑柱 / 触摸铜箔 / PCB 天线"),
    ((0.870, 0.935, 0.980), "BK7 光学玻璃", "25.4 × 25.4 × 25.4 分光棱镜"),
    ((0.300, 0.720, 1.000), "分光介质膜", "45° 50:50 镀膜面"),
    ((0.000, 0.930, 1.000), "LCD 发光面", "23.4×23.4 有效显示区"),
    ((0.020, 0.020, 0.025), "黑色硅胶 / 泡棉", "遮光框 外25.4 内窗23.4"),
    ((0.820, 0.900, 0.960), "UV 光学胶", "0.1mm 胶层，棱镜粘接（不夹持）"),
]

COLS = 3
CELL_W, CELL_H = 470, 430
PAD = 18
CAP_H = 36
LEGEND_ROW_H = 46
BG = (248, 248, 249)
FG = (30, 30, 34)
ACCENT = (0, 130, 160)


def fit(img, w, h):
    r = min(w / img.width, h / img.height)
    return img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))),
                      Image.LANCZOS)


def main():
    files = {}
    for name in ORDER:
        p = os.path.join(RENDER, name + ".png")
        if os.path.exists(p):
            files[name] = Image.open(p).convert("RGB")
    if not files:
        raise SystemExit("没有找到渲染图，请先运行 build_prototype.py")

    names = [n for n in ORDER if n in files]
    rows = (len(names) + COLS - 1) // COLS

    legend_h = LEGEND_ROW_H * ((len(LEGEND) + 1) // 2) + 34
    header_h = 104
    W = COLS * CELL_W + (COLS + 1) * PAD
    H = header_h + rows * (CELL_H + CAP_H) + PAD + legend_h + 40

    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)

    f_title = load_font(34)
    f_cap = load_font(21)
    f_small = load_font(17)
    f_tiny = load_font(15)

    # 标题
    d.text((PAD + 4, 18), "棱镜小电视（方案二）· v3 简约版（暖米白）", font=f_title, fill=FG)
    d.text((PAD + 6, 64), "ESP32-PICO-D4 + 1.3\" 240×240 ST7789 + 25.4mm 分光棱镜（粘接、完全裸露）  "
                          "底座 33×40  棱镜包边  光学头后仰 30°", font=f_small, fill=(90, 90, 96))
    d.line([(PAD, header_h - 12), (W - PAD, header_h - 12)], fill=(205, 205, 210), width=2)

    # 图片网格
    for i, name in enumerate(names):
        r, c = divmod(i, COLS)
        x0 = PAD + c * (CELL_W + PAD)
        y0 = header_h + r * (CELL_H + CAP_H)
        img = fit(files[name], CELL_W, CELL_H)
        ox = x0 + (CELL_W - img.width) // 2
        oy = y0 + (CELL_H - img.height) // 2
        d.rectangle([x0 - 3, y0 - 3, x0 + CELL_W + 3, y0 + CELL_H + 3],
                    fill=(255, 255, 255), outline=(218, 218, 224), width=1)
        sheet.paste(img, (ox, oy))
        cap = TITLES.get(name, name)
        tw = d.textlength(cap, font=f_cap)
        d.text((x0 + (CELL_W - tw) / 2, y0 + CELL_H + 8), cap, font=f_cap, fill=ACCENT)

    # 材料图例
    ly = header_h + rows * (CELL_H + CAP_H) + PAD + 8
    d.text((PAD + 4, ly), "材料清单（零件 → 材料）", font=f_cap, fill=FG)
    ly += 32

    col_w = (W - 2 * PAD) // 2
    for i, (rgb, name, note) in enumerate(LEGEND):
        r, c = divmod(i, 2)
        x = PAD + 6 + c * col_w
        y = ly + r * LEGEND_ROW_H
        sw = [int(255 * v) for v in rgb]
        d.rectangle([x, y, x + 26, y + 26], fill=tuple(sw), outline=(150, 150, 155))
        d.text((x + 36, y + 1), name, font=f_small, fill=FG)
        d.text((x + 36, y + 20), note, font=f_tiny, fill=(110, 110, 118))

    sheet.save(OUTFILE, quality=95)
    print("saved:", OUTFILE, sheet.size)


if __name__ == "__main__":
    main()
