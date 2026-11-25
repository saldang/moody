// SPDX-License-Identifier: MIT
// USB provisioning. Line protocol used by firmware/tools/provision.py:
//
//   host> ID                 dev> OK ID <device-id> <fw-version>
//   host> GENKEY             dev> OK CSR <base64(PEM CSR)>     (private key stays in NVS)
//   host> SET <key> <b64>    dev> OK                             key: ssid|pass|uri|ntp|ca|cert
//   host> COMMIT             dev> OK COMMIT                      then reboot
//   host> WIPE               dev> OK
//
// Only reachable when the device is NOT provisioned (factory state or after a factory reset),
// so a provisioned device cannot be silently re-targeted to another gateway.
#include "provision.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "app.h"
#include "app_config.h"
#include "bootloader_random.h"
#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "esp_system.h"
#include "mbedtls/base64.h"
#include "mbedtls/ctr_drbg.h"
#include "mbedtls/ecp.h"
#include "mbedtls/entropy.h"
#include "mbedtls/pk.h"
#include "mbedtls/x509_csr.h"

static const char *TAG = "prov";
#define LINE_MAX_LEN 6144

static void reply(const char *s)
{
    usb_serial_jtag_write_bytes(s, strlen(s), pdMS_TO_TICKS(1000));
    usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(1000));
}

static int read_line(char *buf, size_t len)
{
    size_t n = 0;
    while (n < len - 1) {
        uint8_t c;
        if (usb_serial_jtag_read_bytes(&c, 1, portMAX_DELAY) != 1) {
            continue;
        }
        if (c == '\r') {
            continue;
        }
        if (c == '\n') {
            break;
        }
        buf[n++] = (char)c;
    }
    buf[n] = 0;
    return (int)n;
}

static char *b64_decode(const char *in)
{
    size_t olen = 0;
    size_t ilen = strlen(in);
    mbedtls_base64_decode(NULL, 0, &olen, (const unsigned char *)in, ilen);
    char *out = calloc(1, olen + 1);
    if (!out) {
        return NULL;
    }
    if (mbedtls_base64_decode((unsigned char *)out, olen, &olen, (const unsigned char *)in, ilen) != 0) {
        free(out);
        return NULL;
    }
    out[olen] = 0;
    return out;
}

static int generate_key_and_csr(const char *device_id, char *out, size_t out_len)
{
    int ret;
    mbedtls_pk_context key;
    mbedtls_entropy_context entropy;
    mbedtls_ctr_drbg_context drbg;
    mbedtls_x509write_csr req;
    unsigned char *pem = calloc(1, 2048);
    unsigned char *keypem = calloc(1, 512);
    char subject[64];

    mbedtls_pk_init(&key);
    mbedtls_entropy_init(&entropy);
    mbedtls_ctr_drbg_init(&drbg);
    mbedtls_x509write_csr_init(&req);

    // True RNG: enable the RF/ADC entropy source while Wi-Fi is off.
    bootloader_random_enable();
    ret = mbedtls_ctr_drbg_seed(&drbg, mbedtls_entropy_func, &entropy, (const unsigned char *)"moody-prov", 10);
    if (ret == 0) {
        ret = mbedtls_pk_setup(&key, mbedtls_pk_info_from_type(MBEDTLS_PK_ECKEY));
    }
    if (ret == 0) {
        ret = mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1, mbedtls_pk_ec(key), mbedtls_ctr_drbg_random, &drbg);
    }
    if (ret == 0) {
        snprintf(subject, sizeof(subject), "CN=%s", device_id);
        mbedtls_x509write_csr_set_md_alg(&req, MBEDTLS_MD_SHA256);
        mbedtls_x509write_csr_set_key(&req, &key);
        ret = mbedtls_x509write_csr_set_subject_name(&req, subject);
    }
    if (ret == 0) {
        ret = mbedtls_x509write_csr_pem(&req, pem, 2048, mbedtls_ctr_drbg_random, &drbg);
    }
    if (ret == 0) {
        ret = mbedtls_pk_write_key_pem(&key, keypem, 512);
    }
    bootloader_random_disable();
    if (ret == 0) {
        ret = app_config_set_str("key", (const char *)keypem) == ESP_OK ? 0 : -1;
    }
    if (ret == 0) {
        size_t olen = 0;
        ret = mbedtls_base64_encode((unsigned char *)out, out_len, &olen, pem, strlen((const char *)pem));
    }
    memset(keypem, 0, 512);  // do not leave the key in RAM
    free(keypem);
    free(pem);
    mbedtls_x509write_csr_free(&req);
    mbedtls_pk_free(&key);
    mbedtls_ctr_drbg_free(&drbg);
    mbedtls_entropy_free(&entropy);
    return ret;
}

void provision_run(void)
{
    usb_serial_jtag_driver_config_t cfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    cfg.rx_buffer_size = 2048;
    cfg.tx_buffer_size = 2048;
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&cfg));

    char device_id[20];
    app_config_device_id(device_id, sizeof(device_id));
    char *line = calloc(1, LINE_MAX_LEN);
    char *resp = calloc(1, 3072);
    ESP_LOGW(TAG, "not provisioned: waiting for provisioning tool on USB");
    reply("MOODY-PROV READY");

    while (true) {
        if (read_line(line, LINE_MAX_LEN) == 0) {
            continue;
        }
        if (strcmp(line, "ID") == 0) {
            snprintf(resp, 3072, "OK ID %s %s", device_id, MOODY_FW_VERSION);
            reply(resp);
        } else if (strcmp(line, "GENKEY") == 0) {
            strcpy(resp, "OK CSR ");
            if (generate_key_and_csr(device_id, resp + 7, 3072 - 7) == 0) {
                reply(resp);
            } else {
                reply("ERR keygen");
            }
        } else if (strncmp(line, "SET ", 4) == 0) {
            char *key = line + 4;
            char *val = strchr(key, ' ');
            if (!val) {
                reply("ERR syntax");
                continue;
            }
            *val++ = 0;
            static const char *allowed[] = {"ssid", "pass", "uri", "ntp", "ca", "cert"};
            bool ok = false;
            for (size_t i = 0; i < sizeof(allowed) / sizeof(allowed[0]); i++) {
                ok |= strcmp(key, allowed[i]) == 0;
            }
            char *decoded = ok ? b64_decode(val) : NULL;
            if (decoded && app_config_set_str(key, decoded) == ESP_OK) {
                reply("OK");
            } else {
                reply("ERR set");
            }
            if (decoded) {
                memset(decoded, 0, strlen(decoded));
                free(decoded);
            }
        } else if (strcmp(line, "COMMIT") == 0) {
            app_config_t c;
            app_config_commit();
            if (app_config_load(&c) == ESP_OK) {
                reply("OK COMMIT");
                vTaskDelay(pdMS_TO_TICKS(300));
                esp_restart();
            }
            app_config_erase();
            reply("ERR incomplete");
        } else if (strcmp(line, "WIPE") == 0) {
            app_config_erase();
            reply("OK");
        } else {
            reply("ERR unknown");
        }
    }
}
