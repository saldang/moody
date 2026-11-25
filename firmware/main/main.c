// SPDX-License-Identifier: MIT
// Moody edge firmware - application state machine.
//
//   BOOT -> (not provisioned) PROVISIONING (USB)            -> reboot
//        -> CONNECTING (Wi-Fi, SNTP, WSS mTLS) -> IDLE
//   IDLE --wake word / tap--> LISTENING --VAD end--> THINKING --tts--> SPEAKING --> IDLE
//                                       (follow-up question: SPEAKING -> LISTENING for 6 s)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "app.h"
#include "app_config.h"
#include "audio.h"
#include "cJSON.h"
#include "esp_log.h"
#include "esp_system.h"
#include "link.h"
#include "net.h"
#include "nvs_flash.h"
#include "ota.h"
#include "provision.h"
#include "ui.h"

static const char *TAG = "moody";
QueueHandle_t g_app_events;

typedef enum { ST_CONNECTING, ST_IDLE, ST_LISTENING, ST_THINKING, ST_SPEAKING } state_t;
static state_t s_state = ST_CONNECTING;
static bool s_follow_up;
static app_config_t s_cfg;

#define FIRST_WORD_MS 5000
#define FOLLOW_UP_MS 6000

static void on_audio_from_gateway(const uint8_t *data, size_t len)
{
    audio_play_write(data, len);
}

static void go(state_t st, const char *detail)
{
    s_state = st;
    static const ui_state_t map[] = {
        [ST_CONNECTING] = UI_CONNECTING, [ST_IDLE] = UI_IDLE, [ST_LISTENING] = UI_LISTENING,
        [ST_THINKING] = UI_THINKING, [ST_SPEAKING] = UI_SPEAKING,
    };
    ui_set_state(map[st], detail);
}

static void start_listening(uint32_t no_speech_ms)
{
    if (!link_connected()) {
        return;
    }
    link_send_json("{\"type\":\"listen_start\"}");
    audio_listen(no_speech_ms);
    go(ST_LISTENING, NULL);
}

static void handle_server_message(const char *raw)
{
    cJSON *msg = cJSON_Parse(raw);
    if (!msg) {
        return;
    }
    const char *type = cJSON_GetStringValue(cJSON_GetObjectItem(msg, "type"));
    const char *display = cJSON_GetStringValue(cJSON_GetObjectItem(msg, "display"));
    if (!type) {
        cJSON_Delete(msg);
        return;
    }
    if (strcmp(type, "hello_ack") == 0) {
        ota_mark_valid();  // reached the gateway with mTLS: this firmware works
        go(ST_IDLE, NULL);
        cJSON *ota = cJSON_GetObjectItem(msg, "ota");
        const char *ver = cJSON_GetStringValue(cJSON_GetObjectItem(ota, "version"));
        const char *path = cJSON_GetStringValue(cJSON_GetObjectItem(ota, "path"));
        if (ver && path && ota_version_cmp(ver, MOODY_FW_VERSION) > 0) {  // never downgrade
            ui_set_state(UI_CONNECTING, "Aggiornamento in corso...");
            ota_start(&s_cfg, path);
        }
    } else if (strcmp(type, "state") == 0) {
        const char *v = cJSON_GetStringValue(cJSON_GetObjectItem(msg, "value"));
        if (v && strcmp(v, "thinking") == 0) {
            go(ST_THINKING, NULL);
        } else if (v && strcmp(v, "error") == 0) {
            ui_set_state(UI_ERROR, NULL);
            s_state = ST_IDLE;
        } else if (s_state != ST_SPEAKING) {
            go(ST_IDLE, NULL);
        }
    } else if (strcmp(type, "stt") == 0 && display) {
        ui_set_text(display);
    } else if (strcmp(type, "reply") == 0 && display) {
        ui_set_text(display);
    } else if (strcmp(type, "tts_start") == 0) {
        audio_play_begin();
        s_state = ST_SPEAKING;
        ui_set_state(UI_SPEAKING, NULL);
    } else if (strcmp(type, "tts_end") == 0) {
        s_follow_up = cJSON_IsTrue(cJSON_GetObjectItem(msg, "follow_up"));
        audio_play_end();
    }
    cJSON_Delete(msg);
}

static void event_loop(void)
{
    app_event_t ev;
    while (true) {
        if (xQueueReceive(g_app_events, &ev, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        switch (ev.type) {
        case EV_WIFI_UP:
            ESP_LOGI(TAG, "Wi-Fi up");
            break;
        case EV_WIFI_DOWN:
            go(ST_CONNECTING, "Wi-Fi non disponibile");
            break;
        case EV_LINK_UP: {
            char hello[96];
            snprintf(hello, sizeof(hello), "{\"type\":\"hello\",\"fw\":\"%s\",\"proto\":1}", MOODY_FW_VERSION);
            link_send_json(hello);
            break;
        }
        case EV_LINK_DOWN:
            audio_stop_listening();
            audio_play_abort();
            go(ST_CONNECTING, net_time_valid() ? "Server non raggiungibile" : "Sincronizzo l'ora...");
            break;
        case EV_WAKE:
            if (s_state == ST_IDLE) {
                start_listening(FIRST_WORD_MS);
            }
            break;
        case EV_TAP:
            if (s_state == ST_IDLE) {
                start_listening(FIRST_WORD_MS);
            } else if (s_state == ST_LISTENING) {
                audio_stop_listening();
                link_send_json("{\"type\":\"listen_end\"}");
                go(ST_THINKING, NULL);
            } else if (s_state == ST_SPEAKING || s_state == ST_THINKING) {
                s_follow_up = false;
                audio_play_abort();
                link_send_json("{\"type\":\"abort\"}");
                go(ST_IDLE, NULL);
            }
            break;
        case EV_LISTEN_END:
            if (s_state == ST_LISTENING) {
                if (ev.text) {  // nobody spoke: cancel quietly
                    link_send_json("{\"type\":\"abort\"}");
                    go(ST_IDLE, NULL);
                } else {
                    link_send_json("{\"type\":\"listen_end\"}");
                    go(ST_THINKING, NULL);
                }
            }
            break;
        case EV_PLAYBACK_DONE:
            if (s_follow_up) {
                s_follow_up = false;
                start_listening(FOLLOW_UP_MS);
            } else if (s_state == ST_SPEAKING) {
                go(ST_IDLE, NULL);
            }
            break;
        case EV_SRV_MESSAGE:
            if (ev.text) {
                handle_server_message(ev.text);
            }
            break;
        case EV_FACTORY_RESET:
            ESP_LOGW(TAG, "factory reset requested from touchscreen");
            ui_set_state(UI_PROVISIONING, "Reset: cancello i dati...");
            app_config_erase();
            vTaskDelay(pdMS_TO_TICKS(500));
            esp_restart();
            break;
        }
        free(ev.text);
    }
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();  // with CONFIG_NVS_ENCRYPTION the keys come from nvs_keys
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    g_app_events = xQueueCreate(32, sizeof(app_event_t));
    ui_start();

    if (app_config_load(&s_cfg) != ESP_OK) {
        char detail[96];
        snprintf(detail, sizeof(detail), "ID %s\nCollega l'USB ed esegui provision.py", s_cfg.device_id);
        ui_set_state(UI_PROVISIONING, detail);
        provision_run();  // never returns
    }
    ESP_LOGI(TAG, "device %s, firmware %s", s_cfg.device_id, MOODY_FW_VERSION);

    go(ST_CONNECTING, NULL);
    audio_start();
    net_start(&s_cfg);
    // Wait for a valid clock before TLS: certificate validity dates are enforced.
    for (int i = 0; i < 60 && !net_time_valid(); i++) {
        vTaskDelay(pdMS_TO_TICKS(500));
    }
    link_start(&s_cfg, on_audio_from_gateway);
    event_loop();
}
