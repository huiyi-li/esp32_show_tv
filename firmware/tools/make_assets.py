#!/usr/bin/env python3
"""
make_assets.py —— 为 Prism TV 生成内置图片资源（嵌入固件）

产物（写到 firmware/main/）：
  - anim_frames.bin    分帧动画：N 帧 ALPHA_2BIT(240x120)，4px/byte，MSB 优先
  - weather_icons.bin  天气图标：8 个 ALPHA_4BIT(48x48)，2px/byte，高半字节优先
  - assets_gen.h       上述资源的尺寸/数量宏（供 C 代码对齐使用）

两种格式都是 LVGL 的“alpha 蒙版”图：黑色=透明，白色=不透明，
显示时用 lv_obj_set_style_img_recolor() 任意上色。

用法：
  python3 tools/make_assets.py                # 输入 tools/frames/*.jpg
  python3 tools/make_assets.py --frames DIR
"""

import argparse
import glob
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("需要 Pillow: pip install pillow")

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "..", "main")

# ---- 动画 ----
ANIM_W, ANIM_H = 230, 115   # 2:1，匹配 230x230 可视区宽度
ANIM_BPP = 2                # 2bit -> 4 级灰阶（透明/1/3/2/3/不透明）
CORE_THRESHOLD = 170        # 高于此亮度作为“白色核心”层（1bit）

# ---- 天气图标 ----
ICON = 48
ICON_BPP = 4                # 4bit -> 16 级，边缘平滑
ICON_NAMES = ["sun", "sun_cloud", "cloud", "rain",
              "thunder", "snow", "fog", "haze"]

# ---- 界面小图标（温度计 / 水滴）----
UI_ICON_NAMES = ["thermo", "drop"]
UI_ICON = 24
UI_ICON_BPP = 4


# ======================================================================
#  打包 helper：把 L 模式灰度图按每像素 bpp 位、MSB 优先打包
# ======================================================================
def pack_alpha(gray_img, bpp):
    w, h = gray_img.size
    maxv = (1 << bpp) - 1
    px = gray_img.load()
    per_byte = 8 // bpp
    stride = (w + per_byte - 1) // per_byte
    out = bytearray(stride * h)
    for y in range(h):
        row = y * stride
        for x in range(w):
            v = int(round(px[x, y] * maxv / 255))
            if v < 0:
                v = 0
            elif v > maxv:
                v = maxv
            shift = 8 - bpp * ((x % per_byte) + 1)
            out[row + x // per_byte] |= v << shift
    return bytes(out)


# ======================================================================
#  分帧动画
# ======================================================================
def build_anim(frames_dir):
    files = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")),
                   key=lambda p: int(os.path.splitext(os.path.basename(p))[0]))
    if not files:
        sys.exit(f"没有找到帧图片: {frames_dir}/*.jpg")

    blob = bytearray()
    for p in files:
        im = Image.open(p).convert("L")
        # 轻微提对比，让线条更亮、暗部更干净
        im = im.point(lambda v: 0 if v < 10 else min(255, int((v - 10) * 255 / (235 - 10))))
        im = im.resize((ANIM_W, ANIM_H), Image.LANCZOS)

        # 每个像素两平面：
        #   glow：2bit alpha（平滑边缘，显示为发光色）
        #   core：1bit alpha（高亮核心，显示为白色）
        glow = pack_alpha(im, ANIM_BPP)
        core = pack_alpha(im.point(lambda v: 255 if v > CORE_THRESHOLD else 0), 1)
        blob += glow + core

    with open(os.path.join(MAIN, "anim_frames.bin"), "wb") as f:
        f.write(blob)

    glow_per = (ANIM_W + (8 // ANIM_BPP) - 1) // (8 // ANIM_BPP) * ANIM_H
    core_per = ((ANIM_W + 7) // 8) * ANIM_H
    print(f"anim_frames.bin : {len(files)} 帧, {ANIM_W}x{ANIM_H}, "
          f"glow {glow_per}B + core {core_per}B = {glow_per + core_per} B/帧, "
          f"共 {len(blob)} B")
    return len(files), glow_per, core_per


# ======================================================================
#  天气图标（用 PIL 画形状，4 倍超采样后缩小以获得抗锯齿）
# ======================================================================
S = 4                     # 超采样倍数
W = ICON * S


def new_canvas():
    im = Image.new("L", (W, W), 0)
    return im, ImageDraw.Draw(im)


def circle(d, cx, cy, r, fill=255):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def sun(d, cx, cy, r):
    circle(d, cx, cy, r)
    import math
    for i in range(8):
        a = math.radians(i * 45)
        x0 = cx + math.cos(a) * r * 1.45
        y0 = cy + math.sin(a) * r * 1.45
        x1 = cx + math.cos(a) * r * 2.05
        y1 = cy + math.sin(a) * r * 2.05
        d.line([x0, y0, x1, y1], fill=255, width=int(W * 0.045))


def cloud(d, cx, cy, s):
    """一排圆 + 底部长圆，拼出云朵"""
    circle(d, cx - 0.62 * s, cy + 0.02 * s, 0.40 * s)
    circle(d, cx - 0.10 * s, cy - 0.28 * s, 0.55 * s)
    circle(d, cx + 0.55 * s, cy - 0.02 * s, 0.44 * s)
    d.rounded_rectangle([cx - 0.95 * s, cy - 0.05 * s, cx + 0.95 * s, cy + 0.45 * s],
                        radius=0.42 * s, fill=255)


def draw_icon(name, warm, cool):
    """把图标分别画到两个画布：
       warm = 太阳/闪电（显示为黄色）
       cool = 云/雨/雪/雾/霾条（显示为蓝色）"""
    if name == "sun":
        sun(warm, W * 0.5, W * 0.5, W * 0.20)

    elif name == "sun_cloud":
        sun(warm, W * 0.35, W * 0.33, W * 0.14)
        cloud(cool, W * 0.55, W * 0.62, W * 0.32)

    elif name == "cloud":
        cloud(cool, W * 0.5, W * 0.52, W * 0.40)

    elif name == "rain":
        cloud(cool, W * 0.5, W * 0.42, W * 0.36)
        for x in (0.30, 0.50, 0.70):
            cool.line([W * x, W * 0.66, W * (x - 0.05), W * 0.82],
                      fill=255, width=int(W * 0.05))

    elif name == "thunder":
        cloud(cool, W * 0.5, W * 0.38, W * 0.36)
        warm.polygon([(W * 0.54, W * 0.60), (W * 0.40, W * 0.80),
                      (W * 0.50, W * 0.80), (W * 0.42, W * 0.98),
                      (W * 0.62, W * 0.74), (W * 0.52, W * 0.74)], fill=255)

    elif name == "snow":
        cloud(cool, W * 0.5, W * 0.40, W * 0.36)
        import math
        for x in (0.32, 0.5, 0.68):
            cx, cy, r = W * x, W * 0.78, W * 0.07
            for i in range(3):
                a = math.radians(i * 60)
                cool.line([cx - math.cos(a) * r, cy - math.sin(a) * r,
                           cx + math.cos(a) * r, cy + math.sin(a) * r],
                          fill=255, width=int(W * 0.035))

    elif name == "fog":
        for i, y in enumerate((0.34, 0.48, 0.62, 0.76)):
            x0, x1 = (0.18, 0.82) if i % 2 == 0 else (0.28, 0.72)
            cool.rounded_rectangle([W * x0, W * y - W * 0.035,
                                    W * x1, W * y + W * 0.035],
                                   radius=W * 0.035, fill=255)

    elif name == "haze":
        sun(warm, W * 0.63, W * 0.34, W * 0.13)
        for i, y in enumerate((0.60, 0.74, 0.88)):
            x0, x1 = (0.14, 0.86) if i % 2 == 0 else (0.26, 0.74)
            cool.rounded_rectangle([W * x0, W * y - W * 0.032,
                                    W * x1, W * y + W * 0.032],
                                   radius=W * 0.032, fill=255)


def draw_ui_icon(name, d):
    """界面小图标（单层，24x24）"""
    if name == "thermo":
        cx = W * 0.5
        # 玻管
        d.rounded_rectangle([cx - W * 0.10, W * 0.14, cx + W * 0.10, W * 0.66],
                            radius=W * 0.10, fill=255)
        # 球泡
        circle(d, cx, W * 0.72, W * 0.17)
    elif name == "drop":
        cx = W * 0.5
        # 水滴：三角 + 圆
        d.polygon([(cx, W * 0.10),
                   (cx - W * 0.30, W * 0.56),
                   (cx + W * 0.30, W * 0.56)], fill=255)
        circle(d, cx, W * 0.62, W * 0.30)


def build_icons():
    blob = bytearray()
    per_plane = None
    for name in ICON_NAMES:
        warm_im, warm_d = new_canvas()
        cool_im, cool_d = new_canvas()
        draw_icon(name, warm_d, cool_d)
        warm = pack_alpha(warm_im.resize((ICON, ICON), Image.LANCZOS), ICON_BPP)
        cool = pack_alpha(cool_im.resize((ICON, ICON), Image.LANCZOS), ICON_BPP)
        per_plane = len(warm)
        blob += warm + cool

    with open(os.path.join(MAIN, "weather_icons.bin"), "wb") as f:
        f.write(blob)
    print(f"weather_icons.bin: {len(ICON_NAMES)} 个图标 x2 层, {ICON}x{ICON}, "
          f"{per_plane} B/层, 共 {len(blob)} B")
    return per_plane


def build_ui_icons():
    blob = bytearray()
    per = None
    for name in UI_ICON_NAMES:
        im, d = new_canvas()
        draw_ui_icon(name, d)
        im = im.resize((UI_ICON, UI_ICON), Image.LANCZOS)
        data = pack_alpha(im, UI_ICON_BPP)
        per = len(data)
        blob += data

    with open(os.path.join(MAIN, "ui_icons.bin"), "wb") as f:
        f.write(blob)
    print(f"ui_icons.bin    : {len(UI_ICON_NAMES)} 个图标, {UI_ICON}x{UI_ICON}, "
          f"{per} B/个, 共 {len(blob)} B")
    return per


# ======================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=os.path.join(HERE, "frames"))
    args = ap.parse_args()

    n_anim, glow_per, core_per = build_anim(args.frames)
    icon_per = build_icons()
    ui_per = build_ui_icons()

    with open(os.path.join(MAIN, "assets_gen.h"), "w") as f:
        f.write("/* 自动生成，请勿手改：由 tools/make_assets.py 产出 */\n")
        f.write("#pragma once\n\n")
        f.write(f"#define ANIM_FRAME_COUNT      {n_anim}\n")
        f.write(f"#define ANIM_W                {ANIM_W}\n")
        f.write(f"#define ANIM_H                {ANIM_H}\n")
        f.write(f"#define ANIM_GLOW_BYTES       {glow_per}\n")
        f.write(f"#define ANIM_CORE_BYTES       {core_per}\n")
        f.write(f"#define ANIM_BYTES_PER_FRAME  {glow_per + core_per}\n\n")
        f.write(f"#define WICON_COUNT           {len(ICON_NAMES)}\n")
        f.write(f"#define WICON_SIZE            {ICON}\n")
        f.write(f"#define WICON_PLANE_BYTES     {icon_per}\n")
        f.write(f"#define WICON_BYTES_PER_FRAME {icon_per * 2}\n")
        f.write(f"#define UI_ICON_COUNT         {len(UI_ICON_NAMES)}\n")
        f.write(f"#define UI_ICON_SIZE          {UI_ICON}\n")
        f.write(f"#define UI_ICON_BYTES         {ui_per}\n")
    print("assets_gen.h    : 已更新")


if __name__ == "__main__":
    main()
