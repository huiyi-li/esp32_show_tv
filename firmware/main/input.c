/**
 * @file  input.c
 * @brief 输入源轮询驱动
 *
 * 由 Kconfig PRISM_DEBUG_LCD_ONLY 切换实现：
 *
 *  ── 正常模式：电容触摸条（ESP32 Touch 外设，T0 = GPIO4）──
 *    1. 上电采一段“未触摸”原始计数作为基线 baseline；
 *    2. 周期读取滤波后的计数，count < baseline × 阈值% 判定按下；
 *    3. 未按下时缓慢跟踪基线，适应温漂。
 *
 *  ── 调试模式：两个普通 GPIO 按键（按下接 GND）──
 *    KEY1 = 下一页（默认 GPIO2 / D2）
 *    KEY2 = 上一页（默认 GPIO15 / D15，可设 <0 关闭）
 *    硬件去抖。
 *
 * 两者共用同一套“按下沿/抬起沿/长按”事件逻辑。
 */

#include "input.h"
#include "board_config.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "driver/touch_pad.h"
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "input";

/* 初始化失败（未接焊盘 / 按键损坏）时为 false，所有读取返回“未按下” */
static bool s_ready   = false;
static bool s_pressed = false;

/* 单个输入源的按键状态 */
typedef struct {
    bool    down;        /* 上一周期按下状态（用于边沿检测） */
    bool    long_sent;   /* 长按只上报一次 */
    int64_t press_us;
    bool    stable;      /* 去抖后稳定状态（仅 GPIO 按键用） */
    bool    cand;
    int64_t cand_us;
} key_ctx_t;

#if CONFIG_PRISM_DEBUG_LCD_ONLY
/* ---------------- 调试按键 ---------------- */
#if CONFIG_PRISM_DEBUG_KEY2_GPIO >= 0
#define KEY_COUNT 2
#else
#define KEY_COUNT 1
#endif

static const int s_key_pin[KEY_COUNT] = {
    CONFIG_PRISM_DEBUG_KEY_GPIO,
#if KEY_COUNT > 1
    CONFIG_PRISM_DEBUG_KEY2_GPIO,
#endif
};

static key_ctx_t s_key[KEY_COUNT];

static input_event_t key_tap_event(size_t i)
{
    return (i == 0) ? INPUT_EVT_TAP : INPUT_EVT_PREV;
}

static bool hw_now(size_t i)
{
    const bool raw = (gpio_get_level((gpio_num_t)s_key_pin[i]) == 0);
    key_ctx_t *k = &s_key[i];
    const int64_t t = esp_timer_get_time();

    if (raw != k->cand) {
        k->cand = raw;
        k->cand_us = t;
    } else if (raw != k->stable &&
               (t - k->cand_us) >= (int64_t)BOARD_KEY_DEBOUNCE_MS * 1000) {
        k->stable = raw;
    }
    return k->stable;
}

#else
/* ---------------- 触摸条 ---------------- */
#define KEY_COUNT 1

static key_ctx_t s_key[KEY_COUNT];
static uint16_t s_raw       = 0;
static uint32_t s_baseline  = 0;
static uint32_t s_threshold = 0;   /* 触发计数（低于此值算按下） */

static input_event_t key_tap_event(size_t i)
{
    (void)i;
    return INPUT_EVT_TAP;
}

static bool hw_now(size_t i)
{
    (void)i;
    uint16_t v = 0;
    if (touch_pad_read_filtered(BOARD_TOUCH_PAD, &v) != ESP_OK || v == 0) {
        return s_key[0].down;   /* 读失败保持原态，避免误触发 */
    }
    s_raw = v;

    const bool now = (s_threshold > 0) && ((uint32_t)v < s_threshold);

    if (!now) {
        /* 未按下：缓慢跟踪基线，重算阈值，适应温漂 */
        s_baseline = (s_baseline * 63u + v) / 64u;
        if (s_baseline > 0) {
            s_threshold = s_baseline * (uint32_t)CONFIG_PRISM_TOUCH_THRESHOLD / 100u;
        }
    }
    return now;
}
#endif /* CONFIG_PRISM_DEBUG_LCD_ONLY */

/* ------------------------------------------------------------------ */
/* 初始化                                                              */
/* ------------------------------------------------------------------ */
esp_err_t input_init(void)
{
#if CONFIG_PRISM_DEBUG_LCD_ONLY
    for (size_t i = 0; i < KEY_COUNT; i++) {
        gpio_config_t cfg = {
            .pin_bit_mask = 1ULL << (uint32_t)s_key_pin[i],
            .mode         = GPIO_MODE_INPUT,
            .pull_up_en   = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type    = GPIO_INTR_DISABLE,
        };
        esp_err_t err = gpio_config(&cfg);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "调试按键 GPIO%d 配置失败: %s",
                     s_key_pin[i], esp_err_to_name(err));
            return err;
        }
        const bool pressed = (gpio_get_level((gpio_num_t)s_key_pin[i]) == 0);
        s_key[i].stable = pressed;
        /* 上电已经是低电平：视为“启动前就按着”，先抑制事件，
         * 等松开后再正常响应，避免开机就触发长按关背光。 */
        s_key[i].down      = pressed;
        s_key[i].long_sent = pressed;
        ESP_LOGI(TAG, "  KEY%u GPIO%d 上电电平=%s",
                 (unsigned)i, (int)s_key_pin[i], pressed ? "LOW" : "HIGH");
    }
    s_ready = true;
#if KEY_COUNT > 1
    ESP_LOGI(TAG, "调试按键就绪: GPIO%d=下一页, GPIO%d=上一页（长按 D%ld 切换显示方向）",
             (int)s_key_pin[0], (int)s_key_pin[1], (long)s_key_pin[0]);
#else
    ESP_LOGI(TAG, "调试按键就绪: GPIO%d=下一页（长按切换显示方向）", (int)s_key_pin[0]);
#endif
#else
    esp_err_t err = touch_pad_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "touch_pad_init 失败: %s（触摸功能关闭）", esp_err_to_name(err));
        return err;
    }

    touch_pad_set_fsm_mode(TOUCH_FSM_MODE_TIMER);
    /* 参考高压 2.7V / 低压 0.5V / 衰减 1V，适合 3.3V 供电与外部铜箔 */
    touch_pad_set_voltage(TOUCH_HVOLT_2V7, TOUCH_LVOLT_0V5, TOUCH_HVOLT_ATTEN_1V);
    touch_pad_config(BOARD_TOUCH_PAD, 0);
    touch_pad_filter_start(20);     /* IIR 滤波周期 20ms */

    s_ready = true;

    /* 采集基线：读 16 次取平均 */
    vTaskDelay(pdMS_TO_TICKS(200));
    uint32_t acc = 0;
    int n = 0;
    for (int i = 0; i < 16; i++) {
        uint16_t v = 0;
        if (touch_pad_read_filtered(BOARD_TOUCH_PAD, &v) == ESP_OK && v > 0) {
            acc += v;
            n++;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    if (n > 0) {
        s_baseline = acc / (uint32_t)n;
    }

    if (s_baseline < 10) {
        ESP_LOGW(TAG, "触摸基线异常(%u)，触摸条可能未焊接，已关闭触摸输入", (unsigned)s_baseline);
        s_ready = false;
        return ESP_ERR_NOT_FOUND;
    }

    s_threshold = s_baseline * (uint32_t)CONFIG_PRISM_TOUCH_THRESHOLD / 100u;
    ESP_LOGI(TAG, "触摸条就绪: pad=%d baseline=%u threshold=%u",
             (int)BOARD_TOUCH_PAD, (unsigned)s_baseline, (unsigned)s_threshold);
#endif

    return ESP_OK;
}

bool input_available(void)
{
    return s_ready;
}

uint16_t input_get_raw(void)
{
#if CONFIG_PRISM_DEBUG_LCD_ONLY
    return 0;
#else
    return s_raw;
#endif
}

uint16_t input_get_baseline(void)
{
#if CONFIG_PRISM_DEBUG_LCD_ONLY
    return 0;
#else
    return (uint16_t)s_baseline;
#endif
}

bool input_is_pressed(void)
{
    return s_pressed;
}

/* ------------------------------------------------------------------ */
/* 单个输入源的事件逻辑                                                */
/* ------------------------------------------------------------------ */
static input_event_t key_step(key_ctx_t *k, bool now, int64_t t,
                              input_event_t tap_evt, int64_t long_ms, int64_t min_ms)
{
    input_event_t evt = INPUT_EVT_NONE;

    if (now && !k->down) {
        /* 按下沿 */
        k->down      = true;
        k->long_sent = false;
        k->press_us  = t;
    } else if (now && k->down) {
        /* 保持按下：到达长按阈值只报一次 */
        if (!k->long_sent && (t - k->press_us) >= long_ms * 1000) {
            k->long_sent = true;
            evt = INPUT_EVT_LONG;
        }
    } else if (!now && k->down) {
        /* 抬起沿 */
        k->down = false;
        int64_t dur_ms = (t - k->press_us) / 1000;
        if (!k->long_sent && dur_ms >= min_ms) {
            evt = tap_evt;
        }
        k->long_sent = false;
    }

    return evt;
}

input_event_t input_poll(void)
{
    if (!s_ready) {
        return INPUT_EVT_NONE;
    }

    const int64_t t = esp_timer_get_time();
    input_event_t evt = INPUT_EVT_NONE;
    bool any = false;

#if CONFIG_PRISM_DEBUG_LCD_ONLY
    const int64_t long_ms = BOARD_KEY_LONG_MS;
    const int64_t min_ms  = BOARD_KEY_DEBOUNCE_MS;
#else
    const int64_t long_ms = BOARD_TOUCH_LONG_MS;
    const int64_t min_ms  = BOARD_TOUCH_DEBOUNCE_MS;
#endif

    for (size_t i = 0; i < KEY_COUNT; i++) {
        const bool now = hw_now(i);
        if (now) {
            any = true;
        }
        input_event_t e = key_step(&s_key[i], now, t, key_tap_event(i), long_ms, min_ms);
        if (e != INPUT_EVT_NONE && evt == INPUT_EVT_NONE) {
            evt = e;
        }
    }

    s_pressed = any;
    return evt;
}
