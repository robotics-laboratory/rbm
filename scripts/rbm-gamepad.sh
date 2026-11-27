#!/bin/bash

SCAN_TIMEOUT=8
CONNECT_TIMEOUT=30
READ_TIMEOUT=5
BT_ADAPTER="${BT_ADAPTER:-}"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
BLUEZ_HELPER="$SCRIPT_DIR/rbm-gamepad.py"
WT_TITLE='RBM Gamepad'
WT_HEIGHT=20
WT_WIDTH=78
TASK_PID=''
INIT_PID=''
JOB_PID=''
WORK_DIR=''
GAMEPAD_MAC=''
GAMEPAD_ALIAS=''
GAMEPAD_INFO=''
NEW_PAIR=no
TTY_STATE=''

export LC_ALL=C

ui() (
  local GUARD_PID='' STATUS
  trap - EXIT
  trap '[ -z "$GUARD_PID" ] || kill "$GUARD_PID" 2>/dev/null; exit 130' INT
  trap '[ -z "$GUARD_PID" ] || kill "$GUARD_PID" 2>/dev/null; exit 143' TERM
  if [ -n "$TTY_STATE" ]; then
    (
      while true; do
        stty isig intr '^C' </dev/tty 2>/dev/null
        sleep 0.05
      done
    ) &
    GUARD_PID=$!
  fi
  whiptail --title "$WT_TITLE" --backtitle "Robot: $(hostname)" "$@"
  STATUS=$?
  if [ -n "$GUARD_PID" ]; then
    kill "$GUARD_PID" 2>/dev/null || true
    wait "$GUARD_PID" 2>/dev/null || true
  fi
  return "$STATUS"
)

message() {
  ui --msgbox "$1" "$WT_HEIGHT" "$WT_WIDTH"
}

clean_text() {
  sed $'s/\033\\[[0-9;]*[[:alpha:]]//g' | tr -d '\000-\010\013-\037\177'
}

operation_error() {
  local DETAILS
  DETAILS=$(tail -n 5 "$WORK_DIR/output" | clean_text)
  message "$1${DETAILS:+$'\n\n'$DETAILS}"
  return 1
}

cleanup() {
  if [ -n "$TASK_PID" ]; then
    kill "$TASK_PID" 2>/dev/null || true
    wait "$TASK_PID" 2>/dev/null || true
  fi
  if [ -n "$INIT_PID" ]; then
    kill "$INIT_PID" 2>/dev/null || true
    wait "$INIT_PID" 2>/dev/null || true
  fi
  if [ -n "$TTY_STATE" ]; then
    stty "$TTY_STATE" </dev/tty 2>/dev/null || true
    tput rmcup 2>/dev/null || true
    tput cnorm 2>/dev/null || true
  fi
  if [ -n "$WORK_DIR" ]; then
    rm -rf -- "$WORK_DIR"
    [ ! -t 1 ] || clear
  fi
}

wait_progress() {
  local TEXT="$1" PID="$2" START=$SECONDS ELAPSED PERCENT TICK=0 DETAIL INITIAL STEP
  local SPINNER='|/-\'
  TEXT="${TEXT//\\n/$'\n'}"
  for ((STEP=0; STEP<5; STEP++)); do
    kill -0 "$PID" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -0 "$PID" 2>/dev/null || return 0
  if [ "${PROGRESS_SECONDS:-0}" -eq 0 ]; then
    python3 "$BLUEZ_HELPER" progress "$WORK_DIR" "$PID" "$WT_TITLE" "$TEXT"
    return $?
  fi
  INITIAL="$TEXT"$'\n\n'"Search time: 0 / $PROGRESS_SECONDS s"$'\n|  Elapsed: 0 s'
  {
    printf '0\n'
    while kill -0 "$PID" 2>/dev/null; do
      ELAPSED=$((SECONDS - START))
      PERCENT=$((ELAPSED * 100 / PROGRESS_SECONDS))
      [ "$PERCENT" -lt 100 ] || PERCENT=99
      DETAIL="Search time: $ELAPSED / $PROGRESS_SECONDS s"
      printf 'XXX\n%s\n%s\n\n%s\n%s  Elapsed: %s s\nXXX\n' \
        "$PERCENT" "$TEXT" "$DETAIL" "${SPINNER:TICK%4:1}" "$ELAPSED" || break
      TICK=$((TICK + 1))
      sleep 0.1
    done
    printf '100\n'
  } | ui --gauge "$INITIAL" 12 "$WT_WIDTH" 0
}

run_command() {
  local TEXT="$1" STATUS
  shift
  "$@" >"$WORK_DIR/output" 2>&1 </dev/null &
  TASK_PID=$!
  wait_progress "$TEXT" "$TASK_PID"
  wait "$TASK_PID"
  STATUS=$?
  TASK_PID=''
  return "$STATUS"
}

run_bt() {
  local TEXT="$1"
  shift
  run_command "$TEXT" python3 "$BLUEZ_HELPER" request "$WORK_DIR" -- "$@"
}

use_cached_gamepad() {
  [ -f "$WORK_DIR/cache/$GAMEPAD_MAC" ] || return 1
  GAMEPAD_INFO=$(cat "$WORK_DIR/cache/$GAMEPAD_MAC")
  GAMEPAD_ALIAS=$(info_value Alias)
  GAMEPAD_ALIAS="${GAMEPAD_ALIAS:-$GAMEPAD_MAC}"
}

info_value() {
  sed -n "s/^[[:space:]]*$1: //p" <<< "$GAMEPAD_INFO"
}

has_property() {
  use_cached_gamepad || return 1
  grep -Eq "^[[:space:]]*$1: $2[[:space:]]*$" <<< "$GAMEPAD_INFO"
}

check_system() {
  local COMMAND

  if [ "$EUID" -ne 0 ]; then
    printf 'Run this script with sudo.\n' >&2
    return 1
  fi

  for COMMAND in whiptail python3 systemctl timeout; do
    if ! command -v "$COMMAND" >/dev/null 2>&1; then
      printf 'Required command is not installed: %s\n' "$COMMAND" >&2
      return 1
    fi
  done

  if [ ! -t 0 ] || [ ! -t 1 ]; then
    printf 'Run this script in an interactive terminal.\n' >&2
    return 1
  fi

  WORK_DIR=$(mktemp -d) || return 1
  TTY_STATE=$(stty -g </dev/tty) || return 1
  if [ ! -f "$BLUEZ_HELPER" ]; then
    printf 'Missing Bluetooth backend: %s\n' "$BLUEZ_HELPER" >&2
    return 1
  fi
  if ! python3 -c 'import dbus_next' 2>/dev/null; then
    printf 'Install the Bluetooth dependency: sudo apt install python3-dbus-next\n' >&2
    return 1
  fi
}

stop_job() {
  if [ -n "$JOB_PID" ]; then
    kill "$JOB_PID" 2>/dev/null || true
    wait "$JOB_PID" 2>/dev/null || true
  fi
}

job_command() {
  local STATUS
  "$@" </dev/null &
  JOB_PID=$!
  wait "$JOB_PID"
  STATUS=$?
  JOB_PID=''
  return "$STATUS"
}

prepare_bluetooth() {
  trap - EXIT
  trap 'stop_job; exit 143' INT TERM
  if ! job_command timeout --kill-after=1 "$READ_TIMEOUT" systemctl is-active --quiet bluetooth; then
    if ! job_command timeout --kill-after=1 10 systemctl start bluetooth; then
      printf 'Could not start bluetooth.service.\n' >"$WORK_DIR/backend-error"
      return 1
    fi
  fi
  exec python3 "$BLUEZ_HELPER" serve "$WORK_DIR" --adapter "$BT_ADAPTER"
}

start_bluetooth() {
  rm -f -- "$WORK_DIR/backend-ready" "$WORK_DIR/backend-error"
  prepare_bluetooth >"$WORK_DIR/bluetooth-output" 2>&1 </dev/null &
  INIT_PID=$!
}

ensure_bluetooth() {
  if [ -z "$INIT_PID" ] || ! kill -0 "$INIT_PID" 2>/dev/null; then
    [ -z "$INIT_PID" ] || wait "$INIT_PID" 2>/dev/null
    start_bluetooth
  fi
  [ ! -f "$WORK_DIR/backend-ready" ] || return 0
  run_bt 'Preparing Bluetooth. The service and adapter will be enabled if needed...' ready || {
    operation_error 'Bluetooth setup failed. Select an action to retry.'
    return 1
  }
}

refresh_gamepads() {
  run_bt 'Refreshing gamepad information...' refresh || {
    operation_error 'Could not refresh gamepad information.'
    return 1
  }
}

select_gamepad() {
  local MODE="$1" ADDRESS INFO ALIAS STATUS PROMPT
  local ITEMS=()
  GAMEPAD_MAC=''
  GAMEPAD_ALIAS=''

  [ -f "$WORK_DIR/cache/index" ] || refresh_gamepads || return 1
  while true; do
    ITEMS=()
    while IFS= read -r ADDRESS; do
      [ -f "$WORK_DIR/cache/$ADDRESS" ] || continue
      INFO=$(cat "$WORK_DIR/cache/$ADDRESS")
      if [ -n "$MODE" ]; then
        grep -Eq "^[[:space:]]*$MODE: yes[[:space:]]*$" <<< "$INFO" || continue
      fi
      ALIAS=$(sed -n 's/^[[:space:]]*Alias: //p' <<< "$INFO")
      ALIAS="${ALIAS:-$ADDRESS}"
      STATUS='Disconnected'
      if grep -Eq '^[[:space:]]*Connected: yes[[:space:]]*$' <<< "$INFO"; then
        STATUS='Connected'
      fi
      ITEMS+=("$ADDRESS" "$ALIAS ($STATUS)")
    done <"$WORK_DIR/cache/index"
    PROMPT='Select a gamepad. Bluetooth status updates in the background:'
    if [ "${#ITEMS[@]}" -eq 0 ]; then
      PROMPT='No matching gamepads. Refresh the list or use Pair New Gamepad.'
    fi
    GAMEPAD_MAC=$(ui --ok-button Select --cancel-button Back \
      --menu "$PROMPT" "$WT_HEIGHT" "$WT_WIDTH" 10 \
      "${ITEMS[@]}" 'Refresh' 'Reload saved devices and status' \
      3>&1 1>&2 2>&3) || return 1
    if [ "$GAMEPAD_MAC" = Refresh ]; then
      refresh_gamepads || return 1
      continue
    fi
    use_cached_gamepad && return 0
  done
}

scan_gamepads() {
  ui --yes-button Continue --no-button Back --yesno \
    "Hold SHARE + HOME on the gamepad until the light starts flashing.\n\nSelect Continue to scan for $SCAN_TIMEOUT seconds." \
    12 "$WT_WIDTH" || return 1
  PROGRESS_SECONDS="$SCAN_TIMEOUT" run_bt \
    "Scanning for gamepads for $SCAN_TIMEOUT seconds. Keep the gamepad in pairing mode..." \
    scan "$SCAN_TIMEOUT" || {
    operation_error 'Bluetooth discovery failed.'
    return 1
  }
}

pair_gamepad() {
  NEW_PAIR=no
  run_bt "Pairing $GAMEPAD_ALIAS. Keep the gamepad in pairing mode...\nAllow up to $CONNECT_TIMEOUT seconds." \
    pair "$GAMEPAD_MAC" || {
    operation_error 'Pairing failed.'
    return 1
  }
  if grep -q '^New pairing: yes$' "$WORK_DIR/output"; then
    NEW_PAIR=yes
  fi
  use_cached_gamepad
}

connect_gamepad() {
  run_bt "Connecting $GAMEPAD_ALIAS.\nIf the gamepad is asleep, press HOME. Pairing mode is not needed." \
    connect "$GAMEPAD_MAC" || {
    operation_error 'Connection failed.'
    return 1
  }
  use_cached_gamepad
  message "$(cat "$WORK_DIR/output")"
}

rename_gamepad() {
  local MODE="${1:-manual}" NAME ACTUAL_NAME CANCEL=Back
  [ "$MODE" != optional ] || CANCEL=Skip
  NAME=$(ui --ok-button Save --cancel-button "$CANCEL" \
    --inputbox 'Enter a name for the gamepad. Leave empty to keep the current name:' \
    11 "$WT_WIDTH" "$GAMEPAD_ALIAS" 3>&1 1>&2 2>&3) || return 0
  [ -n "$NAME" ] && [ "$NAME" != "$GAMEPAD_ALIAS" ] || return 0

  run_bt 'Renaming the gamepad. Please wait...' rename "$GAMEPAD_MAC" "$NAME" || {
    operation_error 'Could not rename the gamepad.'
    return 1
  }
  use_cached_gamepad || {
    operation_error 'Could not verify the new gamepad name.'
    return 1
  }
  ACTUAL_NAME=$(info_value Alias)
  if [ "$ACTUAL_NAME" != "$NAME" ]; then
    operation_error 'Could not verify the new gamepad name.'
    return 1
  fi
  GAMEPAD_ALIAS="$NAME"
  if [ "$MODE" != optional ]; then
    message "Gamepad renamed to $NAME."
  fi
}

pair_new_gamepad() {
  local NAME ALIAS OFFER_NAME=no
  scan_gamepads && select_gamepad '' || return 1
  pair_gamepad || return 1
  NAME=$(info_value Name)
  ALIAS=$(info_value Alias)
  if [ "$NEW_PAIR" = yes ]; then
    if [ -z "$ALIAS" ] || [ "$ALIAS" = "$NAME" ] || [ "$ALIAS" = "$GAMEPAD_MAC" ]; then
      OFFER_NAME=yes
    fi
  fi
  if [ "$OFFER_NAME" = yes ]; then
    rename_gamepad optional
  fi
  if ! has_property Paired yes; then
    message 'The gamepad did not retain its pairing. Put it in pairing mode and try again.'
    return 1
  fi
  if [ "$(info_value Bonded)" = no ]; then
    message 'The gamepad paired temporarily, but its pairing keys were not saved. Pairing is not complete.'
    return 1
  fi
  if [ "$(info_value Connected)" = yes ]; then
    message "Pairing saved.\n\n$GAMEPAD_ALIAS is connected."
  else
    message "Pairing saved.\n\nIf the gamepad keeps flashing, switch it to normal operating mode, then select Connect.\n\nFor PS-style gamepads, use HOME without SHARE.\n\nYou do not need to pair again."
  fi
}

disconnect_gamepad() {
  run_bt "Disconnecting $GAMEPAD_ALIAS. Please wait..." disconnect "$GAMEPAD_MAC" || {
    operation_error 'Could not disconnect the gamepad.'
    return 1
  }
  use_cached_gamepad
  message "$(cat "$WORK_DIR/output")"
}

forget_gamepad() {
  ui --defaultno --yes-button Forget --no-button Back --yesno \
    "Forget $GAMEPAD_ALIAS ($GAMEPAD_MAC)?\n\nYou will need to pair this gamepad again to use it." \
    12 "$WT_WIDTH" || return 0
  run_bt "Removing $GAMEPAD_ALIAS. Please wait..." remove "$GAMEPAD_MAC" || {
    operation_error 'Could not remove the gamepad.'
    return 1
  }
  message "$GAMEPAD_ALIAS has been removed."
}

signal_text() {
  local RSSI SIGNAL
  RSSI=$(info_value RSSI)
  SIGNAL=''
  if [[ "$RSSI" =~ \((-?[0-9]+)\) ]]; then
    SIGNAL="${BASH_REMATCH[1]} dBm"
  elif [[ "$RSSI" =~ ^-?[0-9]+$ ]]; then
    SIGNAL="$RSSI dBm"
  fi
  printf '%s\n' "$SIGNAL"
}

show_gamepad_info() {
  local NAME PAIRED CONNECTED TRUSTED SIGNAL
  use_cached_gamepad || return 1
  NAME=$(info_value Name)
  PAIRED=$(info_value Paired)
  CONNECTED=$(info_value Connected)
  TRUSTED=$(info_value Trusted)
  SIGNAL=$(signal_text)
  message "Name: $GAMEPAD_ALIAS\nModel: ${NAME:-Unknown}\nMAC address: $GAMEPAD_MAC\n\nConnected: ${CONNECTED:-unknown}\nPaired: ${PAIRED:-unknown}\nTrusted: ${TRUSTED:-unknown}${SIGNAL:+\n\nSignal (last seen): $SIGNAL}\n\nStatus updates in the background. Reopen this view to see changes."
}

gamepads_menu() {
  local ACTION SIGNAL
  while select_gamepad ''; do
    while true; do
      use_cached_gamepad || break
      SIGNAL=$(signal_text)
      ACTION=$(ui --ok-button Select --cancel-button Back \
        --menu "$GAMEPAD_ALIAS\n$GAMEPAD_MAC\nConnected: $(info_value Connected)    Paired: $(info_value Paired)${SIGNAL:+\nSignal (last seen): $SIGNAL}" \
        "$WT_HEIGHT" "$WT_WIDTH" 6 \
        '1 Information' 'View name, address, status and signal' \
        '2 Connect' 'Connect this paired gamepad' \
        '3 Disconnect' 'Disconnect this gamepad' \
        '4 Forget' 'Unpair and remove this gamepad' \
        '5 Refresh' 'Update this gamepad status' \
        3>&1 1>&2 2>&3) || break
      case "$ACTION" in
        '1 Information') show_gamepad_info ;;
        '2 Connect') connect_gamepad ;;
        '3 Disconnect') disconnect_gamepad ;;
        '4 Forget') forget_gamepad; break ;;
        '5 Refresh') run_bt 'Refreshing gamepad information...' info "$GAMEPAD_MAC" || operation_error 'Could not refresh gamepad status.' ;;
      esac
    done
  done
}

show_about() {
  message 'RBM Gamepad\nROBOMARVEL Gamepad Configuration\n\nBluetooth gamepad management for Linux.\n\nPair and connect gamepads, rename them, view their status or remove a saved pairing.\n\nSeveral gamepads can be managed independently.\n\nPair once. For everyday use, turn on the gamepad normally and select Connect if needed.'
}

advanced_menu() {
  local ACTION
  while true; do
    ACTION=$(ui --ok-button Select --cancel-button Back \
      --menu 'Advanced Options' "$WT_HEIGHT" "$WT_WIDTH" 10 \
      '1 Rename' 'Change a saved gamepad name' \
      '2 Information' 'View gamepad information' \
      3>&1 1>&2 2>&3) || return 0
    case "$ACTION" in
      '1 Rename') select_gamepad Paired && rename_gamepad ;;
      '2 Information') select_gamepad '' && show_gamepad_info ;;
    esac
  done
}

main() {
  local ACTION
  check_system || return 1
  start_bluetooth

  while true; do
    ACTION=$(ui --ok-button Select --cancel-button Finish \
      --menu 'Select an action. Bluetooth is enabled automatically if needed.' "$WT_HEIGHT" "$WT_WIDTH" 10 \
      '1 Connect' 'Connect a paired gamepad' \
      '2 Pair' 'Pair a new gamepad' \
      '3 Disconnect' 'Disconnect a gamepad' \
      '4 Forget' 'Unpair and remove a gamepad' \
      '5 Advanced' 'Rename or view gamepad information' \
      '6 Gamepads' 'Browse gamepads and view information' \
      '7 About' 'About this utility' \
      3>&1 1>&2 2>&3) || break

    if [ "$ACTION" = '7 About' ]; then
      show_about
      continue
    fi
    ensure_bluetooth || continue
    case "$ACTION" in
      '1 Connect') select_gamepad Paired && connect_gamepad ;;
      '2 Pair') pair_new_gamepad ;;
      '3 Disconnect') select_gamepad Connected && disconnect_gamepad ;;
      '4 Forget') select_gamepad '' && forget_gamepad ;;
      '5 Advanced') advanced_menu ;;
      '6 Gamepads') gamepads_menu ;;
    esac
  done
  return 0
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
