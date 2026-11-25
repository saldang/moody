// SPDX-License-Identifier: MIT
#pragma once
// Blocking provisioning loop over the USB Serial/JTAG port. Never returns (reboots on COMMIT).
void provision_run(void);
