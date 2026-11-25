// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "app_config.h"

typedef void (*link_audio_cb_t)(const uint8_t *data, size_t len);

void link_start(const app_config_t *cfg, link_audio_cb_t on_audio);
bool link_connected(void);
void link_send_json(const char *json);
void link_send_audio(const int16_t *pcm, size_t samples);
