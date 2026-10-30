/**
 * @file  net_task.c
 * @brief 网络后台任务：mDNS + SNTP 对时 + 心知天气 + 状态刷新 + OTA
 *
 * 与 DESIGN.md 方案二「net_task」对应：
 *   - WiFi 就绪后注册 mDNS 主机名（默认 prismtv.local）；
 *   - SNTP 对时（仅在联网后启动）；
 *   - 定时拉取天气；
 *   - 周期刷新 IP / RSSI / 在线状态。
 */

#include <string.h>
#include <stdlib.h>
#include <time.h>

#include "net_task.h"
#include "wifi_prov.h"
#include "ui.h"
#include "weather_icons.h"
#include "board_config.h"

#include "esp_log.h"
#include "esp_sntp.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_ota_ops.h"
#include "esp_https_ota.h"
#include "mdns.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "net";

#define HTTP_RESP_MAX  4096

/* ------------------------------------------------------------------ */
/* 简易 HTTP GET，把响应写入 buf                                        */
/* ------------------------------------------------------------------ */
typedef struct {
    char  *buf;
    size_t cap;
    size_t len;
} http_ctx_t;

static esp_err_t http_event_cb(esp_http_client_event_t *evt)
{
    http_ctx_t *ctx = (http_ctx_t *)evt->user_data;
    if (ctx == NULL) {
        return ESP_OK;
    }
    if (evt->event_id == HTTP_EVENT_ON_DATA) {
        size_t space = ctx->cap - 1 - ctx->len;
        size_t copy = (evt->data_len < (int)space) ? (size_t)evt->data_len : space;
        memcpy(ctx->buf + ctx->len, evt->data, copy);
        ctx->len += copy;
        ctx->buf[ctx->len] = '\0';
    }
    return ESP_OK;
}

static esp_err_t http_get(const char *url, char *buf, size_t cap)
{
    http_ctx_t ctx = { .buf = buf, .cap = cap, .len = 0 };
    if (cap > 0) buf[0] = '\0';

    esp_http_client_config_t cfg = {
        .url               = url,
        .event_handler     = http_event_cb,
        .user_data         = &ctx,
        .timeout_ms        = 8000,
        .crt_bundle_attach = esp_crt_bundle_attach,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        return ESP_FAIL;
    }

    esp_err_t err = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);

    if (err != ESP_OK || status != 200) {
        ESP_LOGW(TAG, "HTTP GET 失败 err=%s status=%d", esp_err_to_name(err), status);
        return ESP_FAIL;
    }
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* mDNS                                                                */
/* ------------------------------------------------------------------ */
static void mdns_start(void)
{
    esp_err_t err = mdns_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "mDNS 初始化失败: %s", esp_err_to_name(err));
        return;
    }
    mdns_hostname_set(CONFIG_PRISM_MDNS_HOSTNAME);
    mdns_instance_name_set("Prism TV");
    mdns_service_add(NULL, "_http", "_tcp", 80, NULL, 0);
    ESP_LOGI(TAG, "mDNS 就绪: http://%s.local/", CONFIG_PRISM_MDNS_HOSTNAME);
}

/* ------------------------------------------------------------------ */
/* SNTP 对时                                                           */
/* ------------------------------------------------------------------ */
static void sntp_sync_cb(struct timeval *tv)
{
    (void)tv;
    ESP_LOGI(TAG, "SNTP 已同步");
    ui_toast("Time synced");
}

static void sntp_start(void)
{
    setenv("TZ", CONFIG_PRISM_TZ, 1);
    tzset();

    esp_sntp_setoperatingmode(ESP_SNTP_OPMODE_POLL);
    esp_sntp_setservername(0, CONFIG_PRISM_NTP_SERVER);
    esp_sntp_set_time_sync_notification_cb(sntp_sync_cb);
    esp_sntp_init();

    /* 等待首次同步，最多 15 秒 */
    for (int i = 0; i < 30; i++) {
        if (esp_sntp_get_sync_status() == SNTP_SYNC_STATUS_COMPLETED) {
            return;
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
    ESP_LOGW(TAG, "SNTP 首次同步超时，继续运行");
}

/* ------------------------------------------------------------------ */
/* 天气（心知天气 weather/daily.json）                                  */
/* ------------------------------------------------------------------ */
/* 心知/和风通用天气代码 -> 简短英文，避免依赖中文字库 */
static const char *code_to_text(int c)
{
    static const char *tbl[39] = {
        "Sunny", "Fair", "Cloudy", "Shower", "T-Storm", "T-Storm",
        "Sleet", "Light Rain", "Rain", "Heavy Rain", "Storm", "Storm",
        "Storm", "Snow Flurry", "Light Snow", "Snow", "Heavy Snow", "Snowstorm",
        "Fog", "Freezing Rain", "Sandstorm", "Light Rain", "Rain", "Heavy Rain",
        "Storm", "Storm", "Light Snow", "Snow", "Heavy Snow", "Dust",
        "Blowing Sand", "Sandstorm", "Dense Fog", "Dense Fog", "Haze",
        "Heavy Haze", "Severe Haze", "Fog", "Severe Haze"
    };
    if (c < 0 || c > 38) return "N/A";
    return tbl[c];
}

/* 天气代码 -> 自绘图标 */
static int code_to_icon(int c)
{
    switch (c) {
    case 0:                 return WICON_SUN;
    case 1:                 return WICON_SUN_CLOUD;
    case 2:                 return WICON_CLOUD;
    case 3: case 6: case 7: case 8: case 9:
    case 19: case 21: case 22: case 23:
                            return WICON_RAIN;
    case 4: case 5: case 10: case 11: case 12: case 24: case 25:
                            return WICON_THUNDER;
    case 13: case 14: case 15: case 16: case 17: case 26: case 27: case 28:
                            return WICON_SNOW;
    case 18: case 32: case 33: case 37:
                            return WICON_FOG;
    case 20: case 29: case 30: case 31:
    case 34: case 35: case 36: case 38:
                            return WICON_HAZE;
    default:                return WICON_CLOUD;
    }
}

/* ---------------- Open-Meteo（免 Key 兜底） ---------------- */
/* WMO 天气代码：0 晴, 1-2 少云, 3 阴, 45/48 雾, 51-67 雨, 71-77 雪,
 * 80-82 阵雨, 85-86 阵雪, 95+ 雷暴 */
static const char *wmo_to_text(int c)
{
    if (c == 0)                    return "Sunny";
    if (c <= 2)                    return "Partly";
    if (c == 3)                    return "Cloudy";
    if (c == 45 || c == 48)        return "Fog";
    if (c >= 51 && c <= 67)        return "Rain";
    if (c >= 71 && c <= 77)        return "Snow";
    if (c >= 80 && c <= 82)        return "Showers";
    if (c >= 85 && c <= 86)        return "Snow";
    if (c >= 95)                   return "T-Storm";
    return "N/A";
}

static int wmo_to_icon(int c)
{
    if (c == 0)                    return WICON_SUN;
    if (c <= 2)                    return WICON_SUN_CLOUD;
    if (c == 3)                    return WICON_CLOUD;
    if (c == 45 || c == 48)        return WICON_FOG;
    if (c >= 51 && c <= 67)        return WICON_RAIN;
    if (c >= 71 && c <= 77)        return WICON_SNOW;
    if (c >= 80 && c <= 82)        return WICON_RAIN;
    if (c >= 85 && c <= 86)        return WICON_SNOW;
    if (c >= 95)                   return WICON_THUNDER;
    return WICON_CLOUD;
}

static int json_int_at(cJSON *arr, int idx)
{
    cJSON *v = cJSON_GetArrayItem(arr, idx);
    return v ? (int)(v->valuedouble + (v->valuedouble >= 0 ? 0.5 : -0.5)) : 0;
}

/* 通过公网 IP 粗略定位（免 Key）：先 ipwho.is，失败再 ip-api.com */
static bool geo_lookup(double *lat, double *lon)
{
    static char resp[HTTP_RESP_MAX];

    if (http_get("https://ipwho.is/", resp, sizeof(resp)) == ESP_OK) {
        cJSON *root = cJSON_Parse(resp);
        if (root) {
            cJSON *ok = cJSON_GetObjectItem(root, "success");
            cJSON *la = cJSON_GetObjectItem(root, "latitude");
            cJSON *lo = cJSON_GetObjectItem(root, "longitude");
            cJSON *ci = cJSON_GetObjectItem(root, "city");
            if (cJSON_IsTrue(ok) && cJSON_IsNumber(la) && cJSON_IsNumber(lo)) {
                *lat = la->valuedouble;
                *lon = lo->valuedouble;
                ESP_LOGI(TAG, "IP 定位: %s (%.3f, %.3f)",
                         cJSON_IsString(ci) ? ci->valuestring : "?", *lat, *lon);
                cJSON_Delete(root);
                return true;
            }
            cJSON_Delete(root);
        }
    }

    if (http_get("http://ip-api.com/json", resp, sizeof(resp)) == ESP_OK) {
        cJSON *root = cJSON_Parse(resp);
        if (root) {
            cJSON *st = cJSON_GetObjectItem(root, "status");
            cJSON *la = cJSON_GetObjectItem(root, "lat");
            cJSON *lo = cJSON_GetObjectItem(root, "lon");
            cJSON *ci = cJSON_GetObjectItem(root, "city");
            if (cJSON_IsString(st) && strcmp(st->valuestring, "success") == 0 &&
                cJSON_IsNumber(la) && cJSON_IsNumber(lo)) {
                *lat = la->valuedouble;
                *lon = lo->valuedouble;
                ESP_LOGI(TAG, "IP 定位(ip-api): %s (%.3f, %.3f)",
                         cJSON_IsString(ci) ? ci->valuestring : "?", *lat, *lon);
                cJSON_Delete(root);
                return true;
            }
            cJSON_Delete(root);
        }
    }

    return false;
}

static void openmeteo_fetch(void)
{
    static bool   located = false;
    static double lat = 0.0, lon = 0.0;

    if (!located) {
#if CONFIG_PRISM_WEATHER_AUTO_LOCATION
        if (!geo_lookup(&lat, &lon)) {
            lat = atof(CONFIG_PRISM_WEATHER_LAT);
            lon = atof(CONFIG_PRISM_WEATHER_LON);
            ESP_LOGW(TAG, "IP 定位失败，使用默认坐标 (%.2f, %.2f)", lat, lon);
        }
#else
        lat = atof(CONFIG_PRISM_WEATHER_LAT);
        lon = atof(CONFIG_PRISM_WEATHER_LON);
#endif
        located = true;
    }

    static char url[420];
    snprintf(url, sizeof(url),
             "https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f"
             "&current=temperature_2m,relative_humidity_2m,weather_code"
             "&daily=weather_code,temperature_2m_max,temperature_2m_min,relative_humidity_2m_max"
             "&timezone=Asia%%2FShanghai&forecast_days=1",
             lat, lon);

    static char resp[HTTP_RESP_MAX];
    if (http_get(url, resp, sizeof(resp)) != ESP_OK) {
        ui_set_status("weather offline");
        return;
    }

    cJSON *root = cJSON_Parse(resp);
    if (root == NULL) {
        ESP_LOGW(TAG, "Open-Meteo JSON 解析失败");
        return;
    }

    cJSON *daily = cJSON_GetObjectItem(root, "daily");
    cJSON *code  = cJSON_GetObjectItem(daily, "weather_code");
    int c  = json_int_at(code, 0);
    int hi = json_int_at(cJSON_GetObjectItem(daily, "temperature_2m_max"), 0);
    int lo = json_int_at(cJSON_GetObjectItem(daily, "temperature_2m_min"), 0);
    int hu = json_int_at(cJSON_GetObjectItem(daily, "relative_humidity_2m_max"), 0);

    /* 当前实时温度 / 湿度 / 天气代码 */
    int cur_c = -1000, cur_hum = -1;
    cJSON *cur = cJSON_GetObjectItem(root, "current");
    if (cur) {
        cJSON *t  = cJSON_GetObjectItem(cur, "temperature_2m");
        cJSON *h  = cJSON_GetObjectItem(cur, "relative_humidity_2m");
        cJSON *wc = cJSON_GetObjectItem(cur, "weather_code");
        if (cJSON_IsNumber(t)) {
            cur_c = (int)(t->valuedouble + (t->valuedouble >= 0 ? 0.5 : -0.5));
        }
        if (cJSON_IsNumber(h)) {
            cur_hum = (int)(h->valuedouble + 0.5);
        }
        if (cJSON_IsNumber(wc)) {
            c = wc->valueint;
        }
    }
    if (cur_hum >= 0) {
        hu = cur_hum;
    }

    ui_set_weather(wmo_to_icon(c), wmo_to_text(c), cur_c, lo, hi, hu);
    ESP_LOGI(TAG, "Open-Meteo: %s(code=%d) now %d C, %d~%d C, 湿度 %d%%",
             wmo_to_text(c), c, cur_c, lo, hi, hu);

    cJSON_Delete(root);
}

/* 心知天气 now.json：当前温度 / 湿度 / 天气代码 */
static void seniverse_now(int *cur_c, int *cur_hum, int *cur_code)
{
    static char url[288];
    snprintf(url, sizeof(url),
             "https://api.seniverse.com/v3/weather/now.json"
             "?key=%s&location=%s&language=en&unit=c",
             CONFIG_PRISM_WEATHER_KEY, CONFIG_PRISM_WEATHER_LOCATION);

    static char resp[HTTP_RESP_MAX];
    if (http_get(url, resp, sizeof(resp)) != ESP_OK) {
        return;
    }
    cJSON *root = cJSON_Parse(resp);
    if (root == NULL) {
        return;
    }
    cJSON *results = cJSON_GetObjectItem(root, "results");
    cJSON *first   = cJSON_GetArrayItem(results, 0);
    cJSON *now     = cJSON_GetObjectItem(first, "now");
    if (now) {
        cJSON *t = cJSON_GetObjectItem(now, "temperature");
        cJSON *h = cJSON_GetObjectItem(now, "humidity");
        cJSON *c = cJSON_GetObjectItem(now, "code");
        if (cJSON_IsString(t)) *cur_c = atoi(t->valuestring);
        if (cJSON_IsString(h)) *cur_hum = atoi(h->valuestring);
        if (cJSON_IsString(c)) *cur_code = atoi(c->valuestring);
    }
    cJSON_Delete(root);
}

static void weather_fetch(void)
{
    /* 没填心知 Key 时走 Open-Meteo（无需注册） */
    if (strlen(CONFIG_PRISM_WEATHER_KEY) == 0) {
        openmeteo_fetch();
        return;
    }

    static char url[320];
    snprintf(url, sizeof(url),
             "https://api.seniverse.com/v3/weather/daily.json"
             "?key=%s&location=%s&language=en&unit=c&start=0&days=1",
             CONFIG_PRISM_WEATHER_KEY, CONFIG_PRISM_WEATHER_LOCATION);

    static char resp[HTTP_RESP_MAX];
    if (http_get(url, resp, sizeof(resp)) != ESP_OK) {
        ui_set_status("weather offline");
        return;
    }

    cJSON *root = cJSON_Parse(resp);
    if (root == NULL) {
        ESP_LOGW(TAG, "JSON 解析失败");
        return;
    }

    cJSON *results = cJSON_GetObjectItem(root, "results");
    cJSON *first   = cJSON_GetArrayItem(results, 0);
    cJSON *daily   = cJSON_GetObjectItem(first, "daily");
    cJSON *today   = cJSON_GetArrayItem(daily, 0);

    if (today) {
        cJSON *code = cJSON_GetObjectItem(today, "code_day");
        cJSON *high = cJSON_GetObjectItem(today, "high");
        cJSON *low  = cJSON_GetObjectItem(today, "low");
        cJSON *hum  = cJSON_GetObjectItem(today, "humidity");

        int c  = (code && code->valuestring) ? atoi(code->valuestring) : 2;
        int h  = (high && high->valuestring) ? atoi(high->valuestring) : 0;
        int l  = (low  && low->valuestring)  ? atoi(low->valuestring)  : 0;
        int hu = (hum  && hum->valuestring)  ? atoi(hum->valuestring)  : -1;

        /* now.json 取当前温度/湿度/天气代码 */
        int cur_c = -1000, cur_hum = -1, cur_code = -1;
        seniverse_now(&cur_c, &cur_hum, &cur_code);
        if (cur_code >= 0) c = cur_code;
        if (cur_hum < 0) cur_hum = hu;

        ui_set_weather(code_to_icon(c), code_to_text(c), cur_c, l, h, cur_hum);
        ESP_LOGI(TAG, "心知: %s(code=%d) now %d C, %d~%d C, 湿度 %d%%",
                 code_to_text(c), c, cur_c, l, h, cur_hum);
    }

    cJSON_Delete(root);
}

/* ------------------------------------------------------------------ */
/* OTA                                                                 */
/* ------------------------------------------------------------------ */
esp_err_t net_ota_from_url(const char *url)
{
    if (url == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    ESP_LOGW(TAG, "开始 OTA: %s", url);
    ui_toast("OTA updating...");

    esp_http_client_config_t cfg = {
        .url               = url,
        .timeout_ms        = 10000,
        .keep_alive_enable = true,
        .crt_bundle_attach = esp_crt_bundle_attach,
    };
    esp_https_ota_config_t ota_cfg = { .http_config = &cfg };

    esp_err_t err = esp_https_ota(&ota_cfg);
    if (err == ESP_OK) {
        ESP_LOGW(TAG, "OTA 成功，重启进入新固件");
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
    }
    ESP_LOGE(TAG, "OTA 失败: %s", esp_err_to_name(err));
    ui_toast("OTA failed");
    return err;
}

/* ------------------------------------------------------------------ */
/* 主任务                                                              */
/* ------------------------------------------------------------------ */
static void net_task(void *arg)
{
    (void)arg;

    bool sntp_started = false;
    bool mdns_done    = false;

    char last_hhmm[8] = {0};
    char last_ss[4] = {0};
    char last_date[24] = {0};
    TickType_t last_weather = 0;
    TickType_t last_netinfo = 0;

    for (;;) {
        if (wifi_is_connected()) {
            if (!mdns_done) {
                mdns_start();
                mdns_done = true;
            }
            if (!sntp_started) {
                sntp_start();
                sntp_started = true;
            }

            time_t now = time(NULL);
            struct tm tm_now;
            localtime_r(&now, &tm_now);

            char hhmm[8];
            strftime(hhmm, sizeof(hhmm), "%H:%M", &tm_now);
            if (strcmp(hhmm, last_hhmm) != 0) {
                snprintf(last_hhmm, sizeof(last_hhmm), "%s", hhmm);
                ui_set_time(hhmm);
            }

            char ss[4];
            strftime(ss, sizeof(ss), "%S", &tm_now);
            if (strcmp(ss, last_ss) != 0) {
                snprintf(last_ss, sizeof(last_ss), "%s", ss);
                ui_set_seconds(ss);
            }

            char date[24];
            strftime(date, sizeof(date), "%m/%d %a", &tm_now);
            if (strcmp(date, last_date) != 0) {
                snprintf(last_date, sizeof(last_date), "%s", date);
                ui_set_date(date);
            }

            /* 网络状态（每 5 秒刷新一次页面 1 的 IP/RSSI） */
            TickType_t now_tick = xTaskGetTickCount();
            if (last_netinfo == 0 ||
                (now_tick - last_netinfo) > pdMS_TO_TICKS(5000)) {
                last_netinfo = now_tick;
                ui_set_net_info(wifi_get_ip_str(), wifi_get_rssi(), true);
            }

            /* 天气 */
            if (last_weather == 0 ||
                (now_tick - last_weather) > pdMS_TO_TICKS(CONFIG_PRISM_WEATHER_INTERVAL_S * 1000)) {
                last_weather = now_tick;
                weather_fetch();
            }
        } else {
            mdns_done = false;
            ui_set_net_info(NULL, 0, false);
        }

        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

esp_err_t net_start(void)
{
    BaseType_t ok = xTaskCreatePinnedToCore(net_task, "net", 6144, NULL, 4, NULL, 0);
    return (ok == pdPASS) ? ESP_OK : ESP_FAIL;
}
