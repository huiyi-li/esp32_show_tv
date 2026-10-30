#pragma once

/**
 * @file  wifi_prov.h
 * @brief WiFi：优先用 NVS 里保存的凭据连接；失败则开 AP + 网页配网
 */

#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** 启动配网流程（阻塞直到连接成功或进入 AP 模式） */
esp_err_t wifi_prov_start(void);

/** 当前是否已连上路由器 */
bool wifi_is_connected(void);

/** 取本机 IP 字符串（静态缓冲区，非线程安全） */
const char *wifi_get_ip_str(void);

/** 当前 STA 的 RSSI（dBm）；未连接返回 0 */
int wifi_get_rssi(void);

/** 清除已保存的凭据并重启（重新配网） */
void wifi_prov_reset(void);

#ifdef __cplusplus
}
#endif
