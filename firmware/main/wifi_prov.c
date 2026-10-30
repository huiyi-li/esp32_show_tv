/**
 * @file  wifi_prov.c
 * @brief WiFi 连接管理 + AP 网页配网
 *
 * 流程：
 *   1. 从 NVS("wifi") 读取 ssid/pass
 *   2. 有凭据 -> STA 连接，15s 超时
 *   3. 无凭据 / 连接失败 -> 启动 SoftAP + HTTP 配网页 (http://192.168.4.1)
 *      提交后写入 NVS 并重启
 */

#include <string.h>
#include <stdlib.h>
#include "wifi_prov.h"
#include "board_config.h"

#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "esp_http_server.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

static const char *TAG = "wifi";

#define WIFI_NVS_NS         "wifi"
#define WIFI_CONNECTED_BIT  BIT0
#define WIFI_FAIL_BIT       BIT1
#define WIFI_MAX_RETRY      5
#define WIFI_STA_TIMEOUT_MS 15000

static EventGroupHandle_t s_evt;
static bool     s_connected = false;
static int      s_retry = 0;
static httpd_handle_t s_httpd = NULL;
static char     s_ip_str[16] = "0.0.0.0";

/* ------------------------------------------------------------------ */
/* NVS 凭据                                                            */
/* ------------------------------------------------------------------ */
static void creds_save(const char *ssid, const char *pass)
{
    nvs_handle_t h;
    if (nvs_open(WIFI_NVS_NS, NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_str(h, "ssid", ssid);
        nvs_set_str(h, "pass", pass);
        nvs_commit(h);
        nvs_close(h);
    }
}

static bool creds_load(char *ssid, size_t slen, char *pass, size_t plen)
{
    nvs_handle_t h;
    bool ok = false;
    if (nvs_open(WIFI_NVS_NS, NVS_READONLY, &h) == ESP_OK) {
        size_t l = slen;
        if (nvs_get_str(h, "ssid", ssid, &l) == ESP_OK) {
            size_t l2 = plen;
            if (nvs_get_str(h, "pass", pass, &l2) == ESP_OK) {
                ok = true;
            }
        }
        nvs_close(h);
    }
    return ok;
}

void wifi_prov_reset(void)
{
    nvs_handle_t h;
    if (nvs_open(WIFI_NVS_NS, NVS_READWRITE, &h) == ESP_OK) {
        nvs_erase_all(h);
        nvs_commit(h);
        nvs_close(h);
    }
    ESP_LOGW(TAG, "已清除 WiFi 凭据，2 秒后重启");
    vTaskDelay(pdMS_TO_TICKS(2000));
    esp_restart();
}

/* ------------------------------------------------------------------ */
/* 事件处理                                                            */
/* ------------------------------------------------------------------ */
static void event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_connected = false;
        if (s_retry < WIFI_MAX_RETRY) {
            s_retry++;
            ESP_LOGW(TAG, "连接失败，重试 %d/%d", s_retry, WIFI_MAX_RETRY);
            esp_wifi_connect();
        } else {
            xEventGroupSetBits(s_evt, WIFI_FAIL_BIT);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *evt = (ip_event_got_ip_t *)data;
        snprintf(s_ip_str, sizeof(s_ip_str), IPSTR, IP2STR(&evt->ip_info.ip));
        s_retry = 0;
        s_connected = true;
        ESP_LOGI(TAG, "已连接，IP = %s", s_ip_str);
        xEventGroupSetBits(s_evt, WIFI_CONNECTED_BIT);
    }
}

/* ------------------------------------------------------------------ */
/* 配网网页                                                            */
/* ------------------------------------------------------------------ */
static const char *HTML_FORM =
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Prism TV Setup</title>"
    "<style>body{font-family:sans-serif;background:#111;color:#eee;margin:0;padding:24px}"
    "input,button{font-size:16px;padding:10px;width:100%;box-sizing:border-box;margin:6px 0;"
    "border-radius:8px;border:1px solid #444;background:#222;color:#eee}"
    "button{background:#00bcd4;color:#000;font-weight:bold;border:none}"
    "h1{font-size:20px}</style></head><body>"
    "<h1>Prism TV WiFi Setup</h1>"
    "<form method='POST' action='/save'>"
    "<input name='ssid' placeholder='WiFi SSID' required>"
    "<input name='pass' type='password' placeholder='Password'>"
    "<button type='submit'>保存并重启</button>"
    "</form></body></html>";

static esp_err_t get_root(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html");
    httpd_resp_send(req, HTML_FORM, HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
}

/* 简易 url decode */
static void url_decode(char *s)
{
    char *o = s;
    while (*s) {
        if (*s == '%' && s[1] && s[2]) {
            char hex[3] = { s[1], s[2], 0 };
            *o++ = (char)strtol(hex, NULL, 16);
            s += 3;
        } else if (*s == '+') {
            *o++ = ' ';
            s++;
        } else {
            *o++ = *s++;
        }
    }
    *o = '\0';
}

static bool form_get(const char *body, const char *key, char *out, size_t outlen)
{
    char pattern[32];
    snprintf(pattern, sizeof(pattern), "%s=", key);
    const char *p = strstr(body, pattern);
    if (!p) return false;
    p += strlen(pattern);
    const char *end = strchr(p, '&');
    size_t len = end ? (size_t)(end - p) : strlen(p);
    if (len >= outlen) len = outlen - 1;
    memcpy(out, p, len);
    out[len] = '\0';
    url_decode(out);
    return true;
}

static esp_err_t post_save(httpd_req_t *req)
{
    char body[256] = {0};
    int total = req->content_len;
    if (total <= 0 || total >= (int)sizeof(body)) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "bad length");
        return ESP_FAIL;
    }

    int received = 0;
    while (received < total) {
        int r = httpd_req_recv(req, body + received, total - received);
        if (r <= 0) {
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "recv error");
            return ESP_FAIL;
        }
        received += r;
    }
    body[received] = '\0';

    char ssid[64] = {0};
    char pass[64] = {0};
    if (!form_get(body, "ssid", ssid, sizeof(ssid)) || ssid[0] == '\0') {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "missing ssid");
        return ESP_FAIL;
    }
    form_get(body, "pass", pass, sizeof(pass));

    ESP_LOGI(TAG, "收到配网信息: ssid=%s", ssid);
    creds_save(ssid, pass);

    httpd_resp_set_type(req, "text/html");
    httpd_resp_sendstr(req, "<h3>Saved. Rebooting...</h3>");
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
    return ESP_OK;
}

static void start_ap_and_httpd(void)
{
    esp_netif_create_default_wifi_ap();

    wifi_config_t ap_cfg = {
        .ap = {
            .ssid           = "PrismTV-Setup",
            .ssid_len       = 0,
            .channel        = 1,
            .max_connection = 3,
            .authmode       = WIFI_AUTH_OPEN,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.max_uri_handlers = 8;
    if (httpd_start(&s_httpd, &cfg) == ESP_OK) {
        httpd_uri_t uri_root = { .uri = "/",     .method = HTTP_GET,  .handler = get_root };
        httpd_uri_t uri_save = { .uri = "/save", .method = HTTP_POST, .handler = post_save };
        httpd_register_uri_handler(s_httpd, &uri_root);
        httpd_register_uri_handler(s_httpd, &uri_save);
    }

    ESP_LOGW(TAG, "已进入配网模式");
    ESP_LOGW(TAG, "  1) 手机连接 WiFi: PrismTV-Setup");
    ESP_LOGW(TAG, "  2) 浏览器打开 http://192.168.4.1");
    ESP_LOGW(TAG, "  3) 填写家里 WiFi 帐号密码并保存");
}

/* ------------------------------------------------------------------ */
/* 对外接口                                                            */
/* ------------------------------------------------------------------ */
esp_err_t wifi_prov_start(void)
{
    s_evt = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                        &event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                        &event_handler, NULL, NULL));

    char ssid[64] = {0};
    char pass[64] = {0};

    if (!creds_load(ssid, sizeof(ssid), pass, sizeof(pass)) || ssid[0] == '\0') {
        ESP_LOGI(TAG, "NVS 无凭据，直接进入配网模式");
        start_ap_and_httpd();
        return ESP_OK;
    }

    esp_netif_create_default_wifi_sta();

    wifi_config_t sta_cfg = {0};
    snprintf((char *)sta_cfg.sta.ssid, sizeof(sta_cfg.sta.ssid), "%s", ssid);
    snprintf((char *)sta_cfg.sta.password, sizeof(sta_cfg.sta.password), "%s", pass);
    sta_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    EventBits_t bits = xEventGroupWaitBits(s_evt,
                                           WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
                                           pdFALSE, pdFALSE,
                                           pdMS_TO_TICKS(WIFI_STA_TIMEOUT_MS));

    if (bits & WIFI_CONNECTED_BIT) {
        return ESP_OK;
    }

    ESP_LOGW(TAG, "STA 连接超时/失败，切换到配网模式");
    /* 只停不 deinit：deinit 后必须重新 init 才能再用，这里保持驱动常驻 */
    esp_wifi_stop();
    start_ap_and_httpd();
    return ESP_OK;
}

bool wifi_is_connected(void)
{
    return s_connected;
}

const char *wifi_get_ip_str(void)
{
    return s_ip_str;
}

int wifi_get_rssi(void)
{
    if (!s_connected) {
        return 0;
    }
    wifi_ap_record_t ap = {0};
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        return ap.rssi;
    }
    return 0;
}
