// SPDX-License-Identifier: MIT
#pragma once
#include "app_config.h"

// Returns >0 if version a > b ("x.y.z").
int ota_version_cmp(const char *a, const char *b);
// Download + install firmware from the gateway over mTLS, then reboot. Runs in its own task.
// With Secure Boot V2 the image signature is verified before it can ever boot.
void ota_start(const app_config_t *cfg, const char *path);
// Call once the new firmware proved it works (connected to the gateway): cancels rollback.
void ota_mark_valid(void);
