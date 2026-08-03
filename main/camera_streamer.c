/*
 * Working XIAO ESP32S3 OV3660 Camera Stream
 * Uses RGB565 format with JPEG conversion
 */

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "esp_http_server.h"
#include "esp_camera.h"
#include "driver/gpio.h"
#include "driver/i2s_pdm.h"
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#include "model_path.h"
#include "hiesp.h"



#include "pins.h"

//microphone setup
i2s_chan_handle_t rx_handle = NULL;


size_t bytes_read;
const int WAVE_HEADER_SIZE = 44;

#define SAMPLE_SIZE         (CONFIG_EXAMPLE_BIT_SAMPLE * 1024)
#define BYTE_RATE           (CONFIG_EXAMPLE_SAMPLE_RATE * (CONFIG_EXAMPLE_BIT_SAMPLE / 8)) * NUM_CHANNELS
#define NUM_CHANNELS        (1) // For mono recording only!

static int16_t i2s_readraw_buff[SAMPLE_SIZE];


static const char *TAG = "XIAO_CAM";
//softap configuration
#define EXAMPLE_ESP_WIFI_SSID      "esp32"
#define EXAMPLE_ESP_WIFI_PASS      "2udi62ppa78y"
#define EXAMPLE_ESP_WIFI_CHANNEL   7
#define EXAMPLE_MAX_STA_CONN       1

//WiFi Configuration - Set these in sdkconfig or here
#ifndef CONFIG_ESP_WIFI_SSID
#define CONFIG_ESP_WIFI_SSID  "ATT678zcD2"
#endif

#ifndef CONFIG_ESP_WIFI_PASSWORD
#define CONFIG_ESP_WIFI_PASSWORD "2udi62ppa78y"
#endif

// WiFi credentials from sdkconfig
#define ESP_WIFI_SSID      CONFIG_ESP_WIFI_SSID
#define ESP_WIFI_PASS      CONFIG_ESP_WIFI_PASSWORD
#define ESP_MAXIMUM_RETRY  5


static EventGroupHandle_t s_wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static int s_retry_num = 0;
static httpd_handle_t camera_httpd = NULL;

// Working OV3660 config
static camera_config_t camera_config = {
    .pin_pwdn     = -1,
    .pin_reset    = -1,
    .pin_xclk     = XIAO_CAM_PIN_XCLK,
    .pin_sccb_sda = XIAO_CAM_PIN_SIOD,
    .pin_sccb_scl = XIAO_CAM_PIN_SIOC,
    
    .pin_d7       = XIAO_CAM_PIN_D7,
    .pin_d6       = XIAO_CAM_PIN_D6,
    .pin_d5       = XIAO_CAM_PIN_D5,
    .pin_d4       = XIAO_CAM_PIN_D4,
    .pin_d3       = XIAO_CAM_PIN_D3,
    .pin_d2       = XIAO_CAM_PIN_D2,
    .pin_d1       = XIAO_CAM_PIN_D1,
    .pin_d0       = XIAO_CAM_PIN_D0,
    .pin_vsync    = XIAO_CAM_PIN_VSYNC,
    .pin_href     = XIAO_CAM_PIN_HREF,
    .pin_pclk     = XIAO_CAM_PIN_PCLK,
    
    .xclk_freq_hz = 20000000,
    .ledc_timer   = LEDC_TIMER_0,
    .ledc_channel = LEDC_CHANNEL_0,
    
    .pixel_format = PIXFORMAT_JPEG,     // Try JPEG first
    .frame_size   = FRAMESIZE_VGA,     // 800x600
    .jpeg_quality = 10,
    .fb_count     = 2,
    .fb_location  = CAMERA_FB_IN_PSRAM,
    .grab_mode    = CAMERA_GRAB_LATEST,
    .sccb_i2c_port = 1
};

// i2c microphone initialization
void init_microphone(void)
{
#if SOC_I2S_SUPPORTS_PDM2PCM
    ESP_LOGI(TAG, "Receive PDM microphone data in PCM format");
#else
    ESP_LOGI(TAG, "Receive PDM microphone data in raw PDM format");
#endif  // SOC_I2S_SUPPORTS_PDM2PCM
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, NULL, &rx_handle));

    i2s_pdm_rx_config_t pdm_rx_cfg = {
        .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(CONFIG_EXAMPLE_SAMPLE_RATE),
        /* The default mono slot is the left slot (whose 'select pin' of the PDM microphone is pulled down) */
#if SOC_I2S_SUPPORTS_PDM2PCM
        .slot_cfg = I2S_PDM_RX_SLOT_PCM_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
#else
        .slot_cfg = I2S_PDM_RX_SLOT_RAW_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
#endif
        .gpio_cfg = {
            .clk = CONFIG_EXAMPLE_I2S_CLK_GPIO,
            .din = CONFIG_EXAMPLE_I2S_DATA_GPIO,
            .invert_flags = {
                .clk_inv = false,
            },
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_pdm_rx_mode(rx_handle, &pdm_rx_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(rx_handle));
}


//wake word detection loop
bool wakeword_detection(void *){
     srmodel_list_t *models = esp_srmodel_init("model");
    char *model_name = esp_srmodel_filter(models, ESP_WN_PREFIX, "hiesp");
    esp_wn_iface_t *wakenet = (esp_wn_iface_t*)esp_wn_handle_from_name(model_name);
    model_iface_data_t *model_data = wakenet->create(model_name, DET_MODE_95);

    int audio_chunksize = wakenet->get_samp_chunksize(model_data) * sizeof(int16_t);
    int16_t *i2s_readraw_buff = (int16_t *) malloc(audio_chunksize);

    while (1) {
       i2s_channel_read(
            rx_handle,
            i2s_readraw_buff,
            sizeof(i2s_readraw_buff),
            &bytes_read,
            portMAX_DELAY);
        
        wakenet_state_t state = wakenet->detect(model_data, i2s_readraw_buff);
        if (state == WAKENET_DETECTED) {
            printf("Detected\n");
            break;
        }
    }

    wakenet->destroy(model_data);
    vTaskDelete(NULL);
    return 1;
}


// WiFi event handler
static void wifi_event_handler(void* arg, esp_event_base_t event_base,
                                int32_t event_id, void* event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retry_num < ESP_MAXIMUM_RETRY) {
            esp_wifi_connect();
            s_retry_num++;
            ESP_LOGI(TAG, "Retry connecting to WiFi (%d/%d)", s_retry_num, ESP_MAXIMUM_RETRY);
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "Got IP Address: " IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_num = 0;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}


// WiFi init
static void wifi_init_sta(void)
{
    s_wifi_event_group = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT,
                                                        ESP_EVENT_ANY_ID,
                                                        &wifi_event_handler,
                                                        NULL,
                                                        &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT,
                                                        IP_EVENT_STA_GOT_IP,
                                                        &wifi_event_handler,
                                                        NULL,
                                                        &instance_got_ip));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = ESP_WIFI_SSID,
            .password = ESP_WIFI_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "WiFi connecting to %s...", ESP_WIFI_SSID);

    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
            WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
            pdFALSE,
            pdFALSE,
            portMAX_DELAY);

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "Connected to WiFi");
    } else {
        ESP_LOGI(TAG, "Failed to connect to WiFi");
    }
}


/*
void wifi_init_softap(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT,
                                                        ESP_EVENT_ANY_ID,
                                                        &wifi_event_handler,
                                                        NULL,
                                                        NULL));

    wifi_config_t wifi_config = {
        .ap = {
            .ssid = EXAMPLE_ESP_WIFI_SSID,
            .ssid_len = strlen(EXAMPLE_ESP_WIFI_SSID),
            .channel = EXAMPLE_ESP_WIFI_CHANNEL,
            .password = EXAMPLE_ESP_WIFI_PASS,
            .max_connection = EXAMPLE_MAX_STA_CONN,
#ifdef CONFIG_ESP_WIFI_SOFTAP_SAE_SUPPORT
            .authmode = WIFI_AUTH_WPA3_PSK,
            .sae_pwe_h2e = WPA3_SAE_PWE_BOTH,
#else // CONFIG_ESP_WIFI_SOFTAP_SAE_SUPPORT 
            .authmode = WIFI_AUTH_WPA2_PSK,
#endif
            .pmf_cfg = {
                    .required = true,
            },
#ifdef CONFIG_ESP_WIFI_BSS_MAX_IDLE_SUPPORT
            .bss_max_idle_cfg = {
                .period = WIFI_AP_DEFAULT_MAX_IDLE_PERIOD,
                .protected_keep_alive = 1,
            },
#endif
            .gtk_rekey_interval = 0,
        },
    };
    if (strlen(EXAMPLE_ESP_WIFI_PASS) == 0 && wifi_config.ap.authmode != WIFI_AUTH_OWE) {
        wifi_config.ap.authmode = WIFI_AUTH_OPEN;
    }

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "wifi_init_softap finished. SSID:%s password:%s channel:%d",
             EXAMPLE_ESP_WIFI_SSID, EXAMPLE_ESP_WIFI_PASS, EXAMPLE_ESP_WIFI_CHANNEL);
}

*/
// Camera init
static esp_err_t init_camera(void)
{
    ESP_LOGI(TAG, "Initializing OV3660...");
    
    esp_err_t err = esp_camera_init(&camera_config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Camera init failed: 0x%x", err);
        return err;
    }
    
    sensor_t *s = esp_camera_sensor_get();
    // Camera settings
     s->set_brightness(s, 0);                 // -2 to 2
    s->set_contrast(s, 0);                   // -2 to 2
    s->set_saturation(s, 0);                 // -2 to 2
    s->set_special_effect(s, 0);             // 0 to 6 (0 - No Effect, 1 - Negative, 2 - Grayscale, 3 - Red Tint, 4 - Green Tint, 5 - Blue Tint, 6 - Sepia)
    s->set_whitebal(s, 1);                   // 0 = disable , 1 = enable
    s->set_awb_gain(s, 1);                   // 0 = disable , 1 = enable
    s->set_wb_mode(s, 0);                    // 0 to 4 - if awb_gain enabled (0 - Auto, 1 - Sunny, 2 - Cloudy, 3 - Office, 4 - Home)
    s->set_exposure_ctrl(s, 1);              // 0 = disable , 1 = enable
    s->set_aec2(s, 0);                       // 0 = disable , 1 = enable
    s->set_ae_level(s, 0);                   // -2 to 2
    s->set_aec_value(s, 300);                // 0 to 1200
    s->set_gain_ctrl(s, 1);                  // 0 = disable , 1 = enable
    s->set_agc_gain(s, 0);                   // 0 to 30
    s->set_gainceiling(s, (gainceiling_t)0); // 0 to 6
    s->set_bpc(s, 0);                        // 0 = disable , 1 = enable
    s->set_wpc(s, 1);                        // 0 = disable , 1 = enable
    s->set_raw_gma(s, 1);                    // 0 = disable , 1 = enable
    s->set_lenc(s, 1);                       // 0 = disable , 1 = enable
    s->set_hmirror(s, 0);                    // 0 = disable , 1 = enable
    s->set_vflip(s, 0);                      // 0 = disable , 1 = enable
    s->set_dcw(s, 1);                        // 0 = disable , 1 = enable
    s->set_colorbar(s, 0);                   // 0 = disable , 1 = enable
    
    ESP_LOGI(TAG, "✓ Camera initialized");
    return ESP_OK;
}



static esp_err_t stream_handler(httpd_req_t *req)
{
    camera_fb_t *fb = NULL;
    esp_err_t res = ESP_OK;
    bool onoff = 1;
    char part_buf[128];

    //init wakenet detection model
    srmodel_list_t *models = esp_srmodel_init("model");
    char *model_name = esp_srmodel_filter(models, ESP_WN_PREFIX, "hiesp");
    esp_wn_iface_t *wakenet = (esp_wn_iface_t*)esp_wn_handle_from_name(model_name);
    model_iface_data_t *model_data = wakenet->create(model_name, DET_MODE_95);
    int audio_chunksize = wakenet->get_samp_chunksize(model_data) * sizeof(int16_t);
    int16_t *i2s_readraw_buff = (int16_t *) malloc(audio_chunksize);

    // Set content type AND additional headers for Chrome
    httpd_resp_set_type(req, "multipart/x-mixed-replace; boundary=frame");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_set_hdr(req, "X-Framerate", "30");
    
    ESP_LOGI(TAG, "Video stream started");  // Add logging

    while (true) {
        while(onoff){
            i2s_channel_read(
            rx_handle,
            i2s_readraw_buff,
            audio_chunksize,
            &bytes_read,
            portMAX_DELAY);
        
            wakenet_state_t state = wakenet->detect(model_data, i2s_readraw_buff);
            if (state == WAKENET_DETECTED) {
                printf("Detected\n");
                onoff = 0;
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(1));
        }

        fb = esp_camera_fb_get();
        if (!fb) {
            ESP_LOGE(TAG, "Camera capture failed");
            break;
        }

        if (fb->format != PIXFORMAT_JPEG) {
            ESP_LOGE(TAG, "Non-JPEG format");
            esp_camera_fb_return(fb);
            break;
        }

        size_t hlen = snprintf(part_buf, 128,
                             "Content-Type: image/jpeg\r\n"
                             "Content-Length: %u\r\n"
                             "\r\n",
                             fb->len);
        
        res = httpd_resp_send_chunk(req, part_buf, hlen);
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, "\r\n--frame\r\n", 14);
        }

        
        esp_camera_fb_return(fb);

        if (res != ESP_OK) {
            ESP_LOGE(TAG, "Stream send failed");
            break;
        }
        
        vTaskDelay(pdMS_TO_TICKS(66));
    }

    ESP_LOGI(TAG, "Stream ended");
    return res;
}

/*
static esp_err_t audio_handler(httpd_req_t *req)
{
    

    // Set content type AND additional headers for Chrome
    httpd_resp_set_type(req, "audio/x-wav");

    const wav_header_t wav_header = WAV_HEADER_PCM_DEFAULT(
    0,
    16,
    16000,
    1);

    //send header
    httpd_resp_send_chunk(req, (char *)&wav_header, sizeof(wav_header));

    ESP_LOGI(TAG, "Audio stream started");  // Add logging

    while (1) {
            // Read the RAW samples from the microphone
            if (i2s_channel_read(rx_handle, (char *)i2s_readraw_buff, SAMPLE_SIZE, &bytes_read, 1000) == ESP_OK) {
                printf("[0] %d [1] %d [2] %d [3]%d ...\n", i2s_readraw_buff[0], i2s_readraw_buff[1], i2s_readraw_buff[2], i2s_readraw_buff[3]);
                httpd_resp_send_chunk(req, (char *)i2s_readraw_buff, bytes_read);
            } else {
                printf("Read Failed!\n");
            }
        }

    ESP_LOGI(TAG, "Stream ended");
    return httpd_resp_send_chunk(req, (char *)i2s_readraw_buff, 8192);
}
*/

static void audio_stream_task(void *arg)
{
    int fd = (int)arg;

    while (1)
    {
        esp_err_t err = i2s_channel_read(
            rx_handle,
            (char *)i2s_readraw_buff,
            sizeof(i2s_readraw_buff),
            &bytes_read,
            portMAX_DELAY
        );

        if (err != ESP_OK)
        {
            ESP_LOGE(TAG, "I2S read failed");
            break;
        }


        httpd_ws_frame_t ws_pkt = {
            .type = HTTPD_WS_TYPE_BINARY,
            .payload = (uint8_t *)i2s_readraw_buff,
            .len = bytes_read
        };


        err = httpd_ws_send_frame_async(
            camera_httpd,
            fd,
            &ws_pkt
        );

        if(err != ESP_OK)
        {
            ESP_LOGI(TAG,"Client disconnected");
            break;
        }
    }


    vTaskDelete(NULL);
}



static esp_err_t audio_handler(httpd_req_t *req)
{

    if (httpd_req_to_sockfd(req) < 0)
        return ESP_FAIL;


    int fd = httpd_req_to_sockfd(req);


    ESP_LOGI(TAG,"WebSocket connected");


    xTaskCreate(
        audio_stream_task,
        "audio_stream",
        4096,
        (void *)fd,
        5,
        NULL
    );


    return ESP_OK;
}

// Index handler
static esp_err_t index_handler(httpd_req_t *req)
{
    const char *html = 
        "<!DOCTYPE html><html><head>"
        "<meta name='viewport' content='width=device-width'>"
        "<title>XIAO Camera</title>"
        "<style>body{margin:0;text-align:center;background:#000}"
        "img{max-width:100%;height:auto}</style>"
        "</head><body>"
        /*"<h1 style='color:#fff'>XIAO ESP32S3 Camera</h1>"
        "<script>"
        "let ws = new WebSocket(\"ws://\" + location.host + \"/audio\");"
        ""
        "ws.binaryType = \"arraybuffer\";"
        ""
        "let audioCtx = new AudioContext({"
        "    sampleRate:16000"
        "});"
        ""
        "ws.onmessage = function(event)"
        "{"
        "    let pcm = new Int16Array(event.data);"
        ""
        "    let buffer = audioCtx.createBuffer("
        "        1,"
        "        pcm.length,"
        "        16000"
        "    );"
        ""
        "    let channel = buffer.getChannelData(0);"
        ""
        "    for(let i = 0; i < pcm.length; i++)"
        "    {"
        "        channel[i] = pcm[i] / 32768;"
        "    }"
        ""
        "    let source = audioCtx.createBufferSource();"
        ""
        "    source.buffer = buffer;"
        "    source.connect(audioCtx.destination);"
        "    source.start();"
        "};"
        "</script>"*/
        "<img id='stream' src='/stream'>"
        "</body></html>";
    
    return httpd_resp_send(req, html, HTTPD_RESP_USE_STRLEN);
}

// Start server
static void start_webserver(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();

    config.server_port = 80;
    config.ctrl_port = 32768;

    if (httpd_start(&camera_httpd, &config) == ESP_OK) {
        httpd_uri_t index_uri = {
            .uri = "/",
            .method = HTTP_GET,
            .handler = index_handler,
        };
        httpd_register_uri_handler(camera_httpd, &index_uri);

        httpd_uri_t stream_uri = {
            .uri = "/stream",
            .method = HTTP_GET,
            .handler = stream_handler,
        };
        httpd_register_uri_handler(camera_httpd, &stream_uri);
        /*
        httpd_uri_t audio_uri = {
            .uri = "/audio",
            .method = HTTP_GET,
            .handler = audio_handler,
            .is_websocket = true
        };
        httpd_register_uri_handler(camera_httpd, &audio_uri);*/

        ESP_LOGI(TAG, "✓ Web server started");
    }
}


void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  XIAO ESP32S3 Camera Stream");
    ESP_LOGI(TAG, "========================================");
    
    gpio_reset_pin(XIAO_LED_RGB_GPIO);
    gpio_set_direction(XIAO_LED_RGB_GPIO, GPIO_MODE_OUTPUT);
    
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);
    
    if (init_camera() != ESP_OK) {
        ESP_LOGE(TAG, "Camera failed!");
        return;
    }

    init_microphone();
    
    wifi_init_sta();
    start_webserver();
    
    ESP_LOGI(TAG, "✓ Ready! Open browser to your IP");
    
    while (1) {
        gpio_set_level(XIAO_LED_RGB_GPIO, 1);
        vTaskDelay(pdMS_TO_TICKS(500));
        gpio_set_level(XIAO_LED_RGB_GPIO, 0);
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}