#!/bin/bash
set -e

RELEASE="v1.0.0"
RBM_OPT_PATH="/opt/rbm"
VENV_BIN_PATH="$RBM_OPT_PATH/venv/bin"
APT_REQUIREMENTS=("python3-pip" "python3-venv" "tmux")
PYPI_MIRROR_URL="https://pypi-mirror.gitverse.ru/simple/"
PY_REQUIREMENTS="nicegui==3.17.1 psutil==7.2.2 pyserial==3.5 esptool==5.4.0"
SETUP_PY_URL="https://setup.robomarvel.ru/release/$RELEASE/setup.py"

export DEBIAN_FRONTEND=noninteractive

check_system() {
  echo "Verifying system version..."

  EXPECTED_OS="Ubuntu 22.04.5 LTS"
  OS_VERSION=$(cat /etc/os-release | grep -oP 'PRETTY_NAME="\K[^"]+')
  if [ "$OS_VERSION" != "$EXPECTED_OS" ]; then
    echo "OS check failed: '$OS_VERSION' != '$EXPECTED_OS'" >&2
    exit 1
  fi

  EXPECTED_BOARD="D-Robotics RDK X5"
  BOARD_MODEL=$(tr -d '\0' < /sys/firmware/devicetree/base/model)
  if [[ "$BOARD_MODEL" != "$EXPECTED_BOARD"* ]]; then
    echo "Board check failed: '$BOARD_MODEL' != '$EXPECTED_BOARD'" >&2
    exit 1
  fi
}

setup_apt() {
  echo "Installing apt requirements..."

  sudo sed -i '/^deb .*mirrors4.tuna.tsinghua.edu.cn/ s|http://mirrors4.tuna.tsinghua.edu.cn/ubuntu-ports/|http://mirror.yandex.ru/ubuntu-ports/|g' /etc/apt/sources.list
  sudo sed -i '/^deb .*ports.ubuntu.com/ s|http://ports.ubuntu.com/|http://mirror.yandex.ru/ubuntu-ports/|g' /etc/apt/sources.list
  [ -f "/etc/apt/sources.list.d/ros2.list" ] && mv /etc/apt/sources.list.d/ros2.list /etc/apt/sources.list.d/ros2.list.disabled
  [ -f "/etc/apt/sources.list.d/sunrise.list" ] && mv /etc/apt/sources.list.d/sunrise.list /etc/apt/sources.list.d/sunrise.list.disabled

  MISSING=()
  for pkg in "${APT_REQUIREMENTS[@]}"; do
      dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed" || MISSING+=("$pkg")
  done

  if [ ${#MISSING[@]} -gt 0 ]; then
    sudo apt-get -qq update && sudo apt-get install -yqq "${MISSING[@]}"
  fi
}

setup_venv() {
  echo "Setting up pyhton venv..."

  sudo mkdir -p $RBM_OPT_PATH
  sudo chown -R robomarvel $RBM_OPT_PATH
  if [ ! -f $VENV_BIN_PATH/pip ]; then
    python3 -m venv $RBM_OPT_PATH/venv
    $VENV_BIN_PATH/pip install -q --index-url $PYPI_MIRROR_URL --upgrade pip
  fi
  $VENV_BIN_PATH/pip install -q --index-url $PYPI_MIRROR_URL $PY_REQUIREMENTS
}

launch_setup() {
  echo "Launching setup script..."
  curl -sSL -o /opt/rbm/setup.py https://setup.robomarvel.ru/release/$RELEASE/setup.py
  sudo /opt/rbm/venv/bin/python /opt/rbm/setup.py
}

main() {
  echo "=== ROBOMARVEL SETUP $RELEASE ==="
  check_system
  setup_apt
  setup_venv
  launch_setup
  echo "======= SETUP FINISHED ======="
}

trap 'echo "SETUP INTERRUPTED"; exit 1' INT TERM
main "$@"
