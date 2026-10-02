#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <OneButton.h>

#include "imu.hpp"
#include "tof.hpp"
#include "batt.hpp"
#include "config.hpp"

	static const uint8_t robomarvel_text_bits[120] = {
  		0xFF, 0xFC, 0xFD, 0xF3, 0xF7, 0xDE, 0xDF, 0xBF, 0xF7, 0xFF, 0x1F, 0x00, 
		0x81, 0x07, 0x07, 0x1E, 0x9C, 0x73, 0x70, 0xE0, 0x9C, 0x01, 0x33, 0x00, 
		0x39, 0x73, 0xE6, 0xCC, 0x19, 0x31, 0x67, 0xCE, 0x9C, 0xF9, 0x33, 0x00, 
  		0x39, 0x73, 0xE6, 0xCC, 0x19, 0x30, 0x67, 0xCE, 0x9C, 0xF9, 0x33, 0x00, 
  		0x81, 0x73, 0x06, 0xCE, 0x99, 0x32, 0x67, 0xE0, 0x9C, 0x81, 0x33, 0x00, 
  		0x39, 0x73, 0xE6, 0xCC, 0x99, 0x33, 0x60, 0xCE, 0xC9, 0xF9, 0x33, 0x00, 
 		0x39, 0x73, 0xE6, 0xCC, 0x99, 0x33, 0x67, 0xCE, 0xE3, 0xF9, 0xF3, 0x01, 
  		0x39, 0x07, 0x07, 0x1E, 0x9C, 0x33, 0x67, 0xCE, 0xF6, 0x01, 0x03, 0x03, 
  		0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x7C, 0xFF, 0xFF, 0x03, 
  		0xDE, 0xFB, 0xFB, 0xE7, 0xEF, 0xFD, 0xFB, 0xF7, 0x38, 0xFE, 0xFF, 0x03, 
  	};
class Screen {
public:
	enum class Page {
		BOOT,
		MENU,
		INFO,
		SENSOR,
		ENERGY,
		DO,
		MODEM
	};

	enum class HostAct : uint8_t {
		NONE,
		RESTART,
		OFF,
		MODEM_ON,
		MODEM_OFF
	};

	HostAct takeHostAct() {
		HostAct act = host_act_;
		host_act_ = HostAct::NONE;
		return act;
	}

	Screen(TwoWire& wire, SemaphoreHandle_t& wireMutex, uint8_t address, uint8_t btnA, uint8_t btnB, Imu& imu, Tof& tof, Ina& ina) : wire_(wire), wireMutex_(wireMutex), address_(address), btnA_(btnA), btnB_(btnB), button_one_(btnA, true), button_two_(btnB, true), imu_(imu), tof_(tof), ina_(ina), u8g2_(U8G2_R0, U8X8_PIN_NONE) {
		instance_ = this;
	}

	bool initScreen() {
		SCREEN_INIT_OK_ = false;

		if (!i2cCheck(wire_, address_)) {
			return false;
		}
    		pinMode(btnA_, INPUT);
    		pinMode(btnB_, INPUT);
    
    		u8g2_.begin();
    		u8g2_.clearBuffer();
    		u8g2_.setDrawColor(1);
		u8g2_.setDrawColor(1);

u8g2_.firstPage();

do {
    u8g2_.drawBox(
        0,
        0,
        u8g2_.getDisplayWidth(),
        u8g2_.getDisplayHeight()
    );
} while (u8g2_.nextPage());
		//u8g2_.drawBox(0, 0, u8g2_.getDisplayWidth(), u8g2_.getDisplayHeight());
    		//u8g2_.sendBuffer();
		
		button_one_.attachClick(
			buttonOneClickCallback
		);

		button_two_.attachClick(
			buttonTwoClickCallback
		);

		button_one_.attachLongPressStart(
            		buttonOneLongCallback
        	);

        	button_two_.attachLongPressStart(
            		buttonTwoLongCallback
        	);

		SCREEN_INIT_OK_ = true;
		return SCREEN_INIT_OK_;
	}

	void updateScreen() {
    		uint8_t counter = 0;
    
    		while (true) {
			if (page_ == Page::BOOT) {
				if (millis() - last_boot_sensors_ >= BOOT_SENSOR_SWITCH_MS) {
					last_boot_sensors_ = millis();
					boot_sensor_++;
					screen_dirty_ = true;
					updateNetwork();
				}
			}
			if (page_ == Page::INFO) {
				uint8_t old_network = curr_network_;

				updateNetwork();

				if (curr_network_ != old_network) {
					screen_dirty_ = true;
				}
			}

			if (page_ == Page::ENERGY) {
				if (millis() - last_energy_ >= ENERGY_UPDATE_MS) {
					last_energy_ = millis();
					screen_dirty_ = true;
				}
			}

			if (host_connected_ && millis() - last_host_packet_ >= HOST_TIMEOUT_MS) {
				host_connected_ = false;

				if (page_ == Page::INFO) {
					screen_dirty_ = true;
				}
			}

			if (screen_dirty_) {
				screen_dirty_ = false;


			u8g2_.firstPage();
			do {
        		u8g2_.setFont(u8g2_font_profont12_mf);
			
			switch (page_) {
				case Page::BOOT:
					drawBoot();
					break;
				case Page::MENU:
					drawMenu();
					break;
				case Page::INFO:
					drawInfo();
					break;
				case Page::SENSOR:
					drawSensors();
					break;
				case Page::ENERGY:
					drawEnergy();
					break;
				case Page::DO:
					drawTests();
					break;
				case Page::MODEM:
					drawModem();
					break;
			}

			if (xSemaphoreTake(wireMutex_, pdMS_TO_TICKS(5)) == pdTRUE) {
        			bool more_pages = u8g2_.nextPage();

				xSemaphoreGive(wireMutex_);
				if (!more_pages) {
					break;
				}
			}
			} while (true);
			}

        		vTaskDelay(pdMS_TO_TICKS(5));
    		}
	}

	void updateButton() {
		while (true) {
			button_one_.tick();
			button_two_.tick();
			if (page_ == Page::BOOT) {
				if (button_one_click_ || button_two_click_) {
					page_ = Page::MENU;
					screen_dirty_ = true;

					button_one_click_ = false;
					button_two_click_ = false;
				}
			}

			//if (button_one_long_check_ && button_two_long_check_) {
			//	esp_restart();
			//}

			if (button_one_click_ && !button_two_click_) {
				if (page_ == Page::MENU) {
					if (selected_ == 0) {
						selected_ = MENU_ITEMS - 1;
					} else {
						selected_--;
					}

					screen_dirty_ = true;
				}

				if (page_ == Page::DO) {
					if (do_selected_ == 0) {
						do_selected_ = DO_ITEMS - 1;
					} else {
						do_selected_--;
					}
					screen_dirty_ = true;
				}

				if (page_ == Page::MODEM) {
					modem_selected_ = 0;
					screen_dirty_ = true;
				}

				button_one_click_ = false;
			}

			if (!button_one_click_ && button_two_click_) {
				if (page_ == Page::MENU) {
					selected_++;
					if (selected_ >= MENU_ITEMS) {
						selected_ = 0;
					}
					screen_dirty_ = true;
				}


				if (page_ == Page::DO) {
					do_selected_++;
					if (do_selected_ >= DO_ITEMS) {
						do_selected_ = 0;
					}
					screen_dirty_ = true;
				}

				if (page_ == Page::MODEM) {
					modem_selected_ = 1;
					screen_dirty_ = true;
				}
				button_two_click_ = false;
			}

			if (button_one_long_check_ && !button_two_long_check_) {
				if (page_ == Page::MENU) {
					switch (selected_) {
						case 0:
							page_ = Page::INFO;
							break;
						case 1:
							page_ = Page::MODEM;
							modem_selected_ = 0;
							screen_dirty_ = true;
							break;
						case 2:
							esp_restart();
							break;
						case 3:
							host_act_ = HostAct::RESTART;
							break;
					}

					screen_dirty_ = true;
				} else if (page_ == Page::DO) {
					if (do_selected_ == 0) {
						esp_restart();
					} else if (do_selected_ == 1) {
						page_ = Page::MODEM;
						modem_selected_ = 0;
						modem_enabled_ = 0;
						screen_dirty_ = true;
					} else if (do_selected_ == 2) {
						host_act_ = HostAct::RESTART;
					} else if (do_selected_ == 3) {
						host_act_ = HostAct::OFF;
					}
					screen_dirty_ = true;
				} else if (page_ == Page::MODEM) {
					if (modem_selected_ == 0) {
						host_act_ = HostAct::MODEM_ON;
					} else {
						host_act_ = HostAct::MODEM_OFF;
					}
				} 
				button_one_long_check_ = false;
			}

			if (!button_one_long_check_ && button_two_long_check_) {
				if (page_ == Page::MENU) {
					page_ = Page::BOOT;
					screen_dirty_ = true;
				} else if (page_ == Page::MODEM) {
					page_ = Page::MENU;
					screen_dirty_ = true;
				} else if (page_ != Page::MENU) {
					page_ = Page::MENU;
					screen_dirty_ = true;
				}
				button_two_long_check_ = false;
			}

			vTaskDelay(pdMS_TO_TICKS(5));
		}
	}

	void setNetworkInfo(uint8_t idx, const char* name, const char* ip) {
		if (idx >= 3) {
			return;
		}

		 memcpy(host_info_.networks[idx].name, name, 8);
		 host_info_.networks[idx].name[8] = '\0';

		 memcpy(host_info_.networks[idx].ip, ip, 15);
		 host_info_.networks[idx].ip[15] = '\0';

		 if (page_ == Page::INFO) {
			screen_dirty_ = true;
		}
	}

	void setHostLoad(float mem, float cpu, float npu, float temp) {
		host_info_.hostload.mem = mem;
		host_info_.hostload.cpu = cpu;
		host_info_.hostload.npu = npu;
		host_info_.hostload.temp = temp;
		
		last_host_packet_ = millis();
		host_connected_ = true;

		if (page_ == Page::INFO) {
			screen_dirty_ = true;
		}
	}

	bool isInit() const {
		return SCREEN_INIT_OK_;
	}

	static void screenTask(void* arg) {
		Screen* screen = static_cast<Screen*>(arg);
		screen->updateScreen();
	}

	static void buttonTask(void* arg) {
		Screen* screen = static_cast<Screen*>(arg);
		screen->updateButton();
	}
private:

	static constexpr uint8_t MENU_ITEMS = 4;
	static constexpr uint8_t DO_ITEMS = 4;

	struct DisplayNetwork {
		char name[9];
		char ip[16];
	};

	struct __attribute__((packed)) HostLoad {
		float mem;
		float cpu;
		float npu;
		float temp;
	};

	struct HostInfo {
		DisplayNetwork networks[3];
		HostLoad hostload;
	};

	HostInfo host_info_{};

	void updateNetwork() {
		if (millis() - last_network_ < NETWORK_SWITCH_MS) {
			return;
		}

		last_network_ = millis();

		for (uint8_t i = 0; i < 3; ++i) {
			curr_network_ = (curr_network_ + 1) % 3;

			if (host_info_.networks[curr_network_].name[0] != '\0') {
				return;
			}
		}
	}

	volatile Page page_ = Page::BOOT;
	volatile uint8_t selected_ = 0;
	volatile HostAct host_act_ = HostAct::NONE;
	volatile uint8_t do_selected_ = 0;

	volatile uint8_t modem_selected_ = 0;
	bool modem_enabled_ = false;

	void drawMenu() {
		const char* items[MENU_ITEMS] = {
			"hardware info",
			"hotspot mode",
			"reboot mcu",
			"reboot host"
		};

		for (uint8_t i = 0; i < MENU_ITEMS; ++i) {
			const int y = i * 16;

			if (i == selected_) {
				u8g2_.setDrawColor(1);
				u8g2_.drawBox(0, y, 128, 16);

				u8g2_.setDrawColor(0);
				u8g2_.setCursor(5, y + 12);
				u8g2_.print(items[i]);
				u8g2_.setDrawColor(1);
			} else {
				u8g2_.setDrawColor(1);
				u8g2_.setCursor(5, y + 12);
				u8g2_.print(items[i]);
			}
		}
	}

	//0 убрать надо будет проверять какая из них активная, условным не пустым именем
	void drawInfo() {
		//updateNetwork();
		if (!host_connected_) {
			u8g2_.setCursor(0, 28);
        		u8g2_.print("Host not connected");
        		return;
		}


		u8g2_.setCursor(0, 12);
        	u8g2_.print(host_info_.networks[curr_network_].name);
		u8g2_.print(": ");
		u8g2_.print(host_info_.networks[curr_network_].ip);

        	u8g2_.setCursor(0, 28);
        	u8g2_.print("CPU:");
        	u8g2_.print(host_info_.hostload.cpu, 0);
		u8g2_.print("%");

        	u8g2_.setCursor(0, 44);
        	u8g2_.print("Ram: ");
		u8g2_.print(host_info_.hostload.mem, 0);
		u8g2_.print("%");

        	u8g2_.setCursor(0, 60);
		u8g2_.print("T: ");
        	u8g2_.print(host_info_.hostload.temp, 0);
		u8g2_.print(" NPU:");
		u8g2_.print(host_info_.hostload.npu, 0);
		u8g2_.print("%");
	}

	void drawSensors() {
		u8g2_.setCursor(0, 12);
		u8g2_.print("Sensors");

		u8g2_.setCursor(0, 28);
		u8g2_.print("IMU: ");
		u8g2_.print(imu_.isInit() ? "OK" : "NONE");

		u8g2_.setCursor(0, 44);
		u8g2_.print("ToF: ");
		u8g2_.print(tof_.isInit() ? "OK" : "NONE");

		u8g2_.setCursor(0, 60);
		u8g2_.print("INA: ");
		u8g2_.print(ina_.isInit() ? "OK" : "NONE");
	}

	void drawEnergy() {
		const auto& bat = ina_.getState();
		
		u8g2_.setCursor(0, 12);
		u8g2_.print("Energy");

		u8g2_.setCursor(0, 28);
		u8g2_.print("V: ");
		u8g2_.print(bat.voltage, 2);
		u8g2_.print(" V");

		u8g2_.setCursor(0, 44);
		u8g2_.print("I: ");
		u8g2_.print(bat.current, 1);
		u8g2_.print(" mA");

		u8g2_.setCursor(0, 60);
		u8g2_.print("SOC: ");
		u8g2_.print(bat.percent, 1);
		u8g2_.print("%");
	}

	void drawTests() {
		const char* items[DO_ITEMS] = {
			"Restart FW",
			"Modem",
			"Restart",
			"Off"
		};

		for (uint8_t i = 0; i < DO_ITEMS; ++i) {
			const int y = i * 16;

			if (i == do_selected_) {
				u8g2_.setDrawColor(1);
				u8g2_.drawBox(0, y, 128, 16);

				u8g2_.setDrawColor(0);
				u8g2_.setCursor(5, y + 12);
				u8g2_.print(items[i]);

				u8g2_.setDrawColor(1);
			} else {
				u8g2_.setDrawColor(1);
				u8g2_.setCursor(5, y + 12);
				u8g2_.print(items[i]);
			}
		}
	}

	void drawModem() {
		u8g2_.setCursor(0, 12);
		u8g2_.print("Network: RDK-X5");
		u8g2_.setCursor(0, 28);
		u8g2_.print("Password: robomarvel");
		u8g2_.setCursor(0, 42);
		u8g2_.print("IP: 10.10.10.10");

		if (modem_selected_ == 0) {
			u8g2_.drawBox(10, 47, 45, 16);
        		u8g2_.setDrawColor(0);
        		u8g2_.setCursor(20, 59);
        		u8g2_.print("ON");
        		u8g2_.setDrawColor(1);

        		u8g2_.setCursor(85, 59);
        		u8g2_.print("OFF");
		} else {
			u8g2_.setCursor(20, 59);
        		u8g2_.print("ON");
        		u8g2_.drawBox(75, 47, 45, 16);
        		u8g2_.setDrawColor(0);
        		u8g2_.setCursor(85, 59);
        		u8g2_.print("OFF");
        		u8g2_.setDrawColor(1);
		}
	}

	void drawCentered(const char* text, int y) {
		int width = u8g2_.getStrWidth(text);
		int x = (u8g2_.getDisplayWidth() - width) / 2;

		u8g2_.drawStr(x, y, text);
	}

	void drawBoot() {
		u8g2_.setFontMode(1);
		u8g2_.setFont(u8g2_font_haxrcorp4089_tr);
		u8g2_.drawXBMP(19, 8, 90, 10, robomarvel_text_bits);
		char text[32];
		bool imu_ok = imu_.isInit();
		bool tof_ok = tof_.isInit();
		bool ina_ok = ina_.isInit();

		if (imu_ok && tof_ok && ina_ok) {
			snprintf(text, sizeof(text), "%s :: All sensors OK", config.robot_id);
		} else {
			uint8_t failed[3];
        		uint8_t failed_count = 0;

        		if (!imu_ok) failed[failed_count++] = 0;
        		if (!tof_ok) failed[failed_count++] = 1;
        		if (!ina_ok) failed[failed_count++] = 2;

        		if (boot_sensor_ >= failed_count) {
            			boot_sensor_ = 0;
        		}

        		if (failed[boot_sensor_] == 0) {
            			snprintf(text, sizeof(text), "%s :: IMU init fail", config.robot_id);
        		} else if (failed[boot_sensor_] == 1) {
            			snprintf(text, sizeof(text), "%s :: TOF init fail", config.robot_id);
        		} else {
            			snprintf(text, sizeof(text), "%s :: INA init fail", config.robot_id);
        		}
		}

		drawCentered(text, 31);
    
		if (!host_connected_) {
			//u8g2_.setCursor(0, 28);
        		//u8g2_.print("Host not connected");
			snprintf(text, sizeof(text), "Host not connected");
		} else {
			snprintf(text, sizeof(text), "%s: %s", host_info_.networks[curr_network_].name, host_info_.networks[curr_network_].ip);
		}

		drawCentered(text, 44);

		const auto& bat = ina_.getState();

		if (bat.current < 0) {
			snprintf(text,sizeof(text), "battery: %.0f%% %.1fV", bat.percent, bat.voltage);
		} else {
			snprintf(text,sizeof(text), "charging: %.0f%% %.1fV", bat.percent, bat.voltage);
		}

		drawCentered(text, 56);
	}


	void drawAnimation() {

		     int pupil_x = 0;
    int pupil_y = 0;

    bool blink = false;

    if (boot_frame_ <= 3) {
        pupil_x = -8;
    }
    else if (boot_frame_ <= 7) {
        pupil_x = 0;
    }
    else if (boot_frame_ <= 11) {
        pupil_x = 8;
    }
    else if (boot_frame_ <= 14) {
        pupil_x = 0;
    }
    else if (boot_frame_ <= 16) {
        blink = true;
    }

    if (blink) {
        u8g2_.drawBox(10, 30, 45, 5);
        u8g2_.drawBox(73, 30, 45, 5);

        u8g2_.drawLine(15, 24, 48, 21);
        u8g2_.drawLine(80, 21, 113, 24);

        return;
    }


    u8g2_.drawFrame(8, 12, 48, 40);

    u8g2_.drawFrame(72, 12, 48, 40);

    u8g2_.drawBox(
        28 + pupil_x,
        24 + pupil_y,
        10,
        16
    );

    u8g2_.drawBox(
        92 + pupil_x,
        24 + pupil_y,
        10,
        16
    );

    if (boot_frame_ % 2 == 0) {
        u8g2_.drawBox(60, 55, 3, 3);
        u8g2_.drawBox(65, 55, 3, 3);
    } else {
        u8g2_.drawBox(60, 55, 8, 3);
    }

    		//boot_frame_++;
	}

	bool i2cCheck(TwoWire& bus, uint8_t address) {
        	bus.beginTransmission(address);
        	return bus.endTransmission() == 0;
    	}

	static void buttonOneClickCallback() {
        	if (instance_ != nullptr) {
            		instance_->button_one_click_ = true;
        	}
    	}


    	static void buttonTwoClickCallback() {
        	if (instance_ != nullptr) {
            		instance_->button_two_click_ = true;
        	}
    	}

    	static void buttonOneLongCallback() {
        	if (instance_ != nullptr) {
            		instance_->button_one_long_check_ = true;
        	}
    	}


    	static void buttonTwoLongCallback() {
        	if (instance_ != nullptr) {
            		instance_->button_two_long_check_ = true;
        	}
    	}


    	TwoWire& wire_;
    	SemaphoreHandle_t& wireMutex_;

    	uint8_t address_;

    	uint8_t btnA_;
    	uint8_t btnB_;


    	U8G2_SSD1306_128X64_NONAME_1_HW_I2C u8g2_;

    	OneButton button_one_;
    	OneButton button_two_;


    	Imu& imu_;
    	Tof& tof_;
    	Ina& ina_;


    	bool SCREEN_INIT_OK_ = false;

	volatile bool screen_dirty_ = true;
	
	volatile bool button_one_click_ = false;
	volatile bool button_two_click_ = false;
    	volatile bool button_one_long_check_ = false;
    	volatile bool button_two_long_check_ = false;

    	volatile uint8_t check_1_ = 0;
    	volatile uint8_t check_2_ = 0;
	
	static constexpr uint32_t NETWORK_SWITCH_MS = 3000;
	uint8_t curr_network_ = 0;
	uint32_t last_network_ = 0;
	
    	inline static Screen* instance_ = nullptr;

	static constexpr uint32_t ENERGY_UPDATE_MS = 500;
	uint32_t last_energy_ = 0;

	static constexpr uint32_t HOST_TIMEOUT_MS = 5000;
	uint32_t last_host_packet_ = 0;
	bool host_connected_ = false;

	static constexpr uint32_t BOOT_FRAME_MS = 120;
	uint8_t boot_frame_ = 0;
	uint32_t last_bool_frame_ = 0;

	uint8_t boot_sensor_ = 0;
	uint32_t last_boot_sensors_ = 0;
	static constexpr uint32_t BOOT_SENSOR_SWITCH_MS = 1000;
};
