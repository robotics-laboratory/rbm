#pragma once


#define CONFIG_VERSION 1
#define FIRMWARE_VERSION_DEFAULT 1
#include <nvs.h>

struct __attribute__((packed)) PIDConfigIn {
	float kp;
    	float ki;
    	float kd;
   	float limit;
    	float lpf_tf;
};

//struct MotorDir {
//    	bool motor_dir;
//    	bool encoder_dir;
//};

//struct __attribute__((packed)) MotorDirConfig {
//	MotorDir front_left;
//	MotorDir front_right;
//	MotorDir rear_left;
//	MotorDir rear_right;
//};

struct __attribute__((packed)) Dir {
	int8_t motor_one; // MotorDir front_left 
	//uint8_t front_left_enc_dir
	int8_t motor_two;
	int8_t motor_three;
	int8_t motor_four;
};

struct __attribute__((packed)) ConfigV1 {
	uint8_t config_ver;
	uint8_t firmware_ver;
	char robot_id[16];
	uint32_t encoder_cpr;
	PIDConfigIn pid;
	//MotorDirConfig motors;
	Dir direction_mot; // uint8_t
	Dir direction_enc;
};

constexpr ConfigV1 DEFAULT_CONFIG = { CONFIG_VERSION, FIRMWARE_VERSION_DEFAULT, "R4-Y0", 330, {0.5f, 5.0f, 0.001f, 500.0f, 0.01f}, {1, -1, 1, -1}, {1, -1, 1, -1} };

using Config = ConfigV1;

//constexpr Config DEFAULT_CONFIG = {
//		1,
//		1, 
//		"rbm-000",
//		330,
//		{0.5f, 5.0f, 0.001f, 500.0f, 0.01f},
//		{{true, true},
//		{false, false},
//		{true, true},
//		{false, false}},
//};


inline Config config = DEFAULT_CONFIG;

inline bool saveConfig() {
	nvs_handle_t handle;

	esp_err_t err = nvs_open("robot", NVS_READWRITE, &handle);
	if (err != ESP_OK) {
		return false;
	}

	err = nvs_set_u32(handle, "config_ver", CONFIG_VERSION);
	if (err != ESP_OK) {
		nvs_close(handle);
		return false;
	}

	err = nvs_set_blob(handle, "config", &config, sizeof(config));
	if (err == ESP_OK) {
		err = nvs_commit(handle);
	}

	nvs_close(handle);
	
	return err == ESP_OK;
}

inline bool loadConfig() {
	nvs_handle_t handle;

	esp_err_t err = nvs_open("robot", NVS_READONLY, &handle);
	if (err != ESP_OK) {
		config = DEFAULT_CONFIG;
		return false;
	}

	uint32_t stored_v = -1;
	err = nvs_get_u32(handle, "config_v", &stored_v);

	if (err != ESP_OK || stored_v != CONFIG_VERSION) {
		nvs_close(handle);

		config = DEFAULT_CONFIG;
		return false;
	}

	size_t size = sizeof(Config);

	err = nvs_get_blob(handle, "config", &config, &size);
	nvs_close(handle);

	if (err != ESP_OK || size != sizeof(Config)) {
		config = DEFAULT_CONFIG;
		return false;
	}
	return true;
}
