#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <ICM_20948.h>
#include <SparkFun_VL53L5CX_Library.h>
#include <math.h>

constexpr uint8_t IMU_ADDR = 0x69;
constexpr uint8_t TOF_ADDR = 0x29;
constexpr uint8_t SCREEN_ADDR = 0x3c;
constexpr uint8_t SCREEN_STATUS_ADDR = 0x3d;

constexpr uint8_t BUTTON_A = 25;
constexpr uint8_t BUTTON_B = 26;

TwoWire TOF_I2C(1);

ICM_20948_I2C imu;
SparkFun_VL53L5CX tof;
U8G2_SSD1306_128X64_NONAME_F_HW_I2C screen(U8G2_R0);
U8G2_SSD1306_128X64_NONAME_F_HW_I2C screenStatus(U8G2_R0);

VL53L5CX_ResultsData lidar_data;

bool checkImu = false;
bool checkTof = false;
bool checkScreen = false;

bool checkInitImu = false;
bool checkInitTof = false;
bool checkInitScreen = false;

bool checkWorkImu = false;
bool checkWorkTof= false;
bool checkWorkScreen = false;

bool buttonAPressed = false;
bool buttonBPressed = false;

uint32_t screenStart = 0;
bool screenTestFinished = false;

uint32_t lastCheck = 0;
uint32_t lastStatus = 0;

bool ping(TwoWire& wire, uint8_t address) {
  wire.beginTransmission(address);
  return wire.endTransmission() == 0;
}




bool initImu() {
  imu.begin(Wire, 1);
  return (imu.status == ICM_20948_Stat_Ok);
}

bool initTof() {
  bool meow = tof.begin(TOF_ADDR, TOF_I2C);

  if (meow) {
      meow = tof.setResolution(64);
  }
  if (meow) {
      meow = tof.setRangingFrequency(15);
  }
  if (meow) {
      meow = tof.startRanging();
  }
  return meow;
}

bool initScreen() {
    screen.setI2CAddress(SCREEN_ADDR << 1);
    screen.begin();

    buttonAPressed = false;
    buttonBPressed = false;
    screenTestFinished = false;

    screenStart = millis();

    screen.clearBuffer();
    screen.drawBox(0, 0, 128, 64);
    screen.sendBuffer();

    return true;
}

void setup() {
  Wire.begin(21, 22);
    Wire.setClock(400000);
    Wire.setTimeOut(50);

    TOF_I2C.begin(33, 32);
    TOF_I2C.setClock(400000);
    TOF_I2C.setTimeOut(50);

    pinMode(BUTTON_A, INPUT_PULLUP);
    pinMode(BUTTON_B, INPUT_PULLUP);

    screenStatus.setI2CAddress(SCREEN_STATUS_ADDR << 1);
    screenStatus.begin();

    screenStatus.clearBuffer();
    screenStatus.setFont(u8g2_font_6x13_tf);
    screenStatus.drawStr(0, 20, "Waiting for sensor");
    screenStatus.sendBuffer();
}

void loop() {
  uint32_t now = millis(); 
  if (now - lastCheck >= 500) {
    lastCheck = now;
    checkImu = ping(Wire, IMU_ADDR);
    checkTof = ping(TOF_I2C, TOF_ADDR);
    checkScreen = ping(Wire, SCREEN_ADDR);

    if (!checkImu) {
      checkInitImu = false;
      checkWorkImu = false;
    }

    if (!checkTof) {
      checkInitTof = false;
      checkWorkTof = false;
    }

    if (!checkScreen) {
      checkInitScreen = false;
      checkWorkScreen = false;
      screenTestFinished = false;
    }

    if (checkImu && !checkInitImu) {
      checkInitImu = initImu();
    } else if (checkTof && !checkInitTof) {
      checkInitTof = initTof();
    } else if (checkScreen && !checkInitScreen) {
      checkInitScreen = initScreen();
      checkWorkScreen = checkInitScreen;
    }
  }

    if (checkInitImu && !checkWorkImu) {
      if (imu.dataReady()) {
          imu.getAGMT();
          if (imu.status == ICM_20948_Stat_Ok) {
            checkWorkImu = true;
          }
      }
    }

    if (checkInitTof && !checkWorkTof) {
      if (tof.isDataReady()) {
        if (tof.getRangingData(&lidar_data)) {
          checkWorkTof = true;
        }
      }
    }

    if (checkInitScreen) {
      if (!screenTestFinished) {
        if (millis() - screenStart >= 3000) {
          screenTestFinished = true;
          screen.clearBuffer();
          screen.setFont(u8g2_font_6x13_tf);
          screen.drawStr(0, 20, "A: false");
          screen.drawStr(0, 40, "B: false");
          screen.sendBuffer();
        }
      } else {
        bool changed = false;

        if (digitalRead(BUTTON_A) == LOW && !buttonAPressed) {
          buttonAPressed = true;
          changed = true;
        }

        if (digitalRead(BUTTON_B) == LOW && !buttonBPressed) {
          buttonBPressed = true;
          changed = true;
        }
        if (changed) {
          screen.clearBuffer();
          screen.setFont(u8g2_font_6x13_tf);

          screen.setCursor(0, 20);
          screen.print("A: ");
          screen.print(buttonAPressed ? "true" : "false");
          screen.setCursor(0, 40);
          screen.print("B: ");
          screen.print(buttonBPressed ? "true" : "false");

          screen.sendBuffer();
        }
      }
    }

    if (now - lastStatus >= 200) {
      lastStatus = now;

        const char* name = "NONE";
        bool initialized = false;
        bool working = false;

        if (checkImu) {
            name = "IMU";
            initialized = checkInitImu;
            working = checkWorkImu;
        } else if (checkTof) {
            name = "ToF";
            initialized = checkInitTof;
            working = checkWorkTof;
        } else if (checkScreen) {
            name = "SCREEN";
            initialized = checkInitScreen;
            working = checkWorkScreen;
        }

        screenStatus.clearBuffer();
        screenStatus.setFont(u8g2_font_6x13_tf);
        screenStatus.drawStr(0, 12, name);

        screenStatus.setCursor(0, 28);
        screenStatus.print("INIT: ");
        screenStatus.print(initialized ? "OK" : "FAIL");

        screenStatus.setCursor(0, 43);
        screenStatus.print("DATA: ");
        screenStatus.print(working ? "OK" : "FAIL");

        screenStatus.setFont(u8g2_font_helvB12_tf);
        screenStatus.drawStr(
            0, 62,
            working ? "PASS" : "FAIL"
        );

        screenStatus.sendBuffer();
    }
     delay(10);
}
