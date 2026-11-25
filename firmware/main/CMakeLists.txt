idf_component_register(
    SRCS "main.c" "app_config.c" "provision.c" "net.c" "link.c" "audio.c" "ui.c" "ota.c"
    INCLUDE_DIRS "."
    REQUIRES nvs_flash esp_wifi esp_netif esp_event esp_timer mbedtls json
             esp_driver_usb_serial_jtag bootloader_support esp_app_format
             esp_https_ota app_update esp_http_client
)
