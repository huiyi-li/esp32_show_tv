/**
 * @file  ui.c
 * @brief LVGL 界面实现（时钟 / 太空人+时间天气 / 动画 / 系统 / 图片）
 *
 * 设计要点：
 *  - 多个独立 screen，用 lv_scr_load_anim 滑动切换；
 *  - 状态栏与 toast 挂在 lv_layer_top()，所有页面都可见；
 *  - 太空人动画是「双层」：2bit 发光层 + 1bit 白色核心层，
 *    光晕颜色随时间缓慢变化；
 *  - HOME 页把太空人 + 时间 + 日期 + 天气图标/温度/湿度放在同一屏。
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "ui.h"
#include "board_config.h"
#include "weather_icons.h"
#include "ui_icons.h"
#include "assets_gen.h"

#include "esp_lvgl_port.h"
#include "esp_heap_caps.h"
#include "esp_log.h"

static const char *TAG = "ui";

/* 嵌入的动画资源（tools/make_assets.py 生成） */
extern const uint8_t _binary_anim_frames_bin_start[];

static lv_obj_t *s_scr[UI_PAGE_MAX];
static ui_page_t s_page = UI_PAGE_CLOCK;

/* 页面 0（时钟） */
static lv_obj_t *s_lbl_time;
static lv_obj_t *s_lbl_sec;
static lv_obj_t *s_lbl_date;
static lv_obj_t *s_img_weather_cool;
static lv_obj_t *s_img_weather_warm;
static lv_obj_t *s_lbl_weather;
static lv_obj_t *s_lbl_humid;

/* 页面 1（HOME：太空人 + 时间/天气） */
static lv_obj_t *s_home_glow;
static lv_obj_t *s_home_core;
static lv_obj_t *s_home_lbl_time;
static lv_obj_t *s_home_lbl_sec;
static lv_obj_t *s_home_lbl_date;
static lv_obj_t *s_home_lbl_week;
static lv_obj_t *s_home_img_weather_cool;
static lv_obj_t *s_home_img_weather_warm;
static lv_obj_t *s_home_lbl_cond;
static lv_obj_t *s_home_lbl_range;
static lv_obj_t *s_home_img_thermo;
static lv_obj_t *s_home_img_drop;
static lv_obj_t *s_home_bar_temp;
static lv_obj_t *s_home_bar_hum;
static lv_obj_t *s_home_lbl_temp;
static lv_obj_t *s_home_lbl_hum;

/* 页面 2（全屏动画） */
static lv_obj_t *s_anim_glow;
static lv_obj_t *s_anim_core;

/* 动画资源描述符 */
static lv_img_dsc_t s_anim_glow_dsc[ANIM_FRAME_COUNT];
static lv_img_dsc_t s_anim_core_dsc[ANIM_FRAME_COUNT];
static lv_timer_t  *s_anim_timer;
static int          s_anim_idx;
static uint16_t     s_anim_hue;

/* 页面 3（系统） */
static lv_obj_t *s_lbl_temp;
static lv_obj_t *s_lbl_accel;
static lv_obj_t *s_lbl_lux;
static lv_obj_t *s_lbl_net;

/* 页面 4（图片） */
static lv_obj_t *s_canvas;
static lv_obj_t *s_lbl_img_hint;
static uint8_t  *s_img_buf = NULL;

/* 顶层 */
static lv_obj_t *s_lbl_status;
static lv_obj_t *s_toast;
static lv_timer_t *s_toast_timer;

/* 画布占位缓冲（1x1） */
static lv_color_t s_dummy_px;

/* 主题色 */
#define UI_COLOR_TIME   0xFFFFFF
#define UI_COLOR_ACCENT 0x00E5FF
#define UI_COLOR_SEC    0xFFD54F
#define UI_COLOR_DIM    0x9E9E9E
#define UI_COLOR_SUN    0xFFC107   /* 太阳/闪电：琥珀黄 */
#define UI_COLOR_CLOUD  0x4FC3F7   /* 云/雨/雪/雾：天蓝 */

/* ------------------------------------------------------------------ */
/* 小工具                                                              */
/* ------------------------------------------------------------------ */
static void toast_hide_cb(lv_timer_t *t)
{
    (void)t;
    if (s_toast) {
        lv_obj_del(s_toast);
        s_toast = NULL;
    }
    s_toast_timer = NULL;
}

static lv_obj_t *make_label(lv_obj_t *parent, const lv_font_t *font,
                            uint32_t color, lv_align_t align, int x, int y)
{
    lv_obj_t *lbl = lv_label_create(parent);
    lv_obj_set_style_text_font(lbl, font, 0);
    lv_obj_set_style_text_color(lbl, lv_color_hex(color), 0);
    lv_obj_align(lbl, align, x, y);
    return lbl;
}

static lv_obj_t *make_screen(void)
{
    lv_obj_t *scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(scr, 0, 0);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    return scr;
}

/** 把 icon 型图片上色（0xRRGGBB） */
static void tint_img(lv_obj_t *img, uint32_t color)
{
    lv_obj_set_style_img_recolor(img, lv_color_hex(color), 0);
    lv_obj_set_style_img_recolor_opa(img, LV_OPA_COVER, 0);
}

/** 把 icon 型图片上色（lv_color_t，用于动态色） */
static void tint_img_c(lv_obj_t *img, lv_color_t color)
{
    lv_obj_set_style_img_recolor(img, color, 0);
    lv_obj_set_style_img_recolor_opa(img, LV_OPA_COVER, 0);
}

/** 创建双层天气图标：cool 层（蓝）在下、warm 层（黄）在上 */
static void create_weather_icon(lv_obj_t *parent, lv_obj_t **cool, lv_obj_t **warm,
                                lv_align_t align, int x, int y)
{
    *cool = lv_img_create(parent);
    lv_img_set_src(*cool, weather_icon_cool(WICON_SUN));
    tint_img(*cool, UI_COLOR_CLOUD);
    lv_obj_align(*cool, align, x, y);

    *warm = lv_img_create(parent);
    lv_img_set_src(*warm, weather_icon_warm(WICON_SUN));
    tint_img(*warm, UI_COLOR_SUN);
    lv_obj_align(*warm, align, x, y);
}

/** 胶囊形进度条：深色底 + 白色描边 + 彩色填充 */
static lv_obj_t *make_bar(lv_obj_t *parent, uint32_t color)
{
    lv_obj_t *bar = lv_bar_create(parent);
    lv_obj_set_size(bar, 118, 12);
    lv_bar_set_range(bar, 0, 100);
    lv_bar_set_value(bar, 0, LV_ANIM_OFF);

    lv_obj_set_style_bg_color(bar, lv_color_hex(0x14202E), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_border_width(bar, 1, LV_PART_MAIN);
    lv_obj_set_style_border_color(bar, lv_color_hex(0xC8D0D8), LV_PART_MAIN);
    lv_obj_set_style_radius(bar, 6, LV_PART_MAIN);
    lv_obj_set_style_pad_all(bar, 1, LV_PART_MAIN);

    lv_obj_set_style_bg_color(bar, lv_color_hex(color), LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_radius(bar, 5, LV_PART_INDICATOR);
    return bar;
}

/* ------------------------------------------------------------------ */
/* 动画资源 / 双层图片                                                  */
/* ------------------------------------------------------------------ */
static lv_color_t anim_glow_color(void)
{
    /* 饱和度/亮度固定，色相缓慢变化 */
    return lv_color_hsv_to_rgb(s_anim_hue, 85, 100);
}

static void anim_assets_init(void)
{
    const uint8_t *base = _binary_anim_frames_bin_start;

    for (int i = 0; i < ANIM_FRAME_COUNT; i++) {
        const uint8_t *p = base + (size_t)i * ANIM_BYTES_PER_FRAME;

        s_anim_glow_dsc[i].header.cf = LV_IMG_CF_ALPHA_2BIT;
        s_anim_glow_dsc[i].header.w  = ANIM_W;
        s_anim_glow_dsc[i].header.h  = ANIM_H;
        s_anim_glow_dsc[i].data_size = ANIM_GLOW_BYTES;
        s_anim_glow_dsc[i].data      = p;

        s_anim_core_dsc[i].header.cf = LV_IMG_CF_ALPHA_1BIT;
        s_anim_core_dsc[i].header.w  = ANIM_W;
        s_anim_core_dsc[i].header.h  = ANIM_H;
        s_anim_core_dsc[i].data_size = ANIM_CORE_BYTES;
        s_anim_core_dsc[i].data      = p + ANIM_GLOW_BYTES;
    }
}

/** 创建一对动画图片（发光层在下、白色核心层在上） */
static void create_anim_pair(lv_obj_t *parent, lv_obj_t **glow, lv_obj_t **core,
                             lv_align_t align, int x, int y)
{
    *glow = lv_img_create(parent);
    lv_img_set_src(*glow, &s_anim_glow_dsc[0]);
    tint_img_c(*glow, anim_glow_color());
    lv_obj_align(*glow, align, x, y);

    *core = lv_img_create(parent);
    lv_img_set_src(*core, &s_anim_core_dsc[0]);
    tint_img(*core, 0xFFFFFF);
    lv_obj_align(*core, align, x, y);
}

static void anim_tick_cb(lv_timer_t *t)
{
    (void)t;

    s_anim_idx = (s_anim_idx + 1) % ANIM_FRAME_COUNT;
    s_anim_hue = (s_anim_hue + 1) % 360;
    lv_color_t glow = anim_glow_color();

    if (s_home_glow) {
        lv_img_set_src(s_home_glow, &s_anim_glow_dsc[s_anim_idx]);
        tint_img_c(s_home_glow, glow);
    }
    if (s_home_core) {
        lv_img_set_src(s_home_core, &s_anim_core_dsc[s_anim_idx]);
    }
    if (s_anim_glow) {
        lv_img_set_src(s_anim_glow, &s_anim_glow_dsc[s_anim_idx]);
        tint_img_c(s_anim_glow, glow);
    }
    if (s_anim_core) {
        lv_img_set_src(s_anim_core, &s_anim_core_dsc[s_anim_idx]);
    }
}

/* ------------------------------------------------------------------ */
/* 页面 0：时钟 / 天气                                                 */
/* ------------------------------------------------------------------ */
static void build_clock_page(lv_obj_t *scr)
{
    s_lbl_date = make_label(scr, &lv_font_montserrat_16, UI_COLOR_DIM,
                            LV_ALIGN_TOP_MID, 0, 14);
    lv_label_set_text(s_lbl_date, "---- -- ----");

    s_lbl_time = make_label(scr, &lv_font_montserrat_48, UI_COLOR_TIME,
                            LV_ALIGN_CENTER, 0, -46);
    lv_label_set_recolor(s_lbl_time, true);
    lv_label_set_text(s_lbl_time, "--:--");

    s_lbl_sec = lv_label_create(scr);
    lv_obj_set_style_text_font(s_lbl_sec, &lv_font_montserrat_20, 0);
    lv_obj_set_style_text_color(s_lbl_sec, lv_color_hex(UI_COLOR_SEC), 0);
    lv_label_set_text(s_lbl_sec, "--");
    lv_obj_align_to(s_lbl_sec, s_lbl_time, LV_ALIGN_OUT_RIGHT_BOTTOM, 10, -6);

    lv_obj_t *line = lv_obj_create(scr);
    lv_obj_set_size(line, 208, 2);
    lv_obj_set_style_bg_color(line, lv_color_hex(0x30363D), 0);
    lv_obj_set_style_border_width(line, 0, 0);
    lv_obj_set_style_radius(line, 1, 0);
    lv_obj_set_style_pad_all(line, 0, 0);
    lv_obj_clear_flag(line, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_align(line, LV_ALIGN_CENTER, 0, -6);

    create_weather_icon(scr, &s_img_weather_cool, &s_img_weather_warm,
                        LV_ALIGN_CENTER, -54, 54);

    s_lbl_weather = make_label(scr, &lv_font_montserrat_28, UI_COLOR_TIME,
                               LV_ALIGN_CENTER, 28, 40);
    lv_label_set_text(s_lbl_weather, "--~-- C");

    s_lbl_humid = make_label(scr, &lv_font_montserrat_16, UI_COLOR_DIM,
                             LV_ALIGN_CENTER, 28, 72);
    lv_label_set_text(s_lbl_humid, "humidity --%");
}

/* ------------------------------------------------------------------ */
/* 页面 1：HOME（太空人 + 时间/天气）                                   */
/* ------------------------------------------------------------------ */
static void build_home_page(lv_obj_t *scr)
{
    /* 深蓝渐变背景（让霓虹元素更跳） */
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x0A1626), 0);
    lv_obj_set_style_bg_grad_color(scr, lv_color_black(), 0);
    lv_obj_set_style_bg_grad_dir(scr, LV_GRAD_DIR_VER, 0);

    /* 太空人：顶部 230x115 */
    create_anim_pair(scr, &s_home_glow, &s_home_core, LV_ALIGN_TOP_MID, 0, 0);

    /* 左：日期 + 星期 */
    s_home_lbl_date = make_label(scr, &lv_font_montserrat_16, 0xD0D0D0,
                                 LV_ALIGN_TOP_LEFT, 8, 40);
    lv_label_set_text(s_home_lbl_date, "--/--");

    s_home_lbl_week = make_label(scr, &lv_font_montserrat_14, UI_COLOR_SEC,
                                 LV_ALIGN_TOP_LEFT, 8, 60);
    lv_label_set_text(s_home_lbl_week, "---");

    /* 右：天气图标 + 天气文字 + 最高/最低 */
    create_weather_icon(scr, &s_home_img_weather_cool, &s_home_img_weather_warm,
                        LV_ALIGN_TOP_RIGHT, -8, 8);

    s_home_lbl_cond = lv_label_create(scr);
    lv_obj_set_style_text_font(s_home_lbl_cond, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(s_home_lbl_cond, lv_color_hex(0xB0BEC5), 0);
    lv_label_set_text(s_home_lbl_cond, "---");
    lv_obj_align(s_home_lbl_cond, LV_ALIGN_TOP_RIGHT, -8, 60);

    s_home_lbl_range = lv_label_create(scr);
    lv_obj_set_style_text_font(s_home_lbl_range, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(s_home_lbl_range, lv_color_hex(0xFFFFFF), 0);
    lv_label_set_text(s_home_lbl_range, "--/--");
    lv_obj_align(s_home_lbl_range, LV_ALIGN_TOP_RIGHT, -8, 78);

    /* 双色时间 */
    s_home_lbl_time = lv_label_create(scr);
    lv_label_set_recolor(s_home_lbl_time, true);
    lv_obj_set_style_text_font(s_home_lbl_time, &lv_font_montserrat_48, 0);
    lv_obj_set_style_text_color(s_home_lbl_time, lv_color_hex(0xFFFFFF), 0);
    lv_label_set_text(s_home_lbl_time, "#FFFFFF --#:#FF8A65 --#");
    lv_obj_align(s_home_lbl_time, LV_ALIGN_TOP_MID, 0, 112);

    s_home_lbl_sec = lv_label_create(scr);
    lv_obj_set_style_text_font(s_home_lbl_sec, &lv_font_montserrat_20, 0);
    lv_obj_set_style_text_color(s_home_lbl_sec, lv_color_hex(UI_COLOR_SEC), 0);
    lv_label_set_text(s_home_lbl_sec, "--");
    lv_obj_align_to(s_home_lbl_sec, s_home_lbl_time, LV_ALIGN_OUT_RIGHT_BOTTOM, 8, -6);

    /* 分隔线 */
    lv_obj_t *line = lv_obj_create(scr);
    lv_obj_set_size(line, 210, 1);
    lv_obj_set_style_bg_color(line, lv_color_hex(0x1E2A38), 0);
    lv_obj_set_style_border_width(line, 0, 0);
    lv_obj_set_style_radius(line, 0, 0);
    lv_obj_set_style_pad_all(line, 0, 0);
    lv_obj_clear_flag(line, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_align(line, LV_ALIGN_TOP_MID, 0, 170);

    /* 温度行 */
    s_home_img_thermo = lv_img_create(scr);
    lv_img_set_src(s_home_img_thermo, ui_icon_get(UI_ICON_THERMO));
    tint_img(s_home_img_thermo, 0xFF7043);
    lv_obj_align(s_home_img_thermo, LV_ALIGN_TOP_LEFT, 10, 174);

    s_home_bar_temp = make_bar(scr, 0xFF7043);
    lv_obj_align(s_home_bar_temp, LV_ALIGN_TOP_LEFT, 40, 180);

    s_home_lbl_temp = lv_label_create(scr);
    lv_obj_set_style_text_font(s_home_lbl_temp, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_color(s_home_lbl_temp, lv_color_hex(0xFFFFFF), 0);
    lv_label_set_text(s_home_lbl_temp, "--°C");
    lv_obj_align(s_home_lbl_temp, LV_ALIGN_TOP_LEFT, 164, 176);

    /* 湿度行 */
    s_home_img_drop = lv_img_create(scr);
    lv_img_set_src(s_home_img_drop, ui_icon_get(UI_ICON_DROP));
    tint_img(s_home_img_drop, 0x42A5F5);
    lv_obj_align(s_home_img_drop, LV_ALIGN_TOP_LEFT, 10, 198);

    s_home_bar_hum = make_bar(scr, 0x42A5F5);
    lv_obj_align(s_home_bar_hum, LV_ALIGN_TOP_LEFT, 40, 204);

    s_home_lbl_hum = lv_label_create(scr);
    lv_obj_set_style_text_font(s_home_lbl_hum, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_color(s_home_lbl_hum, lv_color_hex(0xFFFFFF), 0);
    lv_label_set_text(s_home_lbl_hum, "--%");
    lv_obj_align(s_home_lbl_hum, LV_ALIGN_TOP_LEFT, 164, 200);
}

/* ------------------------------------------------------------------ */
/* 页面 2：全屏动画                                                    */
/* ------------------------------------------------------------------ */
static void build_anim_page(lv_obj_t *scr)
{
    create_anim_pair(scr, &s_anim_glow, &s_anim_core, LV_ALIGN_CENTER, 0, -6);
}

/* ------------------------------------------------------------------ */
/* 页面 3：系统信息                                                    */
/* ------------------------------------------------------------------ */
static void build_sensor_page(lv_obj_t *scr)
{
    lv_obj_t *title = lv_label_create(scr);
    lv_obj_set_style_text_font(title, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(0x616161), 0);
    lv_label_set_text(title, "SYSTEM");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 8);

    s_lbl_temp  = make_label(scr, &lv_font_montserrat_28, 0xFFFFFF,
                             LV_ALIGN_TOP_MID, 0, 40);
    lv_label_set_text(s_lbl_temp, "T --.- C");

    s_lbl_accel = make_label(scr, &lv_font_montserrat_20, UI_COLOR_ACCENT,
                             LV_ALIGN_CENTER, 0, -20);
    lv_label_set_text(s_lbl_accel, "a -- -- --");

    s_lbl_lux   = make_label(scr, &lv_font_montserrat_20, UI_COLOR_SEC,
                             LV_ALIGN_CENTER, 0, 20);
    lv_label_set_text(s_lbl_lux, "lux -----");

    s_lbl_net   = make_label(scr, &lv_font_montserrat_14, UI_COLOR_DIM,
                             LV_ALIGN_CENTER, 0, 56);
    lv_label_set_text(s_lbl_net, "net offline");
}

/* ------------------------------------------------------------------ */
/* 页面 4：图片                                                        */
/* ------------------------------------------------------------------ */
#if CONFIG_PRISM_IMAGE_RES_HALF
#define UI_IMG_W     120
#define UI_IMG_H     120
#define UI_IMG_ZOOM  512    /* 2x 放大到 240x240 */
#else
#define UI_IMG_W     240
#define UI_IMG_H     240
#define UI_IMG_ZOOM  LV_IMG_ZOOM_NONE
#endif

#define IMG_BYTES (UI_IMG_W * UI_IMG_H * 2)

static void build_image_page(lv_obj_t *scr)
{
    s_canvas = lv_canvas_create(scr);
    lv_canvas_set_buffer(s_canvas, &s_dummy_px, 1, 1, LV_IMG_CF_TRUE_COLOR);
    lv_obj_align(s_canvas, LV_ALIGN_CENTER, 0, 0);
    lv_obj_add_flag(s_canvas, LV_OBJ_FLAG_HIDDEN);

    s_lbl_img_hint = make_label(scr, &lv_font_montserrat_14, 0x616161,
                                LV_ALIGN_CENTER, 0, 0);
    lv_label_set_text(s_lbl_img_hint, "no image\n\nupload over HTTP");
    lv_obj_set_style_text_align(s_lbl_img_hint, LV_TEXT_ALIGN_CENTER, 0);
}

/* ------------------------------------------------------------------ */
/* 初始化                                                              */
/* ------------------------------------------------------------------ */
esp_err_t ui_init(void)
{
    if (!lvgl_port_lock(0)) {
        return ESP_FAIL;
    }

    anim_assets_init();
    s_anim_hue = 190;   /* 初始青色，之后缓慢变色 */

    for (int i = 0; i < UI_PAGE_MAX; i++) {
        s_scr[i] = make_screen();
    }
    build_clock_page(s_scr[UI_PAGE_CLOCK]);
    build_home_page(s_scr[UI_PAGE_HOME]);
    build_anim_page(s_scr[UI_PAGE_ANIM]);
    build_sensor_page(s_scr[UI_PAGE_SENSOR]);
    build_image_page(s_scr[UI_PAGE_IMAGE]);

    lv_scr_load(s_scr[UI_PAGE_CLOCK]);
    s_page = UI_PAGE_CLOCK;

    /* 约 12fps -> 20 帧 ≈ 1.67s 一循环；色相每帧 +1° */
    s_anim_timer = lv_timer_create(anim_tick_cb, 83, NULL);
    lv_timer_pause(s_anim_timer);   /* 非动画页时暂停，省 CPU */

    /* 顶层状态栏 */
    s_lbl_status = lv_label_create(lv_layer_top());
    lv_obj_set_style_text_font(s_lbl_status, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(s_lbl_status, lv_color_hex(0x616161), 0);
    lv_label_set_text(s_lbl_status, "booting...");
    lv_obj_align(s_lbl_status, LV_ALIGN_BOTTOM_MID, 0, -6);

    lvgl_port_unlock();

    ESP_LOGI(TAG, "UI ready (%d pages)", UI_PAGE_MAX);
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* 翻页                                                                */
/* ------------------------------------------------------------------ */
void ui_set_page(ui_page_t page)
{
    if (page >= UI_PAGE_MAX) {
        return;
    }
    if (!lvgl_port_lock(0)) {
        return;
    }
    if (page != s_page) {
        lv_scr_load_anim(s_scr[page], LV_SCR_LOAD_ANIM_MOVE_LEFT, 200, 0, false);
        s_page = page;
    }
    /* HOME / ANIM 页需要播放动画，其它页暂停以省 CPU */
    if (s_anim_timer) {
        if (s_page == UI_PAGE_ANIM || s_page == UI_PAGE_HOME) {
            lv_timer_resume(s_anim_timer);
        } else {
            lv_timer_pause(s_anim_timer);
        }
    }
    /* HOME / 动画页隐藏底部状态栏，保持画面干净 */
    if (s_lbl_status) {
        if (s_page == UI_PAGE_HOME || s_page == UI_PAGE_ANIM) {
            lv_obj_add_flag(s_lbl_status, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_clear_flag(s_lbl_status, LV_OBJ_FLAG_HIDDEN);
        }
    }
    lvgl_port_unlock();
}

void ui_next_page(void)
{
    ui_set_page((ui_page_t)((s_page + 1) % UI_PAGE_MAX));
}

void ui_prev_page(void)
{
    ui_set_page((ui_page_t)((s_page + UI_PAGE_MAX - 1) % UI_PAGE_MAX));
}

ui_page_t ui_get_page(void)
{
    return s_page;
}

/* ------------------------------------------------------------------ */
/* 时间 / 日期 / 天气（同时更新 CLOCK 与 HOME 两页）                    */
/* ------------------------------------------------------------------ */
/* "17:53" -> 时白、分橙（LVGL label recolor 语法） */
static void set_two_tone_time(lv_obj_t *lbl, const char *hhmm)
{
    const char *c = strchr(hhmm, ':');
    if (c && (size_t)(c - hhmm) <= 2) {
        char hh[3] = {0};
        size_t n = (size_t)(c - hhmm);
        memcpy(hh, hhmm, n);
        hh[n] = '\0';
        lv_label_set_text_fmt(lbl, "#FFFFFF %s#:#FF8A65 %s#", hh, c + 1);
    } else {
        lv_label_set_text(lbl, hhmm);
    }
}

void ui_set_time(const char *hhmm)
{
    if (!hhmm) return;
    if (!lvgl_port_lock(0)) return;
    if (s_lbl_time) {
        set_two_tone_time(s_lbl_time, hhmm);
        lv_obj_align_to(s_lbl_sec, s_lbl_time, LV_ALIGN_OUT_RIGHT_BOTTOM, 10, -6);
    }
    if (s_home_lbl_time) {
        set_two_tone_time(s_home_lbl_time, hhmm);
        lv_obj_align_to(s_home_lbl_sec, s_home_lbl_time, LV_ALIGN_OUT_RIGHT_BOTTOM, 8, -6);
    }
    lvgl_port_unlock();
}

void ui_set_seconds(const char *ss)
{
    if (!ss) return;
    if (!lvgl_port_lock(0)) return;
    if (s_lbl_sec) {
        lv_label_set_text(s_lbl_sec, ss);
    }
    if (s_home_lbl_sec) {
        lv_label_set_text(s_home_lbl_sec, ss);
    }
    lvgl_port_unlock();
}

void ui_set_date(const char *date)
{
    if (!date) return;
    if (!lvgl_port_lock(0)) return;
    if (s_lbl_date) {
        lv_label_set_text(s_lbl_date, date);
    }
    if (s_home_lbl_date) {
        /* "10/19 Mon" -> 左侧 "10/19"，右侧 "Mon" */
        const char *sp = strrchr(date, ' ');
        if (sp && sp[1] != '\0') {
            char d[24];
            size_t n = (size_t)(sp - date);
            if (n >= sizeof(d)) {
                n = sizeof(d) - 1;
            }
            memcpy(d, date, n);
            d[n] = '\0';
            lv_label_set_text(s_home_lbl_date, d);
            if (s_home_lbl_week) {
                lv_label_set_text(s_home_lbl_week, sp + 1);
            }
        } else {
            lv_label_set_text(s_home_lbl_date, date);
            if (s_home_lbl_week) {
                lv_label_set_text(s_home_lbl_week, "");
            }
        }
    }
    lvgl_port_unlock();
}

void ui_set_weather(int icon_id, const char *text, int cur_c, int low, int high, int humidity)
{
    if (!lvgl_port_lock(0)) return;

    const lv_img_dsc_t *iw = weather_icon_warm(icon_id);
    const lv_img_dsc_t *ic = weather_icon_cool(icon_id);
    if (s_img_weather_cool) {
        lv_img_set_src(s_img_weather_cool, ic);
    }
    if (s_img_weather_warm) {
        lv_img_set_src(s_img_weather_warm, iw);
    }
    if (s_home_img_weather_cool) {
        lv_img_set_src(s_home_img_weather_cool, ic);
    }
    if (s_home_img_weather_warm) {
        lv_img_set_src(s_home_img_weather_warm, iw);
    }

    /* 时钟页：温度区间 + 湿度 */
    if (s_lbl_weather) {
        lv_label_set_text_fmt(s_lbl_weather, "%d~%d C", low, high);
    }
    if (s_lbl_humid) {
        if (humidity >= 0) {
            lv_label_set_text_fmt(s_lbl_humid, "humidity %d%%", humidity);
        } else {
            lv_label_set_text(s_lbl_humid, "humidity --%");
        }
    }

    /* HOME 页：天气文字 / 最高最低 / 当前温度湿度 / 进度条 */
    if (s_home_lbl_cond) {
        lv_label_set_text(s_home_lbl_cond, (text && text[0]) ? text : "---");
    }
    if (s_home_lbl_range) {
        lv_label_set_text_fmt(s_home_lbl_range, "%d°/%d°", high, low);
    }
    if (s_home_lbl_temp) {
        if (cur_c > -100) {
            lv_label_set_text_fmt(s_home_lbl_temp, "%d°C", cur_c);
        } else {
            lv_label_set_text(s_home_lbl_temp, "--°C");
        }
    }
    if (s_home_lbl_hum) {
        if (humidity >= 0) {
            lv_label_set_text_fmt(s_home_lbl_hum, "%d%%", humidity);
        } else {
            lv_label_set_text(s_home_lbl_hum, "--%");
        }
    }
    if (s_home_bar_temp) {
        int pct = 0;
        if (cur_c > -100) {
            pct = (cur_c + 10) * 100 / 50;   /* -10..40°C -> 0..100 */
            if (pct < 0) pct = 0;
            if (pct > 100) pct = 100;
        }
        lv_bar_set_value(s_home_bar_temp, pct, LV_ANIM_ON);
    }
    if (s_home_bar_hum) {
        int pct = (humidity < 0) ? 0 : (humidity > 100 ? 100 : humidity);
        lv_bar_set_value(s_home_bar_hum, pct, LV_ANIM_ON);
    }

    lvgl_port_unlock();
}

/* ------------------------------------------------------------------ */
/* 页面 3：系统                                                        */
/* ------------------------------------------------------------------ */
void ui_set_imu(float temp_c, float ax, float ay, float az)
{
    if (!lvgl_port_lock(0)) return;
    if (s_lbl_temp) {
        lv_label_set_text_fmt(s_lbl_temp, "T %.1f C", temp_c);
    }
    if (s_lbl_accel) {
        lv_label_set_text_fmt(s_lbl_accel, "a %+.2f %+.2f %+.2f g", ax, ay, az);
    }
    lvgl_port_unlock();
}

void ui_set_lux(float lux)
{
    if (!lvgl_port_lock(0)) return;
    if (s_lbl_lux) {
        lv_label_set_text_fmt(s_lbl_lux, "lux %.0f", lux);
    }
    lvgl_port_unlock();
}

void ui_set_net_info(const char *ip, int rssi, bool online)
{
    if (!lvgl_port_lock(0)) return;
    if (s_lbl_net) {
        if (online && ip) {
            lv_label_set_text_fmt(s_lbl_net, "%s  %d dBm", ip, rssi);
        } else {
            lv_label_set_text(s_lbl_net, "net offline");
        }
    }
    lvgl_port_unlock();
}

/* ------------------------------------------------------------------ */
/* 页面 4：图片                                                        */
/* ------------------------------------------------------------------ */
size_t ui_image_capacity(void)
{
    return s_img_buf ? IMG_BYTES : 0;
}

uint32_t ui_image_width(void)
{
    return UI_IMG_W;
}

uint32_t ui_image_height(void)
{
    return UI_IMG_H;
}

uint8_t *ui_image_alloc(void)
{
    if (s_img_buf) {
        free(s_img_buf);
        s_img_buf = NULL;
    }

    s_img_buf = heap_caps_malloc(IMG_BYTES, MALLOC_CAP_SPIRAM);
    if (!s_img_buf) {
        s_img_buf = heap_caps_malloc(IMG_BYTES, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    }
    if (!s_img_buf) {
        ESP_LOGW(TAG, "图片缓冲分配失败（%d 字节），剩余内部堆 %u",
                 (int)IMG_BYTES, (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
        return NULL;
    }
    memset(s_img_buf, 0, IMG_BYTES);
    ESP_LOGI(TAG, "图片缓冲已分配: %d 字节", (int)IMG_BYTES);
    return s_img_buf;
}

esp_err_t ui_image_commit(void)
{
    if (!s_img_buf) {
        return ESP_ERR_INVALID_STATE;
    }
    if (!lvgl_port_lock(0)) {
        return ESP_FAIL;
    }
    lv_canvas_set_buffer(s_canvas, s_img_buf, UI_IMG_W, UI_IMG_H,
                         LV_IMG_CF_TRUE_COLOR);
    lv_obj_clear_flag(s_canvas, LV_OBJ_FLAG_HIDDEN);
#if (UI_IMG_W != BOARD_LCD_H_RES)
    lv_img_set_zoom(s_canvas, UI_IMG_ZOOM);
#endif
    lv_obj_align(s_canvas, LV_ALIGN_CENTER, 0, 0);
    if (s_lbl_img_hint) {
        lv_obj_add_flag(s_lbl_img_hint, LV_OBJ_FLAG_HIDDEN);
    }
    lv_obj_invalidate(s_canvas);
    lvgl_port_unlock();

    ui_set_page(UI_PAGE_IMAGE);
    return ESP_OK;
}

void ui_image_release(void)
{
    if (s_img_buf) {
        free(s_img_buf);
        s_img_buf = NULL;
    }

    if (lvgl_port_lock(0)) {
        if (s_canvas) {
            lv_canvas_set_buffer(s_canvas, &s_dummy_px, 1, 1, LV_IMG_CF_TRUE_COLOR);
            lv_obj_add_flag(s_canvas, LV_OBJ_FLAG_HIDDEN);
        }
        if (s_lbl_img_hint) {
            lv_obj_clear_flag(s_lbl_img_hint, LV_OBJ_FLAG_HIDDEN);
        }
        lvgl_port_unlock();
    }
}

/* ------------------------------------------------------------------ */
/* 通用                                                                */
/* ------------------------------------------------------------------ */
void ui_set_status(const char *text)
{
    if (!text || !s_lbl_status) return;
    if (lvgl_port_lock(0)) {
        lv_label_set_text(s_lbl_status, text);
        lvgl_port_unlock();
    }
}

void ui_toast(const char *text)
{
    if (!text) return;
    if (!lvgl_port_lock(0)) return;

    if (s_toast) {
        lv_obj_del(s_toast);
        s_toast = NULL;
    }
    if (s_toast_timer) {
        lv_timer_del(s_toast_timer);
        s_toast_timer = NULL;
    }

    s_toast = lv_label_create(lv_layer_top());
    lv_obj_set_style_text_font(s_toast, &lv_font_montserrat_20, 0);
    lv_obj_set_style_text_color(s_toast, lv_color_hex(UI_COLOR_SEC), 0);
    lv_obj_set_style_bg_color(s_toast, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(s_toast, LV_OPA_70, 0);
    lv_obj_set_style_pad_all(s_toast, 6, 0);
    lv_label_set_text(s_toast, text);
    lv_obj_align(s_toast, LV_ALIGN_BOTTOM_MID, 0, -34);

    lvgl_port_unlock();

    s_toast_timer = lv_timer_create(toast_hide_cb, 2000, NULL);
}
