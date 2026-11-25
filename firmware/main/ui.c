// SPDX-License-Identifier: MIT
// Minimal, high-contrast UI designed for older adults: large status line, short text,
// and a red border that is ON whenever the microphone is streaming (visual privacy indicator).
#include "ui.h"

#include "app.h"
#include "bsp/esp-box-3.h"
#include "esp_timer.h"
#include "lvgl.h"

#define RESET_HOLD_MS 10000

static lv_obj_t *s_frame, *s_status, *s_text, *s_hint;
static int64_t s_press_started;
static bool s_reset_sent;

static void on_touch(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_PRESSED) {
        s_press_started = esp_timer_get_time();
        s_reset_sent = false;
    } else if (code == LV_EVENT_PRESSING) {
        int64_t held = (esp_timer_get_time() - s_press_started) / 1000;
        if (held > 3000 && !s_reset_sent) {
            lv_label_set_text_fmt(s_hint, "Reset tra %d s...", (int)((RESET_HOLD_MS - held) / 1000) + 1);
        }
        if (held >= RESET_HOLD_MS && !s_reset_sent) {
            s_reset_sent = true;
            app_post(EV_FACTORY_RESET, NULL);
        }
    } else if (code == LV_EVENT_SHORT_CLICKED) {
        app_post(EV_TAP, NULL);
    } else if (code == LV_EVENT_RELEASED) {
        lv_label_set_text(s_hint, "");
    }
}

void ui_start(void)
{
    bsp_display_start();
    bsp_display_backlight_on();
    bsp_display_lock(0);
    lv_obj_t *scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);

    s_frame = lv_obj_create(scr);
    lv_obj_set_size(s_frame, BSP_LCD_H_RES, BSP_LCD_V_RES);
    lv_obj_center(s_frame);
    lv_obj_set_style_bg_color(s_frame, lv_color_black(), 0);
    lv_obj_set_style_border_width(s_frame, 0, 0);
    lv_obj_set_style_radius(s_frame, 0, 0);
    lv_obj_clear_flag(s_frame, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(s_frame, on_touch, LV_EVENT_ALL, NULL);

    s_status = lv_label_create(s_frame);
    lv_obj_set_style_text_font(s_status, &lv_font_montserrat_28, 0);
    lv_obj_set_style_text_color(s_status, lv_color_white(), 0);
    lv_obj_align(s_status, LV_ALIGN_TOP_MID, 0, 6);

    s_text = lv_label_create(s_frame);
    lv_obj_set_width(s_text, BSP_LCD_H_RES - 40);
    lv_label_set_long_mode(s_text, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_font(s_text, &lv_font_montserrat_20, 0);
    lv_obj_set_style_text_color(s_text, lv_color_hex(0xE0E0E0), 0);
    lv_obj_set_style_text_align(s_text, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(s_text, LV_ALIGN_CENTER, 0, 10);

    s_hint = lv_label_create(s_frame);
    lv_obj_set_style_text_font(s_hint, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_color(s_hint, lv_color_hex(0x9E9E9E), 0);
    lv_obj_align(s_hint, LV_ALIGN_BOTTOM_MID, 0, -4);
    lv_label_set_text(s_hint, "");
    bsp_display_unlock();
    ui_set_state(UI_BOOT, NULL);
}

void ui_set_state(ui_state_t state, const char *detail)
{
    static const struct {
        const char *title;
        uint32_t color;
        const char *text;
    } screens[] = {
        [UI_BOOT] = {"Moody", 0xFFFFFF, "Avvio..."},
        [UI_PROVISIONING] = {"Configurazione", 0xFFC107, "Collega il cavo USB al computer ed esegui provision.py"},
        [UI_CONNECTING] = {"Connessione", 0xFFC107, "Mi sto collegando..."},
        [UI_IDLE] = {"Moody", 0x81C784, "Di' \"Hi ESP\" oppure tocca lo schermo"},
        [UI_LISTENING] = {"Ti ascolto", 0xEF5350, ""},
        [UI_THINKING] = {"Ci penso...", 0x64B5F6, NULL},
        [UI_SPEAKING] = {"Moody", 0x81C784, NULL},
        [UI_ERROR] = {"Problema", 0xEF5350, "Riprova tra poco"},
    };
    bsp_display_lock(0);
    lv_label_set_text(s_status, screens[state].title);
    lv_obj_set_style_text_color(s_status, lv_color_hex(screens[state].color), 0);
    // Red border == microphone streaming to the gateway.
    lv_obj_set_style_border_width(s_frame, state == UI_LISTENING ? 8 : 0, 0);
    lv_obj_set_style_border_color(s_frame, lv_color_hex(0xE53935), 0);
    if (detail) {
        lv_label_set_text(s_text, detail);
    } else if (screens[state].text) {
        lv_label_set_text(s_text, screens[state].text);
    }
    bsp_display_unlock();
}

void ui_set_text(const char *text)
{
    bsp_display_lock(0);
    lv_label_set_text(s_text, text ? text : "");
    bsp_display_unlock();
}
