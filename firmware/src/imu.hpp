#pragma once
#include <Arduino.h>
#include <Wire.h>
#include <ICM_20948.h>
#include "i2c_check.hpp"


class Imu {
public:
	struct Coord {
		float x = 0.0f;
		float y = 0.0f;
		float z = 0.0f;
	};

	struct CoordQuat{
		float x = 0.0f;
		float y = 0.0f;
		float z = 0.0f;
		float w = 0.0f;
	};

	struct IMUDEBUG {
		float q1 = 0.0f;
		float q2 = 0.0f;
		float q3 = 0.0f;
		float sum = 0.0f;

		int32_t raw_q1 = 0;
    	int32_t raw_q2 = 0;
    	int32_t raw_q3 = 0;

    	uint16_t header = 0;

    	bool valid = false;
	};



	bool initImu() {
		IMU_INIT_OK_ = false;

		if (!i2cCheck(wire_, address_)) {
			return false;	
		}

		uint8_t ad0 = (address_ == 0x69) ? 1 : 0;

    		myICM_.begin(wire_, ad0);

    		bool initialized = myICM_.status == ICM_20948_Stat_Ok;
    
    		bool success = initialized;
    		success &= (myICM_.initializeDMP() == ICM_20948_Stat_Ok);
    		success &= (myICM_.enableDMPSensor(INV_ICM20948_SENSOR_ORIENTATION) == ICM_20948_Stat_Ok);
    		success &= (myICM_.setDMPODRrate(DMP_ODR_Reg_Quat9, 16) == ICM_20948_Stat_Ok);
    		success &= (myICM_.enableFIFO() == ICM_20948_Stat_Ok);
    		success &= (myICM_.enableDMP() == ICM_20948_Stat_Ok);
    		success &= (myICM_.resetDMP() == ICM_20948_Stat_Ok);
    		success &= (myICM_.resetFIFO() == ICM_20948_Stat_Ok);
    		if (success) IMU_INIT_OK_ = true;
		return IMU_INIT_OK_;
}

	Imu(TwoWire& wire, SemaphoreHandle_t& wireMutex, uint8_t address) : wire_(wire), wireMutex_(wireMutex), address_(address) {
	}



	void updateImu() {
		uint32_t last_ts = 0;
    
   		while (true) {
        if (!monitor_.isLive()) {
          IMU_INIT_OK_ = false;

          vTaskDelay(pdMS_TO_TICKS(1000));
          continue;
        }


        		icm_20948_DMP_data_t data;
			if (xSemaphoreTake(wireMutex_, pdMS_TO_TICKS(20)) == pdTRUE) {
        			myICM_.readDMPdataFromFIFO(&data);

              auto status = myICM_.status;
              xSemaphoreGive(wireMutex_);


              if (status == ICM_20948_Stat_Ok || status == ICM_20948_Stat_FIFOMoreDataAvail) {
                monitor_.record(true);
              } else if (status != ICM_20948_Stat_FIFONoDataAvail) {
                monitor_.record(false);
              }

				
        			double q1, q2, q3, q0;
        
        			if ((myICM_.status == ICM_20948_Stat_Ok) || (myICM_.status == ICM_20948_Stat_FIFOMoreDataAvail)) {
            
					if ((data.header & DMP_header_bitmap_Quat9) > 0) {
                				q1 = ((double)data.Quat9.Data.Q1) / 1073741824.0;
                				q2 = ((double)data.Quat9.Data.Q2) / 1073741824.0;
                				q3 = ((double)data.Quat9.Data.Q3) / 1073741824.0;
                				q0 = sqrt(1.0 - ((q1 * q1) + (q2 * q2) + (q3 * q3)));
                				quat_.w = q0;
	    					quat_.x = q1;
	   					quat_.y = q2;
	    					quat_.z = q3;
	    				}
        			}	
			}

      if (!monitor_.isLive()) {
        IMU_INIT_OK_ = false;
        continue;
      }

        		uint32_t now = micros();
        		if ((now - last_ts >= 100000) || (now < last_ts)) {
            			if (xSemaphoreTake(wireMutex_, pdMS_TO_TICKS(20)) == pdTRUE) {
	        			myICM_.getAGMT();

                bool check = myICM_.status == ICM_20948_Stat_Ok;
	              monitor_.record(check);

    	    			if (myICM_.status == ICM_20948_Stat_Ok) {
        				acc_.x = myICM_.accX();
    	    				acc_.y = myICM_.accY();
    	    				acc_.z = myICM_.accZ();
    
    		    			gyr_.x = myICM_.gyrX();
    		    			gyr_.y = myICM_.gyrY();
    	    				gyr_.z = myICM_.gyrZ();
    	    			}
	    			xSemaphoreGive(wireMutex_);
	    			}

            			last_ts = now;
        		}
        
        		vTaskDelay(pdMS_TO_TICKS(50));
    		}
	}

	bool isInit() const {
		return IMU_INIT_OK_;
	}

	static void task(void* arg) {
		Imu* imu = static_cast<Imu*>(arg);
		imu->updateImu();
	}

	const Coord& getAcc() const  {
		return acc_;
	}

	const Coord& getGyr() const {
		return gyr_;
	}

	const CoordQuat& getQuat() const {
		return quat_;
	}

	const IMUDEBUG& getDebug() const {
		return debug_;
	}
private:
	ICM_20948_I2C myICM_;

	TwoWire& wire_;
	SemaphoreHandle_t wireMutex_;
	uint8_t address_;
		IMUDEBUG debug_;

	bool IMU_INIT_OK_ = false;

	bool i2cCheck(TwoWire& bus, uint8_t address) {
		bus.beginTransmission(address);
		return bus.endTransmission() == 0;
	}

  I2CMonitor<20, 3> monitor_;
  uint32_t lastRetry_ = 0;

  static constexpr uint32_t RETRY_INTERVAL_MS = 1000;

	Coord acc_;
	Coord gyr_;
	CoordQuat quat_;
};
