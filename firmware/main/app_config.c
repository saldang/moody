// SPDX-License-Identifier: MIT
// Persistent configuration in NVS (encrypted in release builds).
#include "app_config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "esp_mac.h"
#include "nvs.h"
#include "nvs_flash.h"

#define NS "moody"

void app_config_device_id(char *out, size_t len)
{
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(out, len, "moody-%02x%02x%02x", mac[3], mac[4], mac[5]);
}

static esp_err_t get_str(nvs_handle_t h, const char *key, char *buf, size_t len)
{
    size_t n = len;
    return nvs_get_str(h, key, buf, &n);
}

static char *get_alloc(nvs_handle_t h, const char *key)
{
    size_t n = 0;
    if (nvs_get_str(h, key, NULL, &n) != ESP_OK || n == 0) {
        return NULL;
    }
    char *buf = calloc(1, n);
    if (buf && nvs_get_str(h, key, buf, &n) != ESP_OK) {
        free(buf);
        buf = NULL;
    }
    return buf;
}

esp_err_t app_config_load(app_config_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    app_config_device_id(cfg->device_id, sizeof(cfg->device_id));
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READONLY, &h);
    if (err != ESP_OK) {
        return ESP_ERR_NOT_FOUND;
    }
    uint8_t provisioned = 0;
    nvs_get_u8(h, "prov", &provisioned);
    get_str(h, "ssid", cfg->ssid, sizeof(cfg->ssid));
    get_str(h, "pass", cfg->pass, sizeof(cfg->pass));
    get_str(h, "uri", cfg->uri, sizeof(cfg->uri));
    if (get_str(h, "ntp", cfg->ntp, sizeof(cfg->ntp)) != ESP_OK) {
        strcpy(cfg->ntp, "pool.ntp.org");
    }
    cfg->ca_pem = get_alloc(h, "ca");
    cfg->cert_pem = get_alloc(h, "cert");
    cfg->key_pem = get_alloc(h, "key");
    nvs_close(h);
    if (!provisioned || !cfg->ssid[0] || !cfg->uri[0] || !cfg->ca_pem || !cfg->cert_pem || !cfg->key_pem) {
        return ESP_ERR_NOT_FOUND;
    }
    return ESP_OK;
}

esp_err_t app_config_set_str(const char *key, const char *value)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err == ESP_OK) {
        err = nvs_set_str(h, key, value);
        if (err == ESP_OK) {
            err = nvs_commit(h);
        }
        nvs_close(h);
    }
    return err;
}

esp_err_t app_config_commit(void)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err == ESP_OK) {
        err = nvs_set_u8(h, "prov", 1);
        if (err == ESP_OK) {
            err = nvs_commit(h);
        }
        nvs_close(h);
    }
    return err;
}

esp_err_t app_config_erase(void)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err == ESP_OK) {
        err = nvs_erase_all(h);
        if (err == ESP_OK) {
            err = nvs_commit(h);
        }
        nvs_close(h);
    }
    return err;
}
