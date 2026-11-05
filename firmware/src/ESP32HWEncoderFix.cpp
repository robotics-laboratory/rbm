#include "ESP32HWEncoderFix.h"

ESP32HWEncoder::ESP32HWEncoder(int pinA, int pinB, int32_t ppr, int pinI)
{
    _pinA = pinA;
    _pinB = pinB;
    _pinI = pinI;

    cpr = ppr * 4; // 4x for quadrature
    if (cpr > 0) inv_cpr = 1.0f / cpr;

    //pcnt_config.ctrl_gpio_num =  _pinA;
    //pcnt_config.pulse_gpio_num = _pinB;
    //pcnt_config.counter_l_lim = INT16_MIN;
    //pcnt_config.counter_h_lim = INT16_MAX;
} 

void ESP32HWEncoder::init()
{
    //pcnt_unit_config_t unit_config = {
    //    .low_limit = INT16_MIN,
    //    .high_limit = INT16_MAX,
    //    .flags.accum_count = true,
    //};
    pcnt_unit_config_t unit_config = {};
    unit_config.low_limit = INT16_MIN;
    unit_config.high_limit = INT16_MAX;
    unit_config.flags.accum_count = true;
    
    ESP_ERROR_CHECK(pcnt_new_unit(&unit_config, &pcnt_unit));

    // 2. Set up a glitch filter (suppress noise shorter than 1 microsecond)
    pcnt_glitch_filter_config_t filter_config = {
        .max_glitch_ns = 10000,
    };
    ESP_ERROR_CHECK(pcnt_unit_set_glitch_filter(pcnt_unit, &filter_config));

    // 3. Configure Channel A
    pcnt_chan_config_t chan_a_config = {
        .edge_gpio_num = _pinA,
        .level_gpio_num = _pinB,
    };
    pcnt_channel_handle_t pcnt_chan_a = NULL;
    ESP_ERROR_CHECK(pcnt_new_channel(pcnt_unit, &chan_a_config, &pcnt_chan_a));

    // 4. Configure Channel B
    pcnt_chan_config_t chan_b_config = {
        .edge_gpio_num = _pinB,
        .level_gpio_num = _pinA,
    };
    pcnt_channel_handle_t pcnt_chan_b = NULL;
    ESP_ERROR_CHECK(pcnt_new_channel(pcnt_unit, &chan_b_config, &pcnt_chan_b));

    // 5. Define quadrature counting rules for Channel A
    ESP_ERROR_CHECK(pcnt_channel_set_edge_action(pcnt_chan_a, PCNT_CHANNEL_EDGE_ACTION_DECREASE, PCNT_CHANNEL_EDGE_ACTION_INCREASE));
    ESP_ERROR_CHECK(pcnt_channel_set_level_action(pcnt_chan_a, PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_INVERSE));

    // 6. Define quadrature counting rules for Channel B
    ESP_ERROR_CHECK(pcnt_channel_set_edge_action(pcnt_chan_b, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_DECREASE));
    ESP_ERROR_CHECK(pcnt_channel_set_level_action(pcnt_chan_b, PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_INVERSE));

    // 7. Enable and start the PCNT unit
    ESP_ERROR_CHECK(pcnt_unit_add_watch_point(pcnt_unit, INT16_MAX));
    ESP_ERROR_CHECK(pcnt_unit_add_watch_point(pcnt_unit, INT16_MIN));

    ESP_ERROR_CHECK(pcnt_unit_enable(pcnt_unit));
    ESP_ERROR_CHECK(pcnt_unit_clear_count(pcnt_unit));
    ESP_ERROR_CHECK(pcnt_unit_start(pcnt_unit));

    initialized = true;

    // ESP_ERROR_CHECK(pcnt_unit_get_count(pcnt_unit, &pulse_count));
}

int ESP32HWEncoder::needsSearch()
{
        return !((indexFound && hasIndex()) || !hasIndex());
}

int ESP32HWEncoder::hasIndex()
{
    return _pinI != -1;
}

void ESP32HWEncoder::setCpr(int32_t ppr){
    cpr = 4*ppr;
    if(cpr > 0){
        inv_cpr = 1.0f/cpr; // Precalculate the inverse of cpr to avoid "slow" float divisions
    }
}

int32_t ESP32HWEncoder::getCpr(){
    return cpr;
}

// Change to Step/Dir counting mode. A->Step, B->Dir
void ESP32HWEncoder::setStepDirMode(){
    
}

// Change to default AB (quadrature) mode
void ESP32HWEncoder::setQuadratureMode(){
    
}

float IRAM_ATTR ESP32HWEncoder::getSensorAngle()
{
    if(!initialized){return -1.0f;}

    //taskENTER_CRITICAL(&spinlock);
    // We are now in a critical section to prevent interrupts messing with angleOverflow and angleCounter

    // Retrieve the count register into a variable
    //pcnt_get_counter_value(pcnt_config.unit, &angleCounter);
    int count = 0;
    ESP_ERROR_CHECK(pcnt_unit_get_count(pcnt_unit, &count));
    int32_t angleCount = count % cpr;
    if (angleCount < 0) {
      angleCount += cpr;
    }
    int32_t prevAngleSum = angleSum;
    angleSum = angleCount;

    //taskEXIT_CRITICAL(&spinlock); // Exit critical section
    
    // Calculate the shaft angle
    float result = _2PI * angleSum * inv_cpr;
    if (angleSum == prevAngleSum) result += 1e-6f;
    return result;
}
