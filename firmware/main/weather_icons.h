#pragma once

/**
 * @file  weather_icons.h
 * @brief 自绘天气图标（双层 alpha 蒙版，48x48）
 *
 * 每个图标拆成两层：
 *   - warm 层：太阳 / 闪电 -> 显示为黄色
 *   - cool 层：云 / 雨 / 雪 / 雾 / 霾条 -> 显示为蓝色
 * 数据由 tools/make_assets.py 生成，嵌入为 weather_icons.bin。
 */

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    WICON_SUN = 0,      /* 晴 */
    WICON_SUN_CLOUD,    /* 多云 */
    WICON_CLOUD,        /* 阴 */
    WICON_RAIN,         /* 雨 / 雨夹雪 */
    WICON_THUNDER,      /* 雷阵雨 */
    WICON_SNOW,         /* 雪 */
    WICON_FOG,          /* 雾 */
    WICON_HAZE,         /* 霾 / 沙尘 */
    WICON_COUNT
} weather_icon_t;

/** 太阳/闪电层（建议黄色） */
const lv_img_dsc_t *weather_icon_warm(int id);

/** 云/雨/雪/雾层（建议蓝色） */
const lv_img_dsc_t *weather_icon_cool(int id);

#ifdef __cplusplus
}
#endif
