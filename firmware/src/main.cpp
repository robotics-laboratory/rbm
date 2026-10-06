#include <Arduino.h>
#include <Wire.h>
#include <esp_log.h>
#include <stdarg.h>

#include "config.hpp"
#include "motor.hpp"
#include "imu.hpp"
#include "tof.hpp"
#include "batt.hpp"
#include "screen.hpp"
#include "led.hpp"
#include "proto.hpp"

Proto* log_proto = nullptr;

int logV(const char* format, va_list args) {
	char message[192];

	int len = vsnprintf(message, sizeof(message), format, args);

	if (log_proto != nullptr) {
		log_proto->sendLog(message);
	}
	return len;
}

void resetI2C(int sda_pin, int scl_pin) {
    pinMode(scl_pin, OUTPUT_OPEN_DRAIN);
    pinMode(sda_pin, OUTPUT_OPEN_DRAIN);
    digitalWrite(scl_pin, HIGH);
    digitalWrite(sda_pin, HIGH);
    delayMicroseconds(5);

    for (int i = 0; i < 9; i++) {
        digitalWrite(scl_pin, LOW);
        delayMicroseconds(5);
        digitalWrite(scl_pin, HIGH);
        delayMicroseconds(5);
    }

    digitalWrite(sda_pin, LOW);
    delayMicroseconds(5);
    digitalWrite(scl_pin, HIGH);
    delayMicroseconds(5);
    digitalWrite(sda_pin, HIGH);
    delayMicroseconds(5);
	
    pinMode(scl_pin, INPUT);
    pinMode(sda_pin, INPUT);
    delayMicroseconds(50);
}

void setup() {
	Serial.begin(921600);
	while (!Serial) delay(10);

	resetI2C(21, 22);
	Wire.begin(21, 22);
	Wire.setClock(400000);

	resetI2C(33, 32);
	static TwoWire TOF_I2C(1);
	TOF_I2C.begin(33, 32, 1000000);

	static SemaphoreHandle_t wireMutex = xSemaphoreCreateMutex();

	if (wireMutex == nullptr) {
		while (true) {
	    		delay(1000);
		}
    	}

	loadConfig();

	static Motors motors;
	static Imu imu(Wire, wireMutex, 0x69);
	static Tof tof(TOF_I2C, 0x29);
	static Ina ina(Wire, wireMutex, 0x41);
	static Screen screen(Wire, wireMutex, 0x3C, 25, 26, imu, tof, ina);
	static Led led;
	static Proto proto(Serial, motors, imu, tof, ina, screen);

	proto.initProto();
	log_proto = &proto;
	esp_log_set_vprintf(logV);

	motors.initMotors();
	screen.initScreen();
	ina.initIna();
	imu.initImu();
	tof.initToF();
	led.initLEDs();

	if (motors.isInit()) {
		xTaskCreatePinnedToCore(Motors::task, "motors", 2048, &motors, 1, NULL, 1);
	}

	if (imu.isInit()) {
		xTaskCreatePinnedToCore(Imu::task, "imu", 2048, &imu, 1, NULL, 1);
	}

	if (tof.isInit()) {
		xTaskCreatePinnedToCore(Tof::task, "tof", 2048, &tof, 1, NULL, 1);
	}
	if (ina.isInit()) {
		xTaskCreatePinnedToCore(Ina::task, "ina", 2048, &ina, 1, NULL, 1);
	}

	if (screen.isInit()) {
		xTaskCreatePinnedToCore(Screen::screenTask, "screen", 4096, &screen, 1, NULL, 1);
		xTaskCreatePinnedToCore(Screen::buttonTask, "button", 2048, &screen, 1, NULL, 1);
	}

	if (led.isInit()) {
		xTaskCreatePinnedToCore(Led::task, "leds", 2048, &led, 1, NULL, 1);
	}

	if (proto.isInit()) {
		xTaskCreatePinnedToCore(Proto::packTask, "pack_update", 2048, &proto, 1, NULL, 1);
		xTaskCreatePinnedToCore(Proto::packInTask, "PackInTask", 2048, &proto, 1, NULL, 1);
	}
}

void loop() {
}
