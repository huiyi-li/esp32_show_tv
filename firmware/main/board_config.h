#pragma once

/**
 * @file  board_config.h
 * @brief 方案二主板引脚与器件地址定义（ESP32-PICO-D4）
 *
 * 约束：
 *  - GPIO6~11 / 16 / 17 被内部 Flash 占用，禁止使用
 *  - GPIO12 上电必须为低（Flash 电压选择），禁止接任何可拉高的网络
 *  - GPIO34/35/36/39 仅输入
 */

#include "sdkconfig.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "driver/touch_pad.h"

/* ---------------- LCD (ST7789, 1.3" 240x240) ---------------- */
#define BOARD_LCD_HOST          SPI2_HOST
#define BOARD_LCD_PIN_SCLK      GPIO_NUM_18
#define BOARD_LCD_PIN_MOSI      GPIO_NUM_23
#define BOARD_LCD_PIN_CS        GPIO_NUM_5
#define BOARD_LCD_PIN_DC        GPIO_NUM_27
#define BOARD_LCD_PIN_RST       GPIO_NUM_33
#define BOARD_LCD_PIN_BL        GPIO_NUM_32
#define BOARD_LCD_PANEL_W       240     /* 面板物理分辨率 */
#define BOARD_LCD_PANEL_H       240
#define BOARD_LCD_H_RES         230     /* 实际显示区（缩小居中，适配棱镜宽度） */
#define BOARD_LCD_V_RES         230
#define BOARD_LCD_VIEW_LEFT     5       /* 左/上留 5px 黑边 */
#define BOARD_LCD_VIEW_TOP      5
#define BOARD_LCD_RAM_H         320     /* ST7789 帧存行数（MY 补偿用） */

/* 显示方向（补偿分光棱镜的反序像）：
 * 0 正常 / 1 左右镜像 / 2 上下镜像 / 3 180°反序 */
#if CONFIG_PRISM_LCD_ORIENT_MIRROR_X
#define BOARD_LCD_MIRROR_X      1
#define BOARD_LCD_MIRROR_Y      0
#define BOARD_LCD_ORIENT_ID     1
#elif CONFIG_PRISM_LCD_ORIENT_MIRROR_Y
#define BOARD_LCD_MIRROR_X      0
#define BOARD_LCD_MIRROR_Y      1
#define BOARD_LCD_ORIENT_ID     2
#elif CONFIG_PRISM_LCD_ORIENT_ROT180
#define BOARD_LCD_MIRROR_X      1
#define BOARD_LCD_MIRROR_Y      1
#define BOARD_LCD_ORIENT_ID     3
#else
#define BOARD_LCD_MIRROR_X      0
#define BOARD_LCD_MIRROR_Y      0
#define BOARD_LCD_ORIENT_ID     0
#endif

/* LEDC 背光 */
#define BOARD_BL_LEDC_MODE      LEDC_LOW_SPEED_MODE
#define BOARD_BL_LEDC_TIMER     LEDC_TIMER_0
#define BOARD_BL_LEDC_CHANNEL   LEDC_CHANNEL_0
#define BOARD_BL_LEDC_RES       LEDC_TIMER_10_BIT
#define BOARD_BL_PWM_HZ         20000   /* >10kHz，避免可见频闪 */

/* ---------------- I2C 总线 ---------------- */
#define BOARD_I2C_PORT          0
#define BOARD_I2C_PIN_SDA       GPIO_NUM_21
#define BOARD_I2C_PIN_SCL       GPIO_NUM_22
#define BOARD_I2C_HZ            400000

/* ---------------- 传感器 ---------------- */
#define BOARD_MPU6050_ADDR      0x68    /* AD0 -> GND */
#define BOARD_MPU6050_PIN_INT   GPIO_NUM_34
#define BOARD_BH1750_ADDR       0x23    /* ADDR -> GND */

/* ---------------- 调试按键（PRISM_DEBUG_LCD_ONLY 时使用） ---------------- */
#if CONFIG_PRISM_DEBUG_LCD_ONLY
/* 按下接 GND，内部上拉。
 * 注意避开内部 Flash 占用脚：GPIO6~11/16/17；GPIO12 也不能拉高。
 * 默认 D13 下一页 / D15 上一页（D15 是 strapping，复位时别按住；
 * D2 在多数开发板上被板载 LED 拉低，不适合做按键）。 */
#define BOARD_PIN_KEY           ((gpio_num_t)CONFIG_PRISM_DEBUG_KEY_GPIO)   /* 下一页 */
#define BOARD_PIN_KEY2          ((gpio_num_t)CONFIG_PRISM_DEBUG_KEY2_GPIO)  /* 上一页，-1=关闭 */
#define BOARD_KEY_DEBOUNCE_MS   30
#define BOARD_KEY_LONG_MS       800
#endif

/* ---------------- 其它板级外设 ---------------- */
#define BOARD_PIN_TOUCH         GPIO_NUM_4     /* ESP32 Touch T0 */
#define BOARD_TOUCH_PAD         TOUCH_PAD_NUM0 /* 与 GPIO4 对应 */
#define BOARD_TOUCH_DEBOUNCE_MS 120
#define BOARD_TOUCH_LONG_MS     800
#define BOARD_PIN_VBUS_DET      GPIO_NUM_35    /* 分压后输入 */
#define BOARD_PIN_RGB_LED       GPIO_NUM_25    /* WS2812 数据，可选 */

/* ---------------- 行为参数 ---------------- */
#define BOARD_SENSOR_PERIOD_MS  20      /* 50Hz 采样 */
#define BOARD_ALS_EVERY_N       10      /* 每 10 次采样读一次光照(约 200ms) */

/* 自动亮度：以对数映射 lux -> 背光百分比 */
#define BOARD_LUX_DARK          5.0f
#define BOARD_LUX_BRIGHT        400.0f

/* 翻转检测阈值：加速度 Z 轴低于此值判定为“倒置” */
#define BOARD_FLIP_THRESHOLD    (-0.70f)
/* 回正阈值：Z 轴重新向上超过此值判定为“正立” */
#define BOARD_UPRIGHT_THRESHOLD (0.5f)

/* 摇一摇：合加速度与 1g 的偏差阈值（单位 g），
 * 实际生效阈值取 CONFIG_PRISM_SHAKE_THRESHOLD(mg)/1000 */
#define BOARD_SHAKE_COOLDOWN_MS 700

/* 熄屏（省电）：环境光低于阈值并持续一段时间后关背光 */
#define BOARD_LUX_OFF_DEFAULT   3.0f
#define BOARD_SCREEN_OFF_DELAY_DEFAULT_S 30

/* UI 页面数量 */
#define BOARD_UI_PAGE_COUNT     5
