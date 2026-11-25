// SPDX-License-Identifier: MIT
// Wi-Fi station with WPA2/WPA3 + PMF, exponential reconnect backoff, SNTP time sync.
#include "net.h"

#include <string.h>
#include <time.h>

#include "app.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"

static const char *TAG = "net";
static int s_backoff_ms = 1000;
static bool s_sntp_started;
static char s_ntp[64];

bool net_time_valid(void)
{
    return time(NULL) > 1735689600;  // 2025-01-01: anything earlier means "not synced"
}

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        app_post(EV_WIFI_DOWN, NULL);
        ESP_LOGW(TAG, "Wi-Fi disconnected, retry in %d ms", s_backoff_ms);
        vTaskDelay(pdMS_TO_TICKS(s_backoff_ms));
        s_backoff_ms = s_backoff_ms < 60000 ? s_backoff_ms * 2 : 60000;
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_backoff_ms = 1000;
        if (!s_sntp_started) {
            // Prefer the NTP server announced by DHCP (local router), fall back to the configured one.
            esp_sntp_config_t sntp = ESP_NETIF_SNTP_DEFAULT_CONFIG(s_ntp);
            sntp.server_from_dhcp = true;
            sntp.renew_servers_after_new_IP = true;
            sntp.start = true;
            esp_netif_sntp_init(&sntp);
            s_sntp_started = true;
        }
        app_post(EV_WIFI_UP, NULL);
    }
}

void net_start(const app_config_t *cfg)
{
    strlcpy(s_ntp, cfg->ntp, sizeof(s_ntp));
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL));

    wifi_config_t wc = {0};
    strlcpy((char *)wc.sta.ssid, cfg->ssid, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, cfg->pass, sizeof(wc.sta.password));
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;  // never join open/WEP/WPA1 networks
    wc.sta.pmf_cfg.capable = true;
    wc.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));  // credentials stay in our (encrypted) NVS only
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
}
