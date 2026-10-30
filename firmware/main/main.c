/**
 * @file  main.c
 * @brief 棱镜小电视 方案二 主程序（ESP-IDF v5.5+）
 *
 * 有两条启动路径，由 Kconfig `PRISM_DEBUG_LCD_ONLY` 选择：
 *
 * ── 调试模式（默认）─────────────────────────────────────────────
 *   只测 LCD 显示：
 *     display -> ui -> （可选传感器读数）-> 按键
 *   不做棱镜光路校正、不依赖触摸条/MPU6050 手势，也不启动 WiFi/HTTP/网络任务，
 *   开机直接进 UI，方便反复复位点屏。翻页/背光用按键（默认 GPIO0 = BOOT 键）。
 *
 * ── 完整模式 ────────────────────────────────────────────────────
 *   NVS -> 显示 -> UI -> 传感器 -> 触摸 -> WiFi/配网 -> HTTP -> 网络任务 -> 传感器任务
 */

#include <math.h>
#include <string.h>

#include "esp_log.h"
#include "esp_err.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "board_config.h"
#include "display.h"
#include "sensors.h"
#include "input.h"
#include "ui.h"

/* 是否需要联网（NTP 时间 / 天气 / OTA / 网页）。
 * 仅当“调试模式 + 纯点屏(不联网)”时才关闭。 */
#if CONFIG_PRISM_DEBUG_LCD_ONLY && CONFIG_PRISM_DEBUG_NO_NET
#define PRISM_NET_ENABLED 0
#else
#define PRISM_NET_ENABLED 1
#endif

/* 是否初始化 I2C 传感器（调试模式默认关闭，当前没接设备） */
#if CONFIG_PRISM_DEBUG_LCD_ONLY && CONFIG_PRISM_DEBUG_NO_SENSORS
#define PRISM_SENSORS_ENABLED 0
#else
#define PRISM_SENSORS_ENABLED 1
#endif

#if PRISM_NET_ENABLED
#include "wifi_prov.h"
#include "net_task.h"
#include "web_server.h"
#endif

static const char *TAG = "app";

/* 任务名（调试模式下语义不同） */
#if CONFIG_PRISM_DEBUG_LCD_ONLY
#define PRISM_INPUT_TASK_NAME "keys"
#else
#define PRISM_INPUT_TASK_NAME "sensors"
#endif

/* ------------------------------------------------------------------ */
/* 页面名（调试提示用）                                                 */
/* ------------------------------------------------------------------ */
#if CONFIG_PRISM_DEBUG_LCD_ONLY
static const char *page_name(ui_page_t p)
{
    switch (p) {
    case UI_PAGE_CLOCK:  return "Clock";
    case UI_PAGE_HOME:   return "Home";
    case UI_PAGE_ANIM:   return "Anim";
    case UI_PAGE_SENSOR: return "System";
    case UI_PAGE_IMAGE:  return "Image";
    default:             return "?";
    }
}
#endif

#if !CONFIG_PRISM_DEBUG_LCD_ONLY
/* ------------------------------------------------------------------ */
/* 环境光 -> 背光百分比（对数映射，并受 Kconfig 上下限约束）              */
/* ------------------------------------------------------------------ */
static uint8_t lux_to_backlight(float lux)
{
    if (lux < BOARD_LUX_DARK) {
        lux = BOARD_LUX_DARK;
    }
    if (lux > BOARD_LUX_BRIGHT) {
        lux = BOARD_LUX_BRIGHT;
    }

    /* log 映射 */
    float t = (logf(lux) - logf(BOARD_LUX_DARK)) /
              (logf(BOARD_LUX_BRIGHT) - logf(BOARD_LUX_DARK));

    int lo = CONFIG_PRISM_BL_MIN_PERCENT;
    int hi = CONFIG_PRISM_BL_MAX_PERCENT;
    int pct = lo + (int)(t * (hi - lo) + 0.5f);

    if (pct < 0)   pct = 0;
    if (pct > 100) pct = 100;
    return (uint8_t)pct;
}
#endif

/* ------------------------------------------------------------------ */
/* 传感器 / 交互 / 电源 任务                                            */
/* ------------------------------------------------------------------ */
static void sensor_task(void *arg)
{
    (void)arg;

    int tick = 0;

#if CONFIG_PRISM_DEBUG_LCD_ONLY
    /* ---------------- 调试：按键翻页 + 固定背光 ---------------- */
    uint8_t bl = CONFIG_PRISM_DEBUG_BACKLIGHT;
    display_set_backlight(bl);

    for (;;) {
        input_event_t ev = input_poll();

        if (ev == INPUT_EVT_TAP) {
            ui_next_page();
            ui_toast(page_name(ui_get_page()));
            ESP_LOGI(TAG, "下一页 -> %s", page_name(ui_get_page()));
        } else if (ev == INPUT_EVT_PREV) {
            ui_prev_page();
            ui_toast(page_name(ui_get_page()));
            ESP_LOGI(TAG, "上一页 -> %s", page_name(ui_get_page()));
        } else if (ev == INPUT_EVT_LONG) {
            /* 调试模式：长按循环切换 LCD 显示方向，对着棱镜调 */
            static const char *const orient_str[4] = {
                "Normal", "Mirror X", "Mirror Y", "Rot 180"
            };
            display_cycle_orientation();
            int o = display_get_orientation() & 3;
            ui_toast(orient_str[o]);
            ESP_LOGI(TAG, "长按 -> 显示方向 %d (%s)", o, orient_str[o]);
        }

#if PRISM_SENSORS_ENABLED
        /* 顺手读一下传感器刷新「System」页（有就显示，没有就留 --），
         * 不参与任何 UI 决策 */
        if ((tick % 10) == 0) {
            imu_sample_t imu;
            float lux = 0.0f;
            if (imu_read(&imu) == ESP_OK) {
                ui_set_imu(imu.temp_c, imu.accel_g[0], imu.accel_g[1], imu.accel_g[2]);
            }
            if (als_read_lux(&lux) == ESP_OK) {
                ui_set_lux(lux);
            }
        }
#endif

        tick++;
        vTaskDelay(pdMS_TO_TICKS(BOARD_SENSOR_PERIOD_MS));
    }
#else
    /* ---------------- 完整：传感器手势 + 自动亮度 + 熄屏 ---------------- */
    imu_sample_t imu;
    float   lux       = 80.0f;
    bool    flipped   = false;
    bool    screen_on = true;
    uint8_t applied_bl = 80;

    TickType_t last_activity = xTaskGetTickCount();
    TickType_t last_shake    = 0;

    const float shake_th = (float)CONFIG_PRISM_SHAKE_THRESHOLD / 1000.0f;

    display_set_backlight(applied_bl);

    for (;;) {
        TickType_t now = xTaskGetTickCount();
        bool activity = false;

        /* 1) 六轴：姿态 / 翻转 / 摇一摇 */
        if (imu_read(&imu) == ESP_OK) {
            ui_set_imu(imu.temp_c, imu.accel_g[0], imu.accel_g[1], imu.accel_g[2]);

            /* 倒置检测：Z 轴朝下持续 -> 转 180° （棱镜光路相关，调试模式已关闭） */
            if (imu.accel_g[2] < BOARD_FLIP_THRESHOLD && !flipped) {
                flipped = true;
                display_set_rotation(180);
                ui_toast("Flipped");
                ESP_LOGI(TAG, "检测到倒置，屏幕旋转 180°");
            } else if (imu.accel_g[2] > BOARD_UPRIGHT_THRESHOLD && flipped) {
                flipped = false;
                display_set_rotation(0);
            }

            /* 摇一摇：合加速度明显偏离 1g -> 翻页 */
            float mag = sqrtf(imu.accel_g[0] * imu.accel_g[0] +
                              imu.accel_g[1] * imu.accel_g[1] +
                              imu.accel_g[2] * imu.accel_g[2]);
            if (fabsf(mag - 1.0f) > shake_th &&
                (now - last_shake) > pdMS_TO_TICKS(BOARD_SHAKE_COOLDOWN_MS)) {
                last_shake = now;
                activity = true;
                ui_next_page();
                ui_toast("Shake");
                ESP_LOGI(TAG, "摇一摇 -> 翻页");
            }
        }

        /* 2) 环境光：每 N 次采样读一次 */
        if ((tick % BOARD_ALS_EVERY_N) == 0) {
            if (als_read_lux(&lux) == ESP_OK) {
                ui_set_lux(lux);
            }
        }

        /* 3) 触摸条：短按翻页，长按开关背光 */
        input_event_t ev = input_poll();
        if (ev != INPUT_EVT_NONE || input_is_pressed()) {
            activity = true;
        }
        if (ev == INPUT_EVT_TAP) {
            ui_next_page();
        } else if (ev == INPUT_EVT_LONG) {
            screen_on = !screen_on;
            ESP_LOGI(TAG, "长按 -> 背光%s", screen_on ? "开" : "关");
        }

        /* 4) 电源管理：暗环境超时自动熄屏 */
        if (activity) {
            last_activity = now;
            screen_on = true;
        } else if (screen_on &&
                   lux < (float)CONFIG_PRISM_SCREEN_OFF_LUX &&
                   (now - last_activity) > pdMS_TO_TICKS(CONFIG_PRISM_SCREEN_OFF_DELAY_S * 1000)) {
            screen_on = false;
            ESP_LOGI(TAG, "环境光偏暗(%.1f lx)且空闲，自动熄屏", (double)lux);
        }

        uint8_t want = screen_on ? lux_to_backlight(lux) : 0;
        if (want != applied_bl) {
            display_set_backlight(want);
            applied_bl = want;
        }

        tick++;
        vTaskDelay(pdMS_TO_TICKS(BOARD_SENSOR_PERIOD_MS));
    }
#endif
}

/* ------------------------------------------------------------------ */
/* app_main                                                            */
/* ------------------------------------------------------------------ */
void app_main(void)
{
    /* 1) NVS */
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    /* 2) 显示 + UI */
    ESP_ERROR_CHECK(display_init());
    ESP_ERROR_CHECK(ui_init());

#if CONFIG_PRISM_DEBUG_LCD_ONLY
    ESP_LOGW(TAG, "==== Prism TV DEBUG (LCD) ====");
    ESP_LOGW(TAG, "key: GPIO%d=next, GPIO%d=prev", (int)BOARD_PIN_KEY, (int)BOARD_PIN_KEY2);
#else
    ESP_LOGI(TAG, "==== Prism TV (Scheme 2) boot ====");
#endif

    /* 3) 传感器（调试模式默认关闭：当前没接设备，避免 I2C 阻塞） */
#if PRISM_SENSORS_ENABLED
    ESP_LOGI(TAG, "init sensors...");
    ESP_ERROR_CHECK(sensors_init());
#else
    ESP_LOGW(TAG, "I2C 传感器已禁用（当前未接设备）");
#endif

    ESP_LOGI(TAG, "init input...");
    if (input_init() != ESP_OK) {
        ESP_LOGW(TAG, "输入源不可用，仍继续启动");
    }

#if PRISM_NET_ENABLED
    /* 4) WiFi（阻塞等待连接或进入 AP 配网模式） */
    ESP_LOGI(TAG, "init wifi...");
    ui_set_status("wifi connecting...");
    ESP_ERROR_CHECK(wifi_prov_start());

    if (wifi_is_connected()) {
        ui_set_status(wifi_get_ip_str());
        ui_toast("WiFi connected");
        web_server_start();
    } else {
        ui_set_status("setup: 192.168.4.1");
        ui_toast("AP: PrismTV-Setup");
    }

    /* 5) 网络任务（mDNS / SNTP / 天气 / OTA） */
    ESP_ERROR_CHECK(net_start());
#else
    ui_set_status("LCD only (no net)");
    ESP_LOGW(TAG, "纯点屏模式：未启动 WiFi/网络，时间与天气不会更新");
#endif

    /* 6) 传感器 + 交互任务 */
    xTaskCreatePinnedToCore(sensor_task, PRISM_INPUT_TASK_NAME, 4096, NULL, 5, NULL, 0);

    ESP_LOGI(TAG, "boot done");
}
