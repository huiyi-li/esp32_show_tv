/**
 * @file  ui_icons.c
 * @brief 界面小图标描述符（数据在 ui_icons.bin，由 make_assets.py 生成）
 */

#include "ui_icons.h"
#include "assets_gen.h"

/* 链接进 flash 的资源符号（EMBED_FILES） */
extern const uint8_t _binary_ui_icons_bin_start[];

static lv_img_dsc_t s_icon[UI_ICON_COUNT];
static lv_img_dsc_t s_fallback;
static bool         s_ready = false;

static void icons_init(void)
{
    const uint8_t *base = _binary_ui_icons_bin_start;

    for (int i = 0; i < UI_ICON_COUNT; i++) {
        s_icon[i].header.cf = LV_IMG_CF_ALPHA_4BIT;
        s_icon[i].header.w  = UI_ICON_SIZE;
        s_icon[i].header.h  = UI_ICON_SIZE;
        s_icon[i].data_size = UI_ICON_BYTES;
        s_icon[i].data      = base + (size_t)i * UI_ICON_BYTES;
    }

    static const uint8_t zero_px[2] = { 0x00, 0x00 };
    s_fallback.header.cf = LV_IMG_CF_ALPHA_4BIT;
    s_fallback.header.w  = 2;
    s_fallback.header.h  = 2;
    s_fallback.data_size = sizeof(zero_px);
    s_fallback.data      = zero_px;

    s_ready = true;
}

const lv_img_dsc_t *ui_icon_get(int id)
{
    if (!s_ready) {
        icons_init();
    }
    if (id < 0 || id >= UI_ICON_COUNT) {
        return &s_fallback;
    }
    return &s_icon[id];
}
