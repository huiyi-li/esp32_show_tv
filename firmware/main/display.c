/**
 * @file  display.c
 * @brief ST7789 240x240 通过 esp_lcd SPI + esp_lvgl_port 驱动
 */

#include <string.h>
#include "display.h"
#include "board_config.h"

#include "driver/spi_master.h"
#include "driver/ledc.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"   /* ESP-IDF v5.x，内含 ST7789 驱动 */
#include "esp_lvgl_port.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "display";

static lv_disp_t *s_disp = NULL;
static uint8_t     s_backlight = 80;
static esp_lcd_panel_handle_t s_panel = NULL;
static int         s_orient = BOARD_LCD_ORIENT_ID;
static bool        s_flip180 = false;   /* 运行时额外 180°（倒置自动旋转用） */

static const char *orient_name(int id)
{
    switch (id) {
    case 0:  return "NORMAL";
    case 1:  return "MIRROR_X";
    case 2:  return "MIRROR_Y";
    default: return "ROT180";
    }
}

/* 应用显示方向（补偿分光棱镜的反序像） */
static void apply_orientation(int id)
{
    if (s_panel == NULL) {
        return;
    }
    const bool mx = ((id == 1 || id == 3) ^ s_flip180);
    const bool my = ((id == 2 || id == 3) ^ s_flip180);

    /* 可视区 230x230 居中在 240x240 面板里：左上留 5px 黑边。
     * MY=1 时还要补偿 ST7789 的 320 行帧存：
     *   y_gap = RAM_H - top - VIEW_H
     * （例：top=5, VIEW_H=230 -> y_gap=85；MY=0 时 y_gap=top=5） */
    const int top   = CONFIG_PRISM_LCD_Y_GAP + BOARD_LCD_VIEW_TOP;
    const int x_gap = BOARD_LCD_VIEW_LEFT;
    const int y_gap = my ? (BOARD_LCD_RAM_H - top - BOARD_LCD_V_RES) : top;

    esp_lcd_panel_swap_xy(s_panel, false);
    esp_lcd_panel_mirror(s_panel, mx, my);
    esp_lcd_panel_set_gap(s_panel, x_gap, y_gap);
}

void display_cycle_orientation(void)
{
    s_orient = (s_orient + 1) & 0x3;
    apply_orientation(s_orient);
    ESP_LOGW(TAG, "LCD 方向 -> %d (%s)", s_orient, orient_name(s_orient));

    if (s_disp && lvgl_port_lock(0)) {
        lv_obj_invalidate(lv_scr_act());
        lv_obj_invalidate(lv_layer_top());
        lvgl_port_unlock();
    }
}

int display_get_orientation(void)
{
    return s_orient;
}

/* ------------------------------------------------------------------ */
/* 背光：LEDC PWM                                                      */
/* ------------------------------------------------------------------ */
static void backlight_init(void)
{
    ledc_timer_config_t timer = {
        .speed_mode      = BOARD_BL_LEDC_MODE,
        .duty_resolution = BOARD_BL_LEDC_RES,
        .timer_num       = BOARD_BL_LEDC_TIMER,
        .freq_hz         = BOARD_BL_PWM_HZ,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));

    ledc_channel_config_t ch = {
        .gpio_num   = BOARD_LCD_PIN_BL,
        .speed_mode = BOARD_BL_LEDC_MODE,
        .channel    = BOARD_BL_LEDC_CHANNEL,
        .timer_sel  = BOARD_BL_LEDC_TIMER,
        .duty       = 0,
        .hpoint     = 0,
        .intr_type  = LEDC_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&ch));
}

void display_set_backlight(uint8_t percent)
{
    if (percent > 100) percent = 100;
    s_backlight = percent;

    const uint32_t max_duty = (1u << 10) - 1;   /* 10-bit */
    uint32_t duty = (max_duty * percent) / 100u;

    ledc_set_duty(BOARD_BL_LEDC_MODE, BOARD_BL_LEDC_CHANNEL, duty);
    ledc_update_duty(BOARD_BL_LEDC_MODE, BOARD_BL_LEDC_CHANNEL);
}

uint8_t display_get_backlight(void)
{
    return s_backlight;
}

/* ------------------------------------------------------------------ */
/* 旋转                                                                */
/* ------------------------------------------------------------------ */
void display_set_rotation(uint16_t degree)
{
    if (s_panel == NULL) {
        return;
    }

    /* 只支持 0 / 180：在棱镜补偿方向上再叠加 180°。
     * 直接用 MADCTL 实现并同步补偿 gap（LVGL 旋转回调不会调 gap）。 */
    const bool flip = ((degree % 360) == 180);
    if (flip == s_flip180) {
        return;
    }
    s_flip180 = flip;
    apply_orientation(s_orient);

    if (s_disp && lvgl_port_lock(0)) {
        lv_obj_invalidate(lv_scr_act());
        lv_obj_invalidate(lv_layer_top());
        lvgl_port_unlock();
    }
}

/* ------------------------------------------------------------------ */
/* 初始化                                                              */
/* ------------------------------------------------------------------ */
#if CONFIG_PRISM_LCD_SELFTEST
/**
 * 绕过 LVGL，直接画整屏彩条 + 白框，用来判断花屏来源：
 *   - 彩条干净、白框完整 -> SPI/接线正常，问题在偏移/LVGL
 *   - 彩条花、白框断裂   -> 降 SPI 频率或检查接线
 */
static void draw_bars(esp_lcd_panel_handle_t panel, int gap)
{
    const int w = BOARD_LCD_H_RES;
    const int h = BOARD_LCD_V_RES;
    uint16_t *line = heap_caps_malloc(w * sizeof(uint16_t),
                                      MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (line == NULL) {
        return;
    }

    static const uint16_t bars[8] = {
        0xF800, 0x07E0, 0x001F, 0xFFFF,   /* R G B W */
        0xFFE0, 0x07FF, 0xF81F, 0x7BEF    /* Y C M Gray */
    };

    esp_lcd_panel_set_gap(panel, 0, gap);
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            uint16_t c = bars[(x * 8) / w];
            if (y < 2 || y >= h - 2 || x < 2 || x >= w - 2) {
                c = 0xFFFF;               /* 白色边框 */
            }
            line[x] = (uint16_t)((c >> 8) | (c << 8));  /* 大端送给面板 */
        }
        esp_lcd_panel_draw_bitmap(panel, 0, y, w, y + 1, line);
    }
    free(line);
}

static void lcd_selftest(esp_lcd_panel_handle_t panel)
{
    ESP_LOGW(TAG, "LCD 自检 A: gap=80, spi=%d Hz (4s)", CONFIG_PRISM_LCD_SPI_HZ);
    draw_bars(panel, 80);
    vTaskDelay(pdMS_TO_TICKS(4000));

    ESP_LOGW(TAG, "LCD 自检 B: gap=0, spi=%d Hz (4s)", CONFIG_PRISM_LCD_SPI_HZ);
    draw_bars(panel, 0);
    vTaskDelay(pdMS_TO_TICKS(4000));

    /* 恢复配置的方向/gap，交给 LVGL */
    apply_orientation(s_orient);
}
#endif

/* 把整块 240x240 面板清成黑色，避免 230x230 可视区外露出旧内容 */
static void panel_clear_black(esp_lcd_panel_handle_t panel)
{
    const int w = BOARD_LCD_PANEL_W;
    uint16_t *line = heap_caps_malloc(w * sizeof(uint16_t),
                                      MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (line == NULL) {
        return;
    }
    memset(line, 0, w * sizeof(uint16_t));

    esp_lcd_panel_swap_xy(panel, false);
    esp_lcd_panel_mirror(panel, false, false);
    esp_lcd_panel_set_gap(panel, 0, 0);
    for (int y = 0; y < BOARD_LCD_PANEL_H; y++) {
        esp_lcd_panel_draw_bitmap(panel, 0, y, w, y + 1, line);
    }
    free(line);
}

esp_err_t display_init(void)
{
    backlight_init();

    /* 1. SPI 总线 */
    spi_bus_config_t buscfg = {
        .sclk_io_num     = BOARD_LCD_PIN_SCLK,
        .mosi_io_num     = BOARD_LCD_PIN_MOSI,
        .miso_io_num     = -1,
        .quadwp_io_num   = -1,
        .quadhd_io_num   = -1,
        .max_transfer_sz = BOARD_LCD_H_RES * 80 * sizeof(uint16_t),
    };
    ESP_ERROR_CHECK(spi_bus_initialize(BOARD_LCD_HOST, &buscfg, SPI_DMA_CH_AUTO));

    /* 2. panel IO */
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_io_spi_config_t io_cfg = {
        .dc_gpio_num       = BOARD_LCD_PIN_DC,
        .cs_gpio_num       = BOARD_LCD_PIN_CS,
        .pclk_hz           = CONFIG_PRISM_LCD_SPI_HZ,
        .lcd_cmd_bits      = 8,
        .lcd_param_bits    = 8,
        .spi_mode          = 0,
        .trans_queue_depth = 10,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)BOARD_LCD_HOST,
                                             &io_cfg, &io));

    /* 3. ST7789 panel */
    esp_lcd_panel_handle_t panel = NULL;
    esp_lcd_panel_dev_config_t panel_cfg = {
        .reset_gpio_num = BOARD_LCD_PIN_RST,
        .rgb_ele_order  = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(io, &panel_cfg, &panel));

    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel, true));

    /* 先把整块面板清黑，保证 230x230 可视区外的 5px 边框是黑的 */
    panel_clear_black(panel);

    /* 棱镜光路校正：分光棱镜成的是反序/镜像像，LCD 需要反向显示。
     * 方向由 PRISM_LCD_ORIENT 选择；调试模式下长按 D13 可实时循环 4 种。 */
    s_panel = panel;
    apply_orientation(s_orient);

    {
        const int top = CONFIG_PRISM_LCD_Y_GAP + BOARD_LCD_VIEW_TOP;
        const int y_gap = BOARD_LCD_MIRROR_Y
                          ? (BOARD_LCD_RAM_H - top - BOARD_LCD_V_RES) : top;
        ESP_LOGW(TAG, "LCD 可视区 %dx%d / 面板 %dx%d, 偏移 (%d,%d), 方向=%d (%s), spi=%d Hz",
                 BOARD_LCD_H_RES, BOARD_LCD_V_RES, BOARD_LCD_PANEL_W, BOARD_LCD_PANEL_H,
                 BOARD_LCD_VIEW_LEFT, y_gap, s_orient, orient_name(s_orient),
                 CONFIG_PRISM_LCD_SPI_HZ);
    }

    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, true));

#if CONFIG_PRISM_LCD_SELFTEST
    lcd_selftest(panel);
#endif

    /* 4. LVGL 移植层 */
    const lvgl_port_cfg_t port_cfg = ESP_LVGL_PORT_INIT_CONFIG();
    ESP_ERROR_CHECK(lvgl_port_init(&port_cfg));

    const lvgl_port_display_cfg_t disp_cfg = {
        .io_handle     = io,
        .panel_handle  = panel,
        .buffer_size   = BOARD_LCD_H_RES * 40,   /* 40 行缓冲 */
        .double_buffer = true,
        .hres          = BOARD_LCD_H_RES,
        .vres          = BOARD_LCD_V_RES,
        .monochrome    = false,
        /* 与 apply_orientation() 保持一致，供 esp_lvgl_port 旋转回调使用 */
        .rotation = {
            .swap_xy  = false,
            .mirror_x = BOARD_LCD_MIRROR_X,
            .mirror_y = BOARD_LCD_MIRROR_Y,
        },
        .flags = {
            .buff_dma = true,
        },
    };
    s_disp = lvgl_port_add_disp(&disp_cfg);
    if (s_disp == NULL) {
        ESP_LOGE(TAG, "lvgl_port_add_disp failed");
        return ESP_FAIL;
    }

    display_set_backlight(s_backlight);
    ESP_LOGI(TAG, "ST7789 %dx%d ready, SPI=%d Hz", BOARD_LCD_H_RES, BOARD_LCD_V_RES,
             CONFIG_PRISM_LCD_SPI_HZ);
    return ESP_OK;
}

lv_disp_t *display_get(void)
{
    return s_disp;
}
