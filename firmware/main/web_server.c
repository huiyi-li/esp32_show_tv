/**
 * @file  web_server.c
 * @brief 内置 HTTP 服务：状态页 / 图片上传 / OTA / 重新配网
 *
 * 图片上传支持两种格式：
 *   1. 24/32bit 未压缩 BMP（自动最近邻缩放到 240x240，流式解码，内存占用小）；
 *   2. 原始 RGB565，恰好 240*240*2 = 115200 字节（LVGL 原生字节序）。
 */

#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#include "web_server.h"
#include "wifi_prov.h"
#include "sensors.h"
#include "ui.h"
#include "net_task.h"
#include "board_config.h"

#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "lvgl.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "web";

static httpd_handle_t s_httpd = NULL;

/* 图片缓冲几何取自 UI（分辨率可由 Kconfig PRISM_IMAGE_RES 决定） */
#define IMG_BYTES_OF(w, h)  ((size_t)(w) * (size_t)(h) * 2)

/* ------------------------------------------------------------------ */
/* 小工具                                                              */
/* ------------------------------------------------------------------ */
static inline uint16_t rd16(const uint8_t *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

static inline uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/** 从请求体读取恰好 n 字节 */
static bool recv_exact(httpd_req_t *req, uint8_t *buf, size_t n)
{
    size_t got = 0;
    int timeouts = 0;
    while (got < n) {
        int r = httpd_req_recv(req, (char *)buf + got, n - got);
        if (r == HTTPD_SOCK_ERR_TIMEOUT) {
            if (++timeouts > 40) {
                return false;
            }
            continue;
        }
        if (r <= 0) {
            return false;
        }
        got += r;
        timeouts = 0;
    }
    return true;
}

/* ------------------------------------------------------------------ */
/* BMP 流式解码 -> RGB565 240x240                                      */
/* ------------------------------------------------------------------ */
static esp_err_t bmp_stream_decode(httpd_req_t *req, const uint8_t *hdr,
                                   uint8_t *dest)
{
    const uint32_t data_off = rd32(hdr + 10);
    const int32_t  w        = (int32_t)rd32(hdr + 18);
    const int32_t  h_raw    = (int32_t)rd32(hdr + 22);
    const uint16_t bpp      = rd16(hdr + 28);
    const uint32_t comp     = rd32(hdr + 30);

    if (comp != 0 || (bpp != 24 && bpp != 32) || w <= 0 || h_raw == 0) {
        ESP_LOGW(TAG, "不支持的 BMP: bpp=%u comp=%u w=%d h=%d",
                 bpp, (unsigned)comp, (int)w, (int)h_raw);
        return ESP_ERR_INVALID_ARG;
    }
    if (w > 4096) {
        ESP_LOGW(TAG, "BMP 宽度过大: %d", (int)w);
        return ESP_ERR_INVALID_ARG;
    }

    const bool    bottom_up  = (h_raw > 0);
    const int32_t H          = bottom_up ? h_raw : -h_raw;
    const size_t  bppx       = bpp / 8;
    const size_t  row_stride = (((size_t)w * bppx) + 3u) & ~3u;

    const int iw = (int)ui_image_width();
    const int ih = (int)ui_image_height();

    /* 跳过文件头/调色板到像素数据 */
    if (data_off > 54) {
        uint8_t skip[64];
        size_t left = data_off - 54;
        while (left) {
            size_t n = left < sizeof(skip) ? left : sizeof(skip);
            if (!recv_exact(req, skip, n)) {
                return ESP_FAIL;
            }
            left -= n;
        }
    }

    uint8_t *row = heap_caps_malloc(row_stride, MALLOC_CAP_8BIT);
    if (row == NULL) {
        return ESP_ERR_NO_MEM;
    }

    lv_color_t *out = (lv_color_t *)dest;

    for (int32_t fr = 0; fr < H; fr++) {
        if (!recv_exact(req, row, row_stride)) {
            free(row);
            return ESP_FAIL;
        }
        int32_t sy = bottom_up ? (H - 1 - fr) : fr;

        for (int y = 0; y < ih; y++) {
            int32_t my = (int32_t)(((int64_t)y * H) / ih);
            if (my != sy) {
                continue;
            }
            for (int x = 0; x < iw; x++) {
                int32_t sx = (int32_t)(((int64_t)x * w) / iw);
                const uint8_t *px = row + (size_t)sx * bppx;
                uint8_t b = px[0], g = px[1], r = px[2];
                out[y * iw + x] = lv_color_make(r, g, b);
            }
        }
    }

    free(row);
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* 页面 / 处理器                                                       */
/* ------------------------------------------------------------------ */
static const char *INDEX_HTML =
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Prism TV</title><style>"
    "body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:20px}"
    "h1{font-size:20px;color:#00e5ff}"
    ".card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px;margin:12px 0}"
    ".grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;font-size:14px}"
    ".k{color:#8b949e}button,input[type=text]{font-size:15px;padding:9px;border-radius:8px;"
    "border:1px solid #30363d;background:#21262d;color:#e6edf3;width:100%;box-sizing:border-box}"
    "button{background:#00bcd4;color:#00181c;font-weight:600;border:none;margin-top:8px}"
    "input[type=file]{font-size:13px;color:#8b949e}"
    "</style></head><body>"
    "<h1>Prism TV</h1>"
    "<div class='card'><div class='grid' id='st'><span class='k'>loading...</span></div></div>"
    "<div class='card'><b>上传图片</b><br>"
    "<span class='k' style='font-size:12px'>24/32bit BMP 会自动缩放；或原始 RGB565 115200 字节</span><br>"
    "<input type='file' id='f' accept='.bmp,image/bmp'>"
    "<button onclick='up()'>上传并显示</button></div>"
    "<div class='card'><b>OTA 升级</b><br>"
    "<input type='text' id='ota' placeholder='http://host/firmware.bin'>"
    "<button onclick='ota()'>开始升级</button></div>"
    "<div class='card'><button onclick='reset()'>清除 WiFi 并重启（重新配网）</button></div>"
    "<script>"
    "async function tick(){try{const r=await fetch('/status');const j=await r.json();"
    "document.getElementById('st').innerHTML="
    "`<span class=k>IP</span><span>${j.ip}</span><span class=k>WiFi</span><span>${j.connected?'已连接 '+j.rssi+' dBm':'未连接'}</span>"
    "<span class=k>环境光</span><span>${j.lux.toFixed(0)} lx</span><span class=k>温度</span><span>${j.temp.toFixed(1)} C</span>"
    "<span class=k>可用内存</span><span>${(j.heap/1024).toFixed(1)} KB</span><span class=k>运行时长</span><span>${j.uptime} s</span>`;"
    "}catch(e){}}setInterval(tick,2000);tick();"
    "async function up(){const f=document.getElementById('f').files[0];if(!f)return;"
    "const b=await f.arrayBuffer();const r=await fetch('/upload',{method:'POST',body:b,"
    "headers:{'Content-Type':f.type||'application/octet-stream'}});"
    "alert(r.ok?'上传成功 ('+b.byteLength+' 字节)':'上传失败 '+r.status);}"
    "async function ota(){const u=document.getElementById('ota').value;if(!u)return;"
    "const r=await fetch('/ota',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},"
    "body:'url='+encodeURIComponent(u)});alert(await r.text());}"
    "function reset(){if(confirm('清除已保存的 WiFi 并重启？'))fetch('/reset',{method:'POST'}).then(()=>alert('重启中'));}"
    "</script></body></html>";

static esp_err_t get_root(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t get_status(httpd_req_t *req)
{
    char buf[288];
    int64_t uptime = esp_timer_get_time() / 1000000;
    snprintf(buf, sizeof(buf),
             "{\"ip\":\"%s\",\"connected\":%s,\"rssi\":%d,\"lux\":%.1f,\"temp\":%.1f,"
             "\"heap\":%u,\"uptime\":%lld,\"page\":%d}",
             wifi_get_ip_str(),
             wifi_is_connected() ? "true" : "false",
             wifi_get_rssi(),
             (double)sensors_last_lux(),
             (double)sensors_last_temp(),
             (unsigned)esp_get_free_heap_size(),
             (long long)uptime,
             (int)ui_get_page());
    httpd_resp_set_type(req, "application/json");
    return httpd_resp_sendstr(req, buf);
}

static esp_err_t post_upload(httpd_req_t *req)
{
    uint8_t *dest = ui_image_alloc();
    if (dest == NULL) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                            "no memory for image buffer");
        return ESP_FAIL;
    }

    uint8_t hdr[54];
    if (!recv_exact(req, hdr, 2)) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "short body");
        return ESP_FAIL;
    }

    const bool is_bmp = (hdr[0] == 'B' && hdr[1] == 'M');
    const size_t img_bytes = IMG_BYTES_OF(ui_image_width(), ui_image_height());
    esp_err_t err = ESP_OK;

    if (is_bmp) {
        if (!recv_exact(req, hdr + 2, 52)) {
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "short bmp header");
            return ESP_FAIL;
        }
        err = bmp_stream_decode(req, hdr, dest);
    } else {
        /* 原始 RGB565：先补回已读的 2 字节，再读满 */
        memcpy(dest, hdr, 2);
        if (!recv_exact(req, dest + 2, img_bytes - 2)) {
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "raw size mismatch");
            return ESP_FAIL;
        }
    }

    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "decode failed");
        return ESP_FAIL;
    }

    ui_image_commit();
    ui_set_status("image updated");
    ESP_LOGI(TAG, "图片上传并显示成功");
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_sendstr(req, "OK");
}

/* urlencoded 表单取字段（仅取第一个 key=value） */
static bool form_get(const char *body, const char *key, char *out, size_t outlen)
{
    char pattern[24];
    snprintf(pattern, sizeof(pattern), "%s=", key);
    const char *p = strstr(body, pattern);
    if (!p) {
        return false;
    }
    p += strlen(pattern);
    const char *end = strchr(p, '&');
    size_t len = end ? (size_t)(end - p) : strlen(p);
    if (len >= outlen) {
        len = outlen - 1;
    }
    memcpy(out, p, len);
    out[len] = '\0';
    return true;
}

static void ota_task(void *arg)
{
    char *url = (char *)arg;
    net_ota_from_url(url);
    free(url);
    vTaskDelete(NULL);
}

static esp_err_t post_ota(httpd_req_t *req)
{
    char body[256] = {0};
    int total = req->content_len;
    if (total <= 0 || total >= (int)sizeof(body)) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "bad length");
        return ESP_FAIL;
    }
    if (!recv_exact(req, (uint8_t *)body, total)) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "recv error");
        return ESP_FAIL;
    }
    body[total] = '\0';

    char url[192] = {0};
    if (!form_get(body, "url", url, sizeof(url)) || url[0] == '\0') {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "missing url");
        return ESP_FAIL;
    }

    char *copy = strdup(url);
    if (copy && xTaskCreate(ota_task, "ota", 6144, copy, 5, NULL) != pdPASS) {
        free(copy);
        copy = NULL;
    }
    if (!copy) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no mem");
        return ESP_FAIL;
    }

    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_sendstr(req, "OTA started");
}

static void reset_task(void *arg)
{
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(500));
    wifi_prov_reset();   /* 内部会重启，不返回 */
    vTaskDelete(NULL);
}

static esp_err_t post_reset(httpd_req_t *req)
{
    xTaskCreate(reset_task, "reset", 3072, NULL, 5, NULL);
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_sendstr(req, "rebooting");
}

/* ------------------------------------------------------------------ */
/* 启停                                                                */
/* ------------------------------------------------------------------ */
esp_err_t web_server_start(void)
{
    if (s_httpd) {
        return ESP_OK;
    }

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.max_uri_handlers  = 8;
    cfg.stack_size        = 6144;
    cfg.recv_wait_timeout = 10;
    cfg.send_wait_timeout = 10;
    cfg.lru_purge_enable  = true;

    esp_err_t err = httpd_start(&s_httpd, &cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "httpd_start 失败: %s", esp_err_to_name(err));
        s_httpd = NULL;
        return err;
    }

    const httpd_uri_t uris[] = {
        { .uri = "/",       .method = HTTP_GET,  .handler = get_root },
        { .uri = "/status", .method = HTTP_GET,  .handler = get_status },
        { .uri = "/upload", .method = HTTP_POST, .handler = post_upload },
        { .uri = "/ota",    .method = HTTP_POST, .handler = post_ota },
        { .uri = "/reset",  .method = HTTP_POST, .handler = post_reset },
    };
    for (size_t i = 0; i < sizeof(uris) / sizeof(uris[0]); i++) {
        httpd_register_uri_handler(s_httpd, &uris[i]);
    }

    ESP_LOGI(TAG, "HTTP 服务已启动: http://%s/", wifi_get_ip_str());
    return ESP_OK;
}

void web_server_stop(void)
{
    if (s_httpd) {
        httpd_stop(s_httpd);
        s_httpd = NULL;
    }
}

bool web_server_running(void)
{
    return s_httpd != NULL;
}
