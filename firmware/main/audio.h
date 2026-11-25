// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Starts microphone capture + AFE (wake word "Hi ESP" + VAD) and the speaker task.
void audio_start(void);

// Open a listening window: audio is streamed to the gateway until VAD end-of-speech,
// `no_speech_ms` without speech, or 12 s max. Posts EV_LISTEN_END when done.
void audio_listen(uint32_t no_speech_ms);
void audio_stop_listening(void);
bool audio_is_listening(void);

// Text-to-speech playback (PCM s16le mono 16 kHz). Posts EV_PLAYBACK_DONE after audio_play_end().
void audio_play_begin(void);
void audio_play_write(const uint8_t *data, size_t len);
void audio_play_end(void);
void audio_play_abort(void);
