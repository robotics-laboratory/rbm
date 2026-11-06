#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <SimpleDCMotor.h>
#include "sensors/MagneticSensorI2C.h"
#include "encoders/esp32hwencoder/ESP32HWEncoder.h"

DCDriver2PWM driver(13, 27);
ESP32HWEncoder encoder(19, 18, 10000);
MagneticSensorI2C as5600(AS5600_I2C);
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

float as5600_zero_offset = 0.0;

float as5600_get_angle() {
  return as5600.getAngle() - as5600_zero_offset;
}

void as5600_reset_angle() {
  as5600_zero_offset = as5600_get_angle();
}

int32_t encoder_get_ticks() {
  return static_cast<int32_t>(encoder.getAngle() / _2PI * 10000.0);
}

void show_status(const char *message) {
  u8g2.clearBuffer();
  u8g2.setDrawColor(1);
  u8g2.setFont(u8g2_font_logisoso24_tf);
  int text_width = u8g2.getStrWidth(message);
  int x = (128 - text_width) / 2;
  int text_ascent = u8g2.getAscent();
  int y = (64 + text_ascent) / 2;
  u8g2.drawStr(x, y, message);
  u8g2.sendBuffer();
}

void show_fail_err(const char *message) {
  u8g2.clearBuffer();
  u8g2.setDrawColor(1);
  u8g2.setFont(u8g2_font_logisoso24_tf);
  int text_width = u8g2.getStrWidth("FAIL");
  int x = (128 - text_width) / 2;
  int text_ascent = u8g2.getAscent();
  int y = (32 + text_ascent) / 2;
  u8g2.drawStr(x, y, "FAIL");
  u8g2.setFont(u8g2_font_profont12_mf);
  text_width = u8g2.getStrWidth(message);
  x = (128 - text_width) / 2;
  u8g2.drawStr(x, 50, message);
  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(921600);
  u8g2.begin();
  
  u8g2.clearBuffer();
  u8g2.setDrawColor(1);
  u8g2.drawBox(0, 0, 128, 64);
  u8g2.sendBuffer();
  delay(500);
  
  u8g2.clearBuffer();
  u8g2.setDrawColor(0);
  u8g2.drawBox(0, 0, 128, 64);
  u8g2.sendBuffer();
  delay(100);

  encoder.init();
  as5600.init();
  as5600.update();
  as5600_reset_angle();
  delay(100);

  driver.voltage_power_supply = 1.0;
  driver.voltage_limit = 1.0;
  driver.pwm_frequency = 10000;
  driver.init();
  
  show_status("TEST");

  uint32_t iterations = 300;
  uint32_t index = 0;
  float angle_arr[iterations];
  float speed_arr[iterations];
  int32_t ticks_arr[iterations];
  uint32_t last_ts = 0;

  driver.enable();
  driver.setPwm(0.5);
  while (true) {
    encoder.update();
    as5600.update();

    if (millis() - last_ts > 10) {
      angle_arr[index] = as5600_get_angle();
      ticks_arr[index] = -1 * encoder_get_ticks();

      Serial.print("as5600 ang: ");
      Serial.print(angle_arr[index]);
      Serial.print(" enc ang: ");
      Serial.print(ticks_arr[index]);
      Serial.println();

      last_ts = millis();
      index++;
    }

    if (index >= iterations) break;
  }

  driver.setPwm(0.0);
  driver.disable();

  float final_angle = angle_arr[iterations - 1];
  int32_t final_ticks = ticks_arr[iterations - 1];
  float cpr = final_ticks * 1.0f / (abs(final_angle) / _2PI);

  Serial.print("final angle: ");
  Serial.println(final_angle);
  Serial.print("final ticks: ");
  Serial.println(final_ticks);
  Serial.print("calculated cpr: ");
  Serial.println(cpr);

  if (abs(final_angle) < _PI) {
    show_fail_err("MOTOR_NO_MOVEMENT");
    return;
  }
  
  if (abs(final_ticks) < 100) {
    show_fail_err("ENCODER_NO_DATA");
    return;
  }

  if (abs(cpr - 616.0) > 10.0) {
    show_fail_err("ENCODER_CPR_MISMATCH");
    return;
  }
  
  if (final_angle < 0) {
    show_fail_err("DIRECTION_MISMATCH");
    return;
  }

  show_status("PASS");
}

void loop() {}
