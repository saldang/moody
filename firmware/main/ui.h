// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>

typedef enum {
    UI_BOOT,
    UI_PROVISIONING,
    UI_CONNECTING,
    UI_IDLE,
    UI_LISTENING,
    UI_THINKING,
    UI_SPEAKING,
    UI_ERROR,
} ui_state_t;

void ui_start(void);                          // display + touch; taps post EV_TAP / EV_FACTORY_RESET
void ui_set_state(ui_state_t state, const char *detail);
void ui_set_text(const char *text);           // transcript / reply (ASCII, folded by the gateway)
