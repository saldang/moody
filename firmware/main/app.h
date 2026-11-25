// SPDX-License-Identifier: MIT
// Shared application types and the central event queue.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_app_desc.h"

// Single source of truth: CONFIG_APP_PROJECT_VER in sdkconfig.defaults (also used by OTA checks).
#define MOODY_FW_VERSION (esp_app_get_description()->version)

typedef enum {
    EV_WIFI_UP,
    EV_WIFI_DOWN,
    EV_LINK_UP,
    EV_LINK_DOWN,
    EV_WAKE,           // wake word detected
    EV_TAP,            // short tap on the screen
    EV_FACTORY_RESET,  // screen held for 10 s
    EV_LISTEN_END,     // on-device VAD: end of speech / timeout
    EV_SRV_MESSAGE,    // JSON control message from the gateway (payload: heap string)
    EV_PLAYBACK_DONE,  // TTS audio fully played
} app_event_type_t;

typedef struct {
    app_event_type_t type;
    char *text;  // owned by the receiver (free() it), may be NULL
} app_event_t;

extern QueueHandle_t g_app_events;

static inline void app_post(app_event_type_t type, char *text)
{
    app_event_t ev = {.type = type, .text = text};
    if (xQueueSend(g_app_events, &ev, 0) != pdTRUE && text) {
        free(text);
    }
}
