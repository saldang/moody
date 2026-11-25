// SPDX-License-Identifier: MIT
#include "ota.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_https_ota.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ota";
static const app_config_t *s_cfg;
static char s_url[200];
static bool s_running;

int ota_version_cmp(const char *a, const char *b)
{
    int va[3] = {0}, vb[3] = {0};
    sscanf(a, "%d.%d.%d", &va[0], &va[1], &va[2]);
    sscanf(b, "%d.%d.%d", &vb[0], &vb[1], &vb[2]);
    for (int i = 0; i < 3; i++) {
        if (va[i] != vb[i]) {
            return va[i] > vb[i] ? 1 : -1;
        }
    }
    return 0;
}

static void ota_task(void *arg)
{
    esp_http_client_config_t http = {
        .url = s_url,
        .cert_pem = s_cfg->ca_pem,
        .client_cert_pem = s_cfg->cert_pem,
        .client_key_pem = s_cfg->key_pem,
        .timeout_ms = 30000,
        .keep_alive_enable = true,
    };
    esp_https_ota_config_t cfg = {.http_config = &http};
    ESP_LOGW(TAG, "downloading firmware from gateway");
    esp_err_t err = esp_https_ota(&cfg);
    if (err == ESP_OK) {
        ESP_LOGW(TAG, "update installed, rebooting");
        esp_restart();
    }
    ESP_LOGE(TAG, "update failed: %s", esp_err_to_name(err));
    s_running = false;
    vTaskDelete(NULL);
}

void ota_start(const app_config_t *cfg, const char *path)
{
    if (s_running || !path || path[0] != '/') {
        return;
    }
    // https://<same host:port as the WebSocket URI><path>
    const char *host = strstr(cfg->uri, "://");
    if (!host) {
        return;
    }
    host += 3;
    const char *end = strchr(host, '/');
    int host_len = end ? (int)(end - host) : (int)strlen(host);
    snprintf(s_url, sizeof(s_url), "https://%.*s%s", host_len, host, path);
    s_cfg = cfg;
    s_running = true;
    xTaskCreate(ota_task, "ota", 8192, NULL, 4, NULL);
}

void ota_mark_valid(void)
{
    esp_ota_img_states_t state;
    const esp_partition_t *running = esp_ota_get_running_partition();
    if (esp_ota_get_state_partition(running, &state) == ESP_OK && state == ESP_OTA_IMG_PENDING_VERIFY) {
        esp_ota_mark_app_valid_cancel_rollback();
        ESP_LOGI(TAG, "new firmware confirmed, rollback cancelled");
    }
}
