// SPDX-License-Identifier: MIT
// WSS link to the gateway with mutual TLS:
//  - the gateway is verified against the service CA stored at provisioning time (no public CAs);
//  - the device authenticates with its own certificate + on-device generated key.
#include "link.h"

#include <stdlib.h>
#include <string.h>

#include "app.h"
#include "esp_log.h"
#include "esp_websocket_client.h"

static const char *TAG = "link";
static esp_websocket_client_handle_t s_client;
static link_audio_cb_t s_on_audio;
static bool s_connected;
static bool s_rx_binary;
static char *s_text;  // reassembly buffer for fragmented text frames
static size_t s_text_len;

#define MAX_TEXT 2048

bool link_connected(void)
{
    return s_connected && esp_websocket_client_is_connected(s_client);
}

static void on_ws(void *arg, esp_event_base_t base, int32_t id, void *event_data)
{
    esp_websocket_event_data_t *d = (esp_websocket_event_data_t *)event_data;
    switch (id) {
    case WEBSOCKET_EVENT_CONNECTED:
        s_connected = true;
        app_post(EV_LINK_UP, NULL);
        break;
    case WEBSOCKET_EVENT_DISCONNECTED:
    case WEBSOCKET_EVENT_CLOSED:
        if (s_connected) {
            s_connected = false;
            app_post(EV_LINK_DOWN, NULL);
        }
        break;
    case WEBSOCKET_EVENT_DATA:
        if (d->op_code == 0x2) {
            s_rx_binary = true;
        } else if (d->op_code == 0x1) {
            s_rx_binary = false;
            s_text_len = 0;
        } else if (d->op_code != 0x0) {
            break;  // ping/pong/close handled by the client
        }
        if (s_rx_binary) {
            if (s_on_audio && d->data_len > 0) {
                s_on_audio((const uint8_t *)d->data_ptr, d->data_len);
            }
        } else {
            if (s_text_len + d->data_len >= MAX_TEXT) {
                s_text_len = 0;  // oversized control message: drop it
                break;
            }
            memcpy(s_text + s_text_len, d->data_ptr, d->data_len);
            s_text_len += d->data_len;
            if (d->payload_offset + d->data_len >= d->payload_len) {
                s_text[s_text_len] = 0;
                app_post(EV_SRV_MESSAGE, strdup(s_text));
                s_text_len = 0;
            }
        }
        break;
    case WEBSOCKET_EVENT_ERROR:
        ESP_LOGW(TAG, "websocket error");
        break;
    default:
        break;
    }
}

void link_start(const app_config_t *cfg, link_audio_cb_t on_audio)
{
    s_on_audio = on_audio;
    s_text = calloc(1, MAX_TEXT);
    esp_websocket_client_config_t wc = {
        .uri = cfg->uri,
        .cert_pem = cfg->ca_pem,
        .client_cert = cfg->cert_pem,
        .client_key = cfg->key_pem,
        .subprotocol = "moody.v1",
        .buffer_size = 4096,
        .task_stack = 8192,
        .reconnect_timeout_ms = 5000,
        .network_timeout_ms = 10000,
        .ping_interval_sec = 15,
        .pingpong_timeout_sec = 30,
    };
    s_client = esp_websocket_client_init(&wc);
    esp_websocket_register_events(s_client, WEBSOCKET_EVENT_ANY, on_ws, NULL);
    ESP_ERROR_CHECK(esp_websocket_client_start(s_client));
}

void link_send_json(const char *json)
{
    if (link_connected()) {
        esp_websocket_client_send_text(s_client, json, strlen(json), pdMS_TO_TICKS(1000));
    }
}

void link_send_audio(const int16_t *pcm, size_t samples)
{
    if (link_connected()) {
        esp_websocket_client_send_bin(s_client, (const char *)pcm, samples * sizeof(int16_t), pdMS_TO_TICKS(500));
    }
}
