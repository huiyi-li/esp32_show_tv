#pragma once

/**
 * @file  ui.h
 * @brief LVGL 界面：时钟 / 动画 / 系统信息 / 图片
 *
 * 页面：
 *   0 CLOCK  大号时间 + 秒 + 日期 + 天气图标/温度/湿度
 *   1 ANIM   内置分帧动画（tools/frames，自绘/内置）
 *   2 SENSOR 温度 / 加速度 / 环境光 / 网络
 *   3 IMAGE  通过 HTTP 上传的图片
 *
 * 翻页来源：按键（调试模式 D2/D15）或触摸条 / 摇一摇（完整模式）。
 */

#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    UI_PAGE_CLOCK = 0,
    UI_PAGE_HOME,       /* 太空人动画 + 时间/天气 同屏 */
    UI_PAGE_ANIM,       /* 全屏动画 */
    UI_PAGE_SENSOR,
    UI_PAGE_IMAGE,
    UI_PAGE_MAX,
} ui_page_t;

/** 创建全部页面（含顶层状态栏） */
esp_err_t ui_init(void);

/** 页面切换 */
void ui_next_page(void);
void ui_prev_page(void);
void ui_set_page(ui_page_t page);
ui_page_t ui_get_page(void);

/* ---------------- 页面 0：时钟 / 天气 ---------------- */

/** 更新时间（大号），如 "14:05" */
void ui_set_time(const char *hhmm);

/** 更新秒（小号，跟在时间右侧），如 "07" */
void ui_set_seconds(const char *ss);

/** 更新日期，如 "2026-10-19 Sat" */
void ui_set_date(const char *date);

/** 更新天气：图标 id（weather_icon_t）、天气文字、当前温度、
 *  今日最高/最低、湿度(%)。cur_c < -100 表示无效。 */
void ui_set_weather(int icon_id, const char *text, int cur_c, int low, int high, int humidity);

/* ---------------- 页面 2：系统 / 传感器 ---------------- */

/** 更新姿态与温度（来自 MPU6050） */
void ui_set_imu(float temp_c, float ax, float ay, float az);

/** 更新环境光读数（lux） */
void ui_set_lux(float lux);

/** 更新网络信息（IP / RSSI / 是否联网） */
void ui_set_net_info(const char *ip, int rssi, bool online);

/* ---------------- 页面 3：图片 ---------------- */

/** 为图片页分配 RGB565 缓冲，返回可写指针；失败返回 NULL。
 *  重复调用会释放旧缓冲。缓冲由 UI 持有，调用方不要 free。 */
uint8_t *ui_image_alloc(void);

/** 缓冲容量（字节）；未分配时为 0 */
size_t ui_image_capacity(void);

/** 图片缓冲的宽 / 高（分辨率由 Kconfig PRISM_IMAGE_RES 决定） */
uint32_t ui_image_width(void);
uint32_t ui_image_height(void);

/** 提交缓冲并切到图片页（需先 ui_image_alloc） */
esp_err_t ui_image_commit(void);

/** 释放图片缓冲，图片页回到占位提示 */
void ui_image_release(void);

/* ---------------- 通用 ---------------- */

/** 底部状态栏（浮在最上层，全页面可见） */
void ui_set_status(const char *text);

/** 屏幕中央弹出提示 2 秒 */
void ui_toast(const char *text);

#ifdef __cplusplus
}
#endif
