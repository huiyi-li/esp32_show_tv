#pragma once

/**
 * @file  sensors.h
 * @brief MPU6050 (IMU, 0x68) + BH1750 (环境光, 0x23)，共用一条 I2C 总线
 */

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float accel_g[3];     /* x y z，单位 g */
    float gyro_dps[3];    /* x y z，单位 °/s */
    float temp_c;
} imu_sample_t;

/** 初始化 I2C 总线及两个传感器 */
esp_err_t sensors_init(void);

/** 读取六轴数据 */
esp_err_t imu_read(imu_sample_t *out);

/** 读取环境光，单位 lux */
esp_err_t als_read_lux(float *lux);

/** 最近一次读取的环境光（lux），未读取过为 0 */
float sensors_last_lux(void);

/** 最近一次读取的 IMU 温度（°C），未读取过为 0 */
float sensors_last_temp(void);

#ifdef __cplusplus
}
#endif
