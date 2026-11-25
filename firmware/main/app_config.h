// SPDX-License-Identifier: MIT
#pragma once
#include "esp_err.h"
#include <stddef.h>

typedef struct {
    char ssid[33];
    char pass[65];
    char uri[160];
    char ntp[64];
    char *ca_pem;    // CA that signed the gateway certificate (service CA)
    char *cert_pem;  // this device's certificate (signed by the device CA)
    char *key_pem;   // this device's private key, generated on-device, never exported
    char device_id[20];
} app_config_t;

void app_config_device_id(char *out, size_t len);
esp_err_t app_config_load(app_config_t *cfg);       // ESP_ERR_NOT_FOUND if not provisioned
esp_err_t app_config_set_str(const char *key, const char *value);
esp_err_t app_config_commit(void);                  // marks the device as provisioned
esp_err_t app_config_erase(void);                   // factory reset: wipes everything
