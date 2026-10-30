#pragma once

/**
 * @file  input.h
 * @brief 输入抽象：翻页 / 背光开关
 *
 * 两种实现，接口一致（由 Kconfig PRISM_DEBUG_LCD_ONLY 选择）：
 *   - 正常模式：ESP32 电容触摸条（Touch T0 = GPIO4），短按翻页 / 长按开关背光；
 *   - 调试模式：两个普通 GPIO 按键（默认 D2=下一页、D15=上一页），
 *               短按翻页 / 长按开关背光。
 *
 * 采用轮询方式（约 50Hz 调用 input_poll()），不占用中断，逻辑简单、抗干扰好。
 */

#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    INPUT_EVT_NONE = 0,
    INPUT_EVT_TAP,      /* 下一页（按键1 短按 / 触摸条短按） */
    INPUT_EVT_PREV,     /* 上一页（按键2 短按；仅调试双键模式会产生） */
    INPUT_EVT_LONG,     /* 长按：开关背光 */
} input_event_t;

/** 初始化输入源（触摸条或调试按键）。失败时 input_available() 返回 false，不影响其它功能 */
esp_err_t input_init(void);

/** 输入源是否可用 */
bool input_available(void);

/** 周期调用（建议 20~50Hz），返回本周期产生的按键事件 */
input_event_t input_poll(void);

/** 当前是否有输入按下（任意按键 / 触摸条） */
bool input_is_pressed(void);

/** 最近一次读取的原始计数（触摸：计数；按键：0） */
uint16_t input_get_raw(void);

/** 基线值（触摸：未触摸计数；按键：0） */
uint16_t input_get_baseline(void);

#ifdef __cplusplus
}
#endif
