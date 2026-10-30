/**
 * @file  weather_icons.c
 * @brief 天气图标描述符（数据在 weather_icons.bin，由 make_assets.py 生成）
 *
 * weather_icons.bin 布局：每个图标 WICON_BYTES_PER_FRAME 字节，
 *   前 WICON_PLANE_BYTES 为 warm（太阳/闪电）ALPHA_4BIT 48x48 蒙版，
 *   后 WICON_PLANE_BYTES 为 cool（云/雨/雪/雾）蒙版。
 * 这里在首次访问时生成 lv_img_dsc_t 描述符（指向 flash 只读数据）。
 */

#include "weather_icons.h"
#include "assets_gen.h"
#include "esp_log.h"

static const char *TAG = "wicon";

/* 链接进 flash 的资源符号（EMBED_FILES） */
extern const uint8_t _binary_weather_icons_bin_start[];

static lv_img_dsc_t s_warm[WICON_COUNT];
static lv_img_dsc_t s_cool[WICON_COUNT];
static lv_img_dsc_t s_fb_warm;
static lv_img_dsc_t s_fb_cool;
static bool         s_ready = false;

static void dsc_init(lv_img_dsc_t *d, const uint8_t *data)
{
    d->header.cf = LV_IMG_CF_ALPHA_4BIT;
    d->header.w  = WICON_SIZE;
    d->header.h  = WICON_SIZE;
    d->data_size = WICON_PLANE_BYTES;
    d->data      = data;
}

static void icons_init(void)
{
    const uint8_t *base = _binary_weather_icons_bin_start;

    for (int i = 0; i < WICON_COUNT; i++) {
        const uint8_t *p = base + (size_t)i * WICON_BYTES_PER_FRAME;
        dsc_init(&s_warm[i], p);
        dsc_init(&s_cool[i], p + WICON_PLANE_BYTES);
    }

    /* 兜底：2x2 全透明（ALPHA_4BIT，1 字节/行） */
    static const uint8_t zero_px[2] = { 0x00, 0x00 };
    s_fb_warm.header.cf = LV_IMG_CF_ALPHA_4BIT;
    s_fb_warm.header.w  = 2;
    s_fb_warm.header.h  = 2;
    s_fb_warm.data_size = sizeof(zero_px);
    s_fb_warm.data      = zero_px;
    s_fb_cool = s_fb_warm;

    s_ready = true;
    ESP_LOGI(TAG, "天气图标就绪: %d 个 x2 层 %dx%d", WICON_COUNT, WICON_SIZE, WICON_SIZE);
}

const lv_img_dsc_t *weather_icon_warm(int id)
{
    if (!s_ready) {
        icons_init();
    }
    if (id < 0 || id >= WICON_COUNT) {
        return &s_fb_warm;
    }
    return &s_warm[id];
}

const lv_img_dsc_t *weather_icon_cool(int id)
{
    if (!s_ready) {
        icons_init();
    }
    if (id < 0 || id >= WICON_COUNT) {
        return &s_fb_cool;
    }
    return &s_cool[id];
}
