#pragma once

/**
 * @file  web_server.h
 * @brief 内置 HTTP 服务（STA 模式下）：
 *        - GET  /        状态页 + 图片上传 + OTA 入口
 *        - GET  /status  运行状态 JSON
 *        - POST /upload  上传图片（24/32bit BMP，或原始 RGB565 240x240）
 *        - POST /ota     表单 url=... 触发 OTA
 *        - POST /reset   清除 WiFi 凭据并重启（重新配网）
 *
 * 注意：AP 配网模式使用 wifi_prov.c 里的 80 端口服务，两者不同时运行。
 */

#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** 启动内置 HTTP 服务（重复调用安全） */
esp_err_t web_server_start(void);

/** 停止内置 HTTP 服务 */
void web_server_stop(void);

/** 是否正在运行 */
bool web_server_running(void);

#ifdef __cplusplus
}
#endif
