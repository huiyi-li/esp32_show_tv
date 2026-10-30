/**
 * @file  sensors.c
 * @brief MPU6050 + BH1750 驱动（ESP-IDF v5.2+ 新版 i2c_master 驱动）
 */

#include "sensors.h"
#include "board_config.h"

#include "driver/i2c_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "sensors";

/* I2C 事务超时。绝不能传 -1（永久等待）：传感器未接/无上拉时会卡死启动 */
#define I2C_TIMEOUT_MS  50

static i2c_master_bus_handle_t  s_bus;
static i2c_master_dev_handle_t  s_mpu;
static i2c_master_dev_handle_t  s_bh;

/* 最近一次读数，供 UI / Web 任务读取（仅用于显示，非严格同步） */
static volatile float s_last_lux  = 0.0f;
static volatile float s_last_temp = 0.0f;

/* ---------------- MPU6050 寄存器 ---------------- */
#define MPU_REG_SMPLRT_DIV    0x19
#define MPU_REG_CONFIG        0x1A
#define MPU_REG_GYRO_CONFIG   0x1B
#define MPU_REG_ACCEL_CONFIG  0x1C
#define MPU_REG_ACCEL_XOUT_H  0x3B
#define MPU_REG_PWR_MGMT_1    0x6B
#define MPU_REG_WHO_AM_I      0x75

/* 量程换算系数 */
#define MPU_ACCEL_LSB_PER_G   16384.0f   /* ±2g   */
#define MPU_GYRO_LSB_PER_DPS  65.5f      /* ±500°/s */

/* ---------------- BH1750 命令 ---------------- */
#define BH_CMD_POWER_ON       0x01
#define BH_CMD_CONT_H_RES     0x10

/* ------------------------------------------------------------------ */
/* 底层 I2C 封装                                                       */
/* ------------------------------------------------------------------ */
static esp_err_t mpu_write_reg(uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = { reg, val };
    return i2c_master_transmit(s_mpu, buf, sizeof(buf), I2C_TIMEOUT_MS);
}

static esp_err_t mpu_read_regs(uint8_t reg, uint8_t *buf, size_t len)
{
    return i2c_master_transmit_receive(s_mpu, &reg, 1, buf, len, I2C_TIMEOUT_MS);
}

/* ------------------------------------------------------------------ */
/* 初始化                                                              */
/* ------------------------------------------------------------------ */
esp_err_t sensors_init(void)
{
    /* 1) I2C 主机总线。内部上拉也打开：空板/未接传感器时总线不会悬空，
     *    配合有限超时可避免初始化卡死（外部 4.7k 仍然有效）。 */
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port          = BOARD_I2C_PORT,
        .sda_io_num        = BOARD_I2C_PIN_SDA,
        .scl_io_num        = BOARD_I2C_PIN_SCL,
        .clk_source        = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags = {
            .enable_internal_pullup = true,
        },
    };
    esp_err_t err = i2c_new_master_bus(&bus_cfg, &s_bus);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "I2C 总线初始化失败: %s（跳过传感器）", esp_err_to_name(err));
        s_bus = NULL;
        return ESP_OK;
    }

    /* 2) MPU6050：先 probe，未接就不挂载，避免任何 I2C 事务 */
    if (i2c_master_probe(s_bus, BOARD_MPU6050_ADDR, I2C_TIMEOUT_MS) != ESP_OK) {
        s_mpu = NULL;
        ESP_LOGW(TAG, "未检测到 MPU6050(0x%02X)，跳过", BOARD_MPU6050_ADDR);
    } else {
        i2c_device_config_t mpu_cfg = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7,
            .device_address  = BOARD_MPU6050_ADDR,
            .scl_speed_hz    = BOARD_I2C_HZ,
        };
        err = i2c_master_bus_add_device(s_bus, &mpu_cfg, &s_mpu);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "MPU6050 挂载失败: %s", esp_err_to_name(err));
            s_mpu = NULL;
        } else {
            uint8_t who = 0;
            if (mpu_read_regs(MPU_REG_WHO_AM_I, &who, 1) == ESP_OK) {
                ESP_LOGI(TAG, "MPU6050 WHO_AM_I = 0x%02X (expect 0x68)", who);
                if (who != 0x68) {
                    ESP_LOGW(TAG, "WHO_AM_I 不是 0x68，可能是假片或型号不符");
                }
                mpu_write_reg(MPU_REG_PWR_MGMT_1, 0x00);      /* 唤醒 */
                vTaskDelay(pdMS_TO_TICKS(50));
                mpu_write_reg(MPU_REG_PWR_MGMT_1, 0x01);      /* 时钟源 = 陀螺 X */
                mpu_write_reg(MPU_REG_CONFIG, 0x03);          /* DLPF 44Hz */
                mpu_write_reg(MPU_REG_SMPLRT_DIV, 0x04);      /* 1kHz/(1+4)=200Hz */
                mpu_write_reg(MPU_REG_GYRO_CONFIG, 0x08);     /* ±500°/s */
                mpu_write_reg(MPU_REG_ACCEL_CONFIG, 0x00);    /* ±2g */
            } else {
                ESP_LOGW(TAG, "MPU6050 读取 WHO_AM_I 失败");
            }
        }
    }

    /* 3) BH1750：同样先 probe */
    if (i2c_master_probe(s_bus, BOARD_BH1750_ADDR, I2C_TIMEOUT_MS) != ESP_OK) {
        s_bh = NULL;
        ESP_LOGW(TAG, "未检测到 BH1750(0x%02X)，跳过", BOARD_BH1750_ADDR);
    } else {
        i2c_device_config_t bh_cfg = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7,
            .device_address  = BOARD_BH1750_ADDR,
            .scl_speed_hz    = BOARD_I2C_HZ,
        };
        err = i2c_master_bus_add_device(s_bus, &bh_cfg, &s_bh);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "BH1750 挂载失败: %s", esp_err_to_name(err));
            s_bh = NULL;
        } else {
            uint8_t cmd = BH_CMD_POWER_ON;
            if (i2c_master_transmit(s_bh, &cmd, 1, I2C_TIMEOUT_MS) == ESP_OK) {
                cmd = BH_CMD_CONT_H_RES;
                i2c_master_transmit(s_bh, &cmd, 1, I2C_TIMEOUT_MS);
                vTaskDelay(pdMS_TO_TICKS(180));           /* 首次转换约 120~180ms */
            } else {
                ESP_LOGW(TAG, "BH1750 上电失败");
            }
        }
    }

    ESP_LOGI(TAG, "传感器初始化完成: MPU6050=%s, BH1750=%s",
             s_mpu ? "OK" : "--", s_bh ? "OK" : "--");
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* 读取六轴                                                            */
/* ------------------------------------------------------------------ */
esp_err_t imu_read(imu_sample_t *out)
{
    if (s_mpu == NULL || out == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    uint8_t raw[14];
    esp_err_t err = mpu_read_regs(MPU_REG_ACCEL_XOUT_H, raw, sizeof(raw));
    if (err != ESP_OK) {
        return err;
    }

    int16_t ax = (int16_t)((raw[0]  << 8) | raw[1]);
    int16_t ay = (int16_t)((raw[2]  << 8) | raw[3]);
    int16_t az = (int16_t)((raw[4]  << 8) | raw[5]);
    int16_t t  = (int16_t)((raw[6]  << 8) | raw[7]);
    int16_t gx = (int16_t)((raw[8]  << 8) | raw[9]);
    int16_t gy = (int16_t)((raw[10] << 8) | raw[11]);
    int16_t gz = (int16_t)((raw[12] << 8) | raw[13]);

    out->accel_g[0] = ax / MPU_ACCEL_LSB_PER_G;
    out->accel_g[1] = ay / MPU_ACCEL_LSB_PER_G;
    out->accel_g[2] = az / MPU_ACCEL_LSB_PER_G;

    out->gyro_dps[0] = gx / MPU_GYRO_LSB_PER_DPS;
    out->gyro_dps[1] = gy / MPU_GYRO_LSB_PER_DPS;
    out->gyro_dps[2] = gz / MPU_GYRO_LSB_PER_DPS;

    out->temp_c = (t / 340.0f) + 36.53f;
    s_last_temp = out->temp_c;
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* 读取环境光                                                          */
/* ------------------------------------------------------------------ */
esp_err_t als_read_lux(float *lux)
{
    if (s_bh == NULL || lux == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    uint8_t raw[2];
    esp_err_t err = i2c_master_receive(s_bh, raw, sizeof(raw), -1);
    if (err != ESP_OK) {
        return err;
    }

    uint16_t v = (uint16_t)((raw[0] << 8) | raw[1]);
    *lux = v / 1.2f;      /* BH1750 高分辨率模式：lux = raw / 1.2 */
    s_last_lux = *lux;
    return ESP_OK;
}

float sensors_last_lux(void)
{
    return s_last_lux;
}

float sensors_last_temp(void)
{
    return s_last_temp;
}
