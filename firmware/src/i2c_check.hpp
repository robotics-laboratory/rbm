#pragma once
#include <Arduino.h>

template<size_t M = 20, size_t N = 3>
class I2CMonitor {
public:
  void record(bool check) {
    if (count_ == M) {
      if (!window_[idx_]) {
        --err_;
      }
    } else {
      ++count_;
    }

    window_[idx_] = check;

    if (!check) {
      ++err_;
    }

    idx_ = (idx_ + 1) % M;

    if (count_ == M && err_ > N) {
      is_live_ = false;
    }
  }

  bool isLive() const {
    return is_live_;
  }

  void reset() {
    for (size_t i = 0; i < M; ++i) {
      window_[i] = true;
    }

    idx_ = 0;
    count_ = 0;
    err_ = 0;
    is_live_ = true;
  }

private:
    bool window_[M] = {};
    size_t idx_ = 0;
    size_t count_ = 0;
    size_t err_ = 0;
    bool is_live_ = true;
};
