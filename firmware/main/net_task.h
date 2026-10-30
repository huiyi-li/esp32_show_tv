#pragma once

/**
 * @file  net_task.h
 * @brief 网络任务：SNTP 对时、天气获取、OTA
 */

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** 启动网络后台任务（需在 WiFi 就绪后调用） */
esp_err_t net_start(void);

/** 触发一次 HTTP/HTTPS OTA（在独立任务中执行，不会返回） */
esp_err_t net_ota_from_url(const char *url);

#ifdef __cplusplus
}
#endif
