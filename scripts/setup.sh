#!/bin/bash
set -e

RELEASE="v1.1.0"
RBM_PLATFORM=""

ROOT="/opt/rbm"
USER="robomarvel"
VENV_BIN_PATH="$ROOT/venv/bin"
HOME_DIR="/home/$USER"
REPO_DIR="$HOME_DIR/robomarvel"
SETUP_URL="https://setup.robomarvel.ru"
REPO_URL="https://github.com/robotics-laboratory/rbm"
SERIAL_PORT="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"

APT_REQUIREMENTS=("python3-pip" "python3-venv" "tmux")
PYPI_MIRROR_URL="https://pypi-mirror.gitverse.ru/simple/"
PY_REQUIREMENTS="nicegui==3.17.1 psutil==7.2.2 pyserial==3.5 esptool==5.4.0"

HOTSPOT_CONN_FILE="/etc/NetworkManager/system-connections/hotspot.nmconnection"

RPI_EEPROM_FREEZE_URL="https://github.com/raspberrypi/rpi-eeprom/raw/refs/heads/master/firmware-2712/old/default/pieeprom-2024-09-10.bin"
RPI_EEPROM_FREEZE_SOURCE="/tmp/pieeprom-2024-09-10.bin"
RPI_EEPROM_FREEZE_CONFIG="/tmp/boot.conf"
RPI_EEPROM_FREEZE_IMAGE="/tmp/pieeprom-freeze.bin"

CURRENT_RELEASE_RELEASE=""
CURRENT_RELEASE_FIRMWARE=""
CURRENT_RELEASE_DOCKER=""
CURRENT_RELEASE_WEBUI=""

TARGET_RELEASE_RELEASE=""
TARGET_RELEASE_FIRMWARE=""
TARGET_RELEASE_DOCKER=""
TARGET_RELEASE_WEBUI=""

DO_RESTORE_ESP_CONFIG=false

SHELL_STDOUT=""
SHELL_STDERR=""
ENSURE_FILE_CREATED=false
ENSURE_FILE_UPDATED=false

export DEBIAN_FRONTEND=noninteractive

AUDIO_UDEV='SUBSYSTEM=="sound", DEVPATH=="*/sound/card*", ATTRS{idVendor}=="0c76", ATTRS{idProduct}=="1203", ATTR{id}="ws-usb-audio"'

ASOUND_CONFIG=$(cat <<'ASOUND_EOF'

defaults.pcm.!card "ws-usb-audio"
defaults.ctl.!card "ws-usb-audio"

pcm.!default {
    type asym
    playback.pcm "playback_route"
    capture.pcm "capture_plug"
}

pcm.playback_route {
    type route
    slave.pcm "hw:ws-usb-audio"
    slave.channels 2
    ttable.0.0 0.5
    ttable.1.0 0.5
    ttable.0.1 0.5
    ttable.1.1 0.5
}

pcm.capture_plug {
    type plug
    slave.pcm "hw:ws-usb-audio"
}

ctl.!default {
    type hw
    card "ws-usb-audio"
}
ASOUND_EOF
)

RPI_HOTSPOT_HOOK=$(cat <<'EOF'
#!/bin/bash

INTERFACE="$1"
ACTION="$2"
CON_NAME="hotspot"
STA_IF="wlan0"

if [ "$INTERFACE" = "wlan1" ] && [ "$ACTION" = "pre-up" ]; then
    /sbin/iw "$STA_IF" set power_save off 2>/dev/null
    /sbin/iw "$INTERFACE" set power_save off 2>/dev/null
    CHANNEL=$(/sbin/iw dev "$STA_IF" info | awk '/channel/ {print $2}')
    if [ -n "$CHANNEL" ]; then
        if [ "$CHANNEL" -le 14 ]; then BAND="bg"; else BAND="a"; fi
        logger -t sync-hotspot "Syncing $CON_NAME to $STA_IF: band=$BAND, channel=$CHANNEL"
        /usr/bin/nmcli connection modify "$CON_NAME" 802-11-wireless.band "$BAND" 802-11-wireless.channel "$CHANNEL"
    else
        logger -t sync-hotspot "$STA_IF disconnected; using fallback band=bg, channel=6"
        /usr/bin/nmcli connection modify "$CON_NAME" 802-11-wireless.band "bg" 802-11-wireless.channel 6
    fi
fi
EOF
)

log_info() { echo "INFO | $*" >&2; }
log_error() { echo "ERROR | $*" >&2; }

hotspot_conn_template() {
    local hostname="$1"
    cat <<EOF

[connection]
id=hotspot
uuid=7b2d7b6d-32e7-4a3b-855b-d0cf76a10b06
type=wifi
autoconnect=false
interface-name=wlan1

[wifi]
mode=ap
ssid=$hostname

[wifi-security]
key-mgmt=wpa-psk
psk=robomarvel

[ipv4]
address1=10.10.10.10/24
method=shared

[ipv6]
addr-gen-mode=stable-privacy
method=disabled

[proxy]
EOF
}

systemd_unit_template() {
    local description="$1"
    local user="$2"
    local workdir="$3"
    local cmd="$4"
    cat <<EOF

[Unit]
Description=$description
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=$user
WorkingDirectory=$workdir
ExecStart=$cmd
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
}

yaml_get() {
    local file="$1"
    local key="$2"
    grep -E "^[[:space:]]*${key}:" "$file" | head -n1 | sed -E "s/^[[:space:]]*${key}:[[:space:]]*//;s/[[:space:]]*$//"
}

get_current_release() {
    local version_file="$ROOT/version.yaml"
    if [ ! -f "$version_file" ]; then
        CURRENT_RELEASE_RELEASE=""
        CURRENT_RELEASE_FIRMWARE=""
        CURRENT_RELEASE_DOCKER=""
        CURRENT_RELEASE_WEBUI=""
        return 0
    fi
    CURRENT_RELEASE_RELEASE=$(yaml_get "$version_file" "release")
    CURRENT_RELEASE_FIRMWARE=$(yaml_get "$version_file" "firmware")
    CURRENT_RELEASE_DOCKER=$(yaml_get "$version_file" "docker")
    CURRENT_RELEASE_WEBUI=$(yaml_get "$version_file" "webui")
}

get_target_release() {
    local release="$1"
    local url="$SETUP_URL/release/$release/version.yaml"
    local tmp
    tmp=$(mktemp)
    wget -qO "$tmp" "$url"
    TARGET_RELEASE_RELEASE=$(yaml_get "$tmp" "release")
    TARGET_RELEASE_FIRMWARE=$(yaml_get "$tmp" "firmware")
    TARGET_RELEASE_DOCKER=$(yaml_get "$tmp" "docker")
    TARGET_RELEASE_WEBUI=$(yaml_get "$tmp" "webui")
    rm -f "$tmp"
}

get_hostname() {
    local h
    h=$(tr -d '[:space:]' < /etc/hostname 2>/dev/null)
    if [ -z "$h" ]; then
        echo "rbm-000"
    else
        echo "$h"
    fi
}

needs_update() {
    local component="$1"
    local uc
    uc=$(echo "$component" | tr '[:lower:]' '[:upper:]')
    local curr_var="CURRENT_RELEASE_${uc}"
    local targ_var="TARGET_RELEASE_${uc}"
    if [ "${!curr_var}" != "${!targ_var}" ]; then
        return 0
    else
        return 1
    fi
}

ensure_file() {
    local path="$1"
    local content="$2"
    local mode="${3:-600}"

    content=$(printf '%s' "$content" | sed -e '1s/^[[:space:]]*//' -e '$s/[[:space:]]*$//')
    content="${content}"$'\n'

    mkdir -p "$(dirname "$path")"

    local exists=false
    if [ -f "$path" ]; then
        exists=true
    fi

    local needs_update_flag=false
    if [ "$exists" = false ] || ! printf '%s' "$content" | cmp -s - "$path"; then
        needs_update_flag=true
    fi

    local created=false updated=false
    if [ "$needs_update_flag" = true ]; then
        updated=true
        if [ "$exists" = false ]; then
            created=true
        fi
        printf '%s' "$content" > "$path"
    fi

    local current_mode
    current_mode=$(stat -c '%a' "$path")
    if [ "$current_mode" != "$mode" ]; then
        updated=true
        chmod "$mode" "$path"
    fi

    ENSURE_FILE_CREATED=$created
    ENSURE_FILE_UPDATED=$updated

    log_info "$path [mode $mode] created=$created updated=$updated"
}

ensure_service() {
    local name="$1"
    local description="$2"
    local user="$3"
    local workdir="$4"
    local cmd="$5"
    local path="/etc/systemd/system/$name.service"
    local content
    content=$(systemd_unit_template "$description" "$user" "$workdir" "$cmd")
    ensure_file "$path" "$content"
    shell "systemctl enable --now $name.service"
}

shell() {
    local cmd="$1"
    local check="${2:-true}"
    local capture="${3:-true}"
    local timeout="${4:-}"
    local cwd="${5:-}"

    log_info "\$ $cmd"

    local full_cmd="$cmd"
    if [ -n "$cwd" ]; then
        full_cmd="cd '$cwd' && $cmd"
    fi

    local exit_code=0
    local stdout_file=""
    local stderr_file=""

    local -a run_prefix=()
    if [ -n "$timeout" ]; then
        run_prefix=(timeout "$timeout")
    fi

    if [ "$capture" = true ]; then
        stdout_file=$(mktemp)
        stderr_file=$(mktemp)
        "${run_prefix[@]}" bash -c "$full_cmd" > "$stdout_file" 2> "$stderr_file" || exit_code=$?
        SHELL_STDOUT=$(cat "$stdout_file")
        SHELL_STDERR=$(cat "$stderr_file")
    else
        SHELL_STDOUT=""
        SHELL_STDERR=""
        "${run_prefix[@]}" bash -c "$full_cmd" || exit_code=$?
    fi

    if [ "$exit_code" -eq 124 ]; then
        log_error "Command timed out after $timeout seconds"
        if [ -n "$stdout_file" ]; then
            rm -f "$stdout_file" "$stderr_file"
        fi
        return 124
    fi

    if [ "$exit_code" -ne 0 ] && [ "$check" = true ]; then
        log_error "Command failed with return code $exit_code"
        log_error "STDOUT:
$SHELL_STDOUT"
        log_error "STDERR:
$SHELL_STDERR"
        if [ -n "$stdout_file" ]; then
            rm -f "$stdout_file" "$stderr_file"
        fi
        return "$exit_code"
    fi

    if [ -n "$stdout_file" ]; then
        rm -f "$stdout_file" "$stderr_file"
    fi
    return 0
}

check_running_as_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "Setup script must be run as root (try with sudo)"
        exit 1
    fi
}

create_hotspot_connection() {
    log_info "Creating hotspot connection..."
    local hostname
    hostname=$(get_hostname)
    local content
    content=$(hotspot_conn_template "$hostname")
    ensure_file "$HOTSPOT_CONN_FILE" "$content"
    if [ "$ENSURE_FILE_CREATED" = true ] || [ "$ENSURE_FILE_UPDATED" = true ]; then
        shell "nmcli connection reload"
    fi
    shell "nmcli connection show"
    if [[ "$SHELL_STDOUT" != *"hotspot"* ]]; then
        log_error "hotspot connection not found"
    fi
}

set_default_audio_device() {
    local udev_path="/etc/udev/rules.d/99-usb-audio.rules"
    ensure_file "$udev_path" "$AUDIO_UDEV"
    if [ "$ENSURE_FILE_CREATED" = true ] || [ "$ENSURE_FILE_UPDATED" = true ]; then
        shell "udevadm control --reload-rules && udevadm trigger"
    fi
    local asound_path="/etc/asound.conf"
    ensure_file "$asound_path" "$ASOUND_CONFIG"
}

setup_repository() {
    log_info "Setting up repository..."
    if [ -d "$REPO_DIR" ]; then
        log_info "Repository exists - deleting"
        shell "rm -rf $REPO_DIR"
    fi
    shell "git clone -b release/$TARGET_RELEASE_RELEASE $REPO_URL $REPO_DIR"
    shell "chown -R robomarvel $REPO_DIR"
}

backup_esp_config() {
    local config_path="$ROOT/esp-config.yaml"
    local backup_config_path="$ROOT/esp-config.backup.yaml"
    if [ -f "$config_path" ]; then
        log_info "Backup esp config..."
        cp "$config_path" "$backup_config_path"
        DO_RESTORE_ESP_CONFIG=true
    fi
}

setup_webui() {
    log_info "Setting up webui..."
    local repo_webui_path="$REPO_DIR/webui"
    local opt_webui_path="$ROOT/webui"
    if [ -d "$opt_webui_path" ]; then
        rm -rf "$opt_webui_path"
    fi
    cp -rf "$repo_webui_path" "$opt_webui_path"
    ensure_service \
        "rbm-webui" \
        "RBM Web UI" \
        "root" \
        "$ROOT" \
        "/opt/rbm/venv/bin/python -m webui.main"
}

setup_webtmux() {
    local ttyd="$ROOT/ttyd"
    if [ ! -f "$ttyd" ]; then
        shell "wget -O /opt/rbm/ttyd $SETUP_URL/static/ttyd"
        shell "chmod +x /opt/rbm/ttyd"
    fi
    ensure_service \
        "rbm-webtmux-host" \
        "RBM Web Terminal (host)" \
        "robomarvel" \
        "$ROOT" \
        "$ttyd -W -p 8100 tmux new -A -s webtmux bash"
    ensure_service \
        "rbm-webtmux-docker" \
        "RBM Web Terminal (docker)" \
        "robomarvel" \
        "$ROOT" \
        "$ttyd -W -p 8200 docker exec -it ros tmux new -A -s main bash"
}

stop_container() {
    log_info "Stopping docker container..."
    shell "docker stop ros" false
}

pull_container() {
    log_info "Pulling docker image..."
    shell "docker compose pull" true false "" "$REPO_DIR"
}

start_container() {
    log_info "Starting docker container..."
    touch "$REPO_DIR/.autostart"
    shell "docker compose up -d --no-build" true false "" "$REPO_DIR"
}

update_firmware() {
    log_info "Downloading firmware..."
    local url="$SETUP_URL/release/$TARGET_RELEASE_RELEASE/firmware.bin"
    local path="$ROOT/firmware.bin"
    shell "wget -O $path $url"
    log_info "Flashing..."
    local cmd="$VENV_BIN_PATH/python -m esptool --chip esp32 --port $SERIAL_PORT --baud 921600 write-flash -z 0x10000 $path"
    shell "$cmd" false false
}

write_version() {
    log_info "Writing version file..."
    local version_file="$ROOT/version.yaml"
    local rel="$TARGET_RELEASE_RELEASE"
    local fw="$TARGET_RELEASE_FIRMWARE"
    local dk="$TARGET_RELEASE_DOCKER"
    local wu="$TARGET_RELEASE_WEBUI"
    if [ -z "$rel" ]; then rel="null"; fi
    if [ -z "$fw" ]; then fw="null"; fi
    if [ -z "$dk" ]; then dk="null"; fi
    if [ -z "$wu" ]; then wu="null"; fi
    cat > "$version_file" <<EOF
release: $rel
firmware: $fw
docker: $dk
webui: $wu
EOF
}

rdk_fix_apt_sources() {
    log_info "[RDK] Fixing apt sources..."
    sed -i '/^deb .*mirrors4.tuna.tsinghua.edu.cn/ s|http://mirrors4.tuna.tsinghua.edu.cn/ubuntu-ports/|http://mirror.yandex.ru/ubuntu-ports/|g' /etc/apt/sources.list
    sed -i '/^deb .*ports.ubuntu.com/ s|http://ports.ubuntu.com/|http://mirror.yandex.ru/ubuntu-ports/|g' /etc/apt/sources.list
    [ -f "/etc/apt/sources.list.d/ros2.list" ] && mv /etc/apt/sources.list.d/ros2.list /etc/apt/sources.list.d/ros2.list.disabled
    [ -f "/etc/apt/sources.list.d/sunrise.list" ] && mv /etc/apt/sources.list.d/sunrise.list /etc/apt/sources.list.d/sunrise.list.disabled
}

rpi_install_docker() {
    log_info "Проверка установки Docker"
    if command -v docker >/dev/null 2>&1; then
        log_info "Docker уже установлен"
        return 0
    fi
    
    log_info "Установка Docker"
    curl -fsSL https://get.docker.com | sh    
    usermod -aG docker $USER

    log_info "Docker успешно установлен"
    log_info "Пользователь $USER добавлен в группу docker"
}

rpi_disable_cloud_init() {
    log_info "[RPI] Replacing netplan connections..."

    NETPLAN_DIR="/etc/netplan"
    NM_DIR="/etc/NetworkManager/system-connections"
    CLOUD_DIR="/etc/cloud/cloud.cfg.d"

    mapfile -t PROFILES < <(nmcli -t -f NAME con show | grep '^netplan-' || true)

    for old in "${PROFILES[@]}"; do
        new="${old#netplan-}"

        if [[ "$new" == wlan0-* ]]; then new="${new#wlan0-}"; fi
        if [[ "$new" == "eth0" ]]; then new="ethernet"; fi
    
        if nmcli -g connection.id con show "$new" >/dev/null 2>&1; then
            echo "Already exists: $new"
        else
            nmcli con clone "$old" "$new"
        fi

        chmod 600 "$NM_DIR/$new.nmconnection"
        nmcli con mod "$new" connection.autoconnect yes
    done

    if [[ -d "$NETPLAN_DIR" ]]; then
        find "$NETPLAN_DIR" -maxdepth 1 -type f -name '*.yaml' -delete
    fi
    nmcli -f NAME,TYPE,DEVICE con show

    log_info "[RPI] Disabling cloud-init..."
    touch /etc/cloud/cloud-init.disabled
}

rpi_configure_eeprom() {
    log_info "[RPI] Checking EEPROM..."

    systemctl disable rpi-eeprom-update.service

    CURRENT_CONFIG=$(rpi-eeprom-config)

    if echo "$CURRENT_CONFIG" | grep -q "^FREEZE_VERSION=1" && \
       echo "$CURRENT_CONFIG" | grep -q "^PSU_MAX_CURRENT=" && \
       vcgencmd bootloader_version 2>/dev/null | grep -q "^2024/09/10"; then
        log_info "EEPROM уже зафиксирован на версии 2024-09-10 и настроен"
        return 0
    fi

    log_info "EEPROM будет настроен на pieeprom-2024-09-10.bin"

    log_info "Загрузка pieeprom-2024-09-10.bin"
    curl -fsSL "$RPI_EEPROM_FREEZE_URL" -o "$RPI_EEPROM_FREEZE_SOURCE"

    rpi-eeprom-config "$RPI_EEPROM_FREEZE_SOURCE" > "$RPI_EEPROM_FREEZE_CONFIG"

    if ! grep -q "^FREEZE_VERSION=" "$RPI_EEPROM_FREEZE_CONFIG"; then
        echo "FREEZE_VERSION=1" >> "$RPI_EEPROM_FREEZE_CONFIG"
    fi

    if ! grep -q "^PSU_MAX_CURRENT=" "$RPI_EEPROM_FREEZE_CONFIG"; then
        echo "PSU_MAX_CURRENT=5000" >> "$RPI_EEPROM_FREEZE_CONFIG"
    fi

    rpi-eeprom-config \
        --out "$RPI_EEPROM_FREEZE_IMAGE" \
        --config "$RPI_EEPROM_FREEZE_CONFIG" \
        "$RPI_EEPROM_FREEZE_SOURCE"

    rpi-eeprom-update -d -f "$RPI_EEPROM_FREEZE_IMAGE"
    log_info "Конфигурация EEPROM обновлена"
}

rpi_hotspot_hooks() {
  log_info "[RPI] Installing hotspot dispatcher hooks..."
  ensure_file "/etc/NetworkManager/dispatcher.d/pre-up.d/99-sync-hotspot" "$RPI_HOTSPOT_HOOK" 755
  systemctl enable --now NetworkManager-dispatcher.service
}

install_tailscale() {
    if [[ -z "$TAILSCALE_KEY" ]]; then return 0; fi
    log_info "Setting up tailscale..."

    local prefix=""
    if [ "$RBM_PLATFORM" = "raspberry" ]; then prefix="raspbian/trixie"
    elif [ "$RBM_PLATFORM" = "rdk" ]; then prefix="ubuntu/jammy"
    else return 0; fi

    if ! command -v tailscale >/dev/null 2>&1; then
        mkdir -p --mode=0755 /usr/share/keyrings
        curl -fsSL https://raw.githubusercontent.com/hopleus/tailscale-mirror/main/data/stable/$prefix.noarmor.gpg | tee /usr/share/keyrings/tailscale-mirror-archive-keyring.gpg > /dev/null
        curl -fsSL https://raw.githubusercontent.com/hopleus/tailscale-mirror/main/data/stable/$prefix.tailscale-keyring.list | tee /etc/apt/sources.list.d/tailscale-mirror.list
        apt-get -qq update && apt-get install -yqq tailscale
    fi

    tailscale up --login-server=https://setup.robomarvel.ru --authkey $TAILSCALE_KEY --hostname rbm-$(openssl rand -hex 5)
}

check_system() {
  local model=$(tr -d '\0' < /sys/firmware/devicetree/base/model)

  if [[ "$model" = "Raspberry Pi 5"* ]]; then
    RBM_PLATFORM="raspberry"
  elif [[ "$model" = "D-Robotics RDK X5"* ]]; then
    RBM_PLATFORM="rdk"
  else
    log_error "Unknown board model: $model"
    exit 1
  fi

  log_info "Detected platform: $RBM_PLATFORM"
  mkdir -p $ROOT && chown -R robomarvel $ROOT
  ensure_file "$ROOT/model" "$RBM_PLATFORM"
}

apply_system_tweaks() {
    if [ "$RBM_PLATFORM" = "raspberry" ]; then
        rpi_install_docker
        rpi_disable_cloud_init
        rpi_configure_eeprom
        rpi_hotspot_hooks
    elif [ "$RBM_PLATFORM" = "rdk" ]; then
        rdk_fix_apt_sources
    fi
}

setup_apt() {
  log_info "Installing apt requirements..."

  MISSING=()
  for pkg in "${APT_REQUIREMENTS[@]}"; do
      dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed" || MISSING+=("$pkg")
  done

  if [ ${#MISSING[@]} -gt 0 ]; then
    log_info "Missing packages: $MISSING"
    apt-get -qq update && apt-get install -yqq "${MISSING[@]}"
  else
    log_info "All apt packages installed"
  fi
}

setup_venv() {
  log_info "Setting up pyhton venv..."

  if [ ! -f $VENV_BIN_PATH/pip ]; then
    python3 -m venv $ROOT/venv
    $VENV_BIN_PATH/pip install -q --index-url $PYPI_MIRROR_URL --upgrade pip
  fi
  $VENV_BIN_PATH/pip install -q --index-url $PYPI_MIRROR_URL $PY_REQUIREMENTS
}

check_release() {
    log_info "Preparing system upgrade to '$RELEASE'"
    get_current_release
    get_target_release "$RELEASE"
    log_info "Current version: release='$CURRENT_RELEASE_RELEASE' firmware='$CURRENT_RELEASE_FIRMWARE' docker='$CURRENT_RELEASE_DOCKER' webui='$CURRENT_RELEASE_WEBUI'"
    log_info "Target version: release='$TARGET_RELEASE_RELEASE' firmware='$TARGET_RELEASE_FIRMWARE' docker='$TARGET_RELEASE_DOCKER' webui='$TARGET_RELEASE_WEBUI'"
}

main() {
    echo "=== ROBOMARVEL SETUP $RELEASE ==="

    check_running_as_root
    check_system
    apply_system_tweaks
    setup_apt
    setup_venv
    check_release
    install_tailscale
    create_hotspot_connection
    set_default_audio_device
    stop_container
    setup_repository
    if needs_update "webui"; then
        setup_webui
        setup_webtmux
    fi
    if needs_update "docker"; then
        pull_container
    fi
    if needs_update "firmware"; then
        backup_esp_config
        update_firmware
    fi
    start_container
    write_version

    echo "======= SETUP FINISHED ======="
}

trap 'echo "SETUP INTERRUPTED"; exit 1' INT TERM
main "$@"
