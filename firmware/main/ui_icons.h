#pragma once

/**
 * @file  ui_icons.h
 * @brief 界面小图标（温度计 / 水滴），24x24 alpha 蒙版
 *
 * 数据由 tools/make_assets.py 生成，嵌入为 ui_icons.bin。
 */

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    UI_ICON_THERMO = 0,
    UI_ICON_DROP,
    UI_ICON_COUNT
} ui_icon_t;

const lv_img_dsc_t *ui_icon_get(int id);

#ifdef __cplusplus
}
#endif
