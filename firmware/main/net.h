// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>
#include "app_config.h"

void net_start(const app_config_t *cfg);   // Wi-Fi STA + SNTP; posts EV_WIFI_UP / EV_WIFI_DOWN
bool net_time_valid(void);                  // true once SNTP synced (needed to validate certificates)
