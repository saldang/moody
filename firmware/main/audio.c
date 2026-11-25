// SPDX-License-Identifier: MIT
// Audio front-end.
//
// Privacy property enforced here: microphone samples are only handed to the network layer
// while a listening window is open, i.e. after the on-device wake word or a tap on the screen.
// Before that, audio lives only in a short RAM ring buffer inside the AFE.
#include "audio.h"

#include <string.h>

#include "app.h"
#include "bsp/esp-box-3.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_wn_iface.h"
#include "freertos/stream_buffer.h"
#include "link.h"
#include "model_path.h"

static const char *TAG = "audio";

#define SAMPLE_RATE 16000
#define MIC_CHANNELS 2
#define MAX_LISTEN_MS 12000
#define END_SILENCE_MS 800
#define PLAY_BUF_BYTES (64 * 1024)

static esp_codec_dev_handle_t s_mic, s_spk;
static const esp_afe_sr_iface_t *s_afe;
static esp_afe_sr_data_t *s_afe_data;
static StreamBufferHandle_t s_play_buf;

static volatile bool s_listening;
static volatile bool s_speaking;
static volatile bool s_play_ending;
static int64_t s_listen_started_us, s_last_speech_us;
static bool s_heard_speech;
static uint32_t s_no_speech_ms;

bool audio_is_listening(void)
{
    return s_listening;
}

void audio_listen(uint32_t no_speech_ms)
{
    s_no_speech_ms = no_speech_ms;
    s_heard_speech = false;
    s_listen_started_us = s_last_speech_us = esp_timer_get_time();
    s_afe->disable_wakenet(s_afe_data);
    s_listening = true;
}

void audio_stop_listening(void)
{
    s_listening = false;
    s_afe->enable_wakenet(s_afe_data);
}

// ---- capture: mic -> AFE ---------------------------------------------------------------
static void feed_task(void *arg)
{
    const int chunk = s_afe->get_feed_chunksize(s_afe_data);  // samples per channel
    int16_t *raw = heap_caps_malloc(chunk * MIC_CHANNELS * sizeof(int16_t), MALLOC_CAP_SPIRAM);
    int16_t *mono = heap_caps_malloc(chunk * sizeof(int16_t), MALLOC_CAP_SPIRAM);
    while (true) {
        esp_codec_dev_read(s_mic, raw, chunk * MIC_CHANNELS * sizeof(int16_t));
        if (s_speaking) {
            continue;  // half duplex: don't let our own voice trigger the wake word
        }
        for (int i = 0; i < chunk; i++) {
            mono[i] = raw[i * MIC_CHANNELS];
        }
        s_afe->feed(s_afe_data, mono);
    }
}

// ---- detection: AFE -> wake word / VAD / stream ------------------------------------------
static void fetch_task(void *arg)
{
    while (true) {
        afe_fetch_result_t *res = s_afe->fetch(s_afe_data);
        if (!res || res->ret_value == ESP_FAIL) {
            continue;
        }
        if (!s_listening) {
            if (res->wakeup_state == WAKENET_DETECTED && !s_speaking) {
                ESP_LOGI(TAG, "wake word detected");
                app_post(EV_WAKE, NULL);
            }
            continue;
        }
        int64_t now = esp_timer_get_time();
        link_send_audio(res->data, res->data_size / sizeof(int16_t));
        if (res->vad_state == VAD_SPEECH) {
            s_heard_speech = true;
            s_last_speech_us = now;
        }
        bool timeout = (now - s_listen_started_us) / 1000 > MAX_LISTEN_MS;
        bool silence_after_speech = s_heard_speech && (now - s_last_speech_us) / 1000 > END_SILENCE_MS;
        bool nobody_spoke = !s_heard_speech && (now - s_listen_started_us) / 1000 > s_no_speech_ms;
        if (timeout || silence_after_speech || nobody_spoke) {
            audio_stop_listening();
            app_post(EV_LISTEN_END, nobody_spoke ? strdup("silence") : NULL);
        }
    }
}

// ---- playback -----------------------------------------------------------------------------
static void play_task(void *arg)
{
    uint8_t *buf = heap_caps_malloc(2048, MALLOC_CAP_INTERNAL);
    while (true) {
        size_t n = xStreamBufferReceive(s_play_buf, buf, 2048, pdMS_TO_TICKS(50));
        if (n > 0) {
            esp_codec_dev_write(s_spk, buf, n);
        } else if (s_speaking && s_play_ending && xStreamBufferIsEmpty(s_play_buf)) {
            vTaskDelay(pdMS_TO_TICKS(150));  // let the codec drain, avoid catching the tail as speech
            s_speaking = false;
            s_play_ending = false;
            app_post(EV_PLAYBACK_DONE, NULL);
        }
    }
}

void audio_play_begin(void)
{
    xStreamBufferReset(s_play_buf);
    s_play_ending = false;
    s_speaking = true;
}

void audio_play_write(const uint8_t *data, size_t len)
{
    if (!s_speaking) {
        return;
    }
    // Blocks when the buffer is full: this back-pressures the WebSocket (TCP flow control).
    xStreamBufferSend(s_play_buf, data, len, pdMS_TO_TICKS(2000));
}

void audio_play_end(void)
{
    s_play_ending = true;
}

void audio_play_abort(void)
{
    xStreamBufferReset(s_play_buf);
    s_play_ending = true;
}

void audio_start(void)
{
    s_spk = bsp_audio_codec_speaker_init();
    s_mic = bsp_audio_codec_microphone_init();
    esp_codec_dev_sample_info_t out_fs = {.sample_rate = SAMPLE_RATE, .channel = 1, .bits_per_sample = 16};
    esp_codec_dev_sample_info_t in_fs = {.sample_rate = SAMPLE_RATE, .channel = MIC_CHANNELS, .bits_per_sample = 16};
    ESP_ERROR_CHECK(esp_codec_dev_open(s_spk, &out_fs));
    ESP_ERROR_CHECK(esp_codec_dev_open(s_mic, &in_fs));
    esp_codec_dev_set_out_vol(s_spk, 75);
    esp_codec_dev_set_in_gain(s_mic, 33.0);

    srmodel_list_t *models = esp_srmodel_init("model");
    afe_config_t *cfg = afe_config_init("M", models, AFE_TYPE_SR, AFE_MODE_LOW_COST);
    cfg->aec_init = false;          // half duplex (see feed_task)
    cfg->vad_init = true;
    cfg->vad_mode = VAD_MODE_3;
    cfg->vad_min_noise_ms = 400;
    cfg->wakenet_init = true;
    cfg->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    cfg->afe_perferred_core = 1;
    s_afe = esp_afe_handle_from_config(cfg);
    s_afe_data = s_afe->create_from_config(cfg);
    afe_config_free(cfg);

    s_play_buf = xStreamBufferCreateWithCaps(PLAY_BUF_BYTES, 1, MALLOC_CAP_SPIRAM);
    xTaskCreatePinnedToCore(feed_task, "afe_feed", 4096, NULL, 6, NULL, 0);
    xTaskCreatePinnedToCore(fetch_task, "afe_fetch", 6144, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(play_task, "play", 4096, NULL, 7, NULL, 0);
}
