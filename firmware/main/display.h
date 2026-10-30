#pragma once

/**
 * @file  display.h
 * @brief ST7789 (1.3" 240x240) + LVGL 显示层
 */

#include "esp_err.h"
#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

/** 初始化 SPI / esp_lcd / LVGL 移植层，并点亮背光 */
esp_err_t display_init(void);

/** 取 LVGL 显示对象（用于旋转等操作） */
lv_disp_t *display_get(void);

/** 设置背光亮度 0~100 (%) */
void display_set_backlight(uint8_t percent);

/** 读取当前背光亮度 (%) */
uint8_t display_get_backlight(void);

/** 设置显示旋转：0 / 90 / 180 / 270 */
void display_set_rotation(uint16_t degree);

/** 循环切换显示方向（0 正常 / 1 左右镜像 / 2 上下镜像 / 3 180°反序） */
void display_cycle_orientation(void);

/** 当前显示方向序号 */
int display_get_orientation(void);

#ifdef __cplusplus
}
#endif
