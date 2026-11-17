#!/bin/bash
set -euo pipefail

model=$(tr -d '\0' < /run/rbm-board-model)

case "$model" in
  "Raspberry Pi 5"*)
    encoder=(x264enc tune=zerolatency speed-preset=ultrafast
             bitrate=2000 key-int-max=30 '!' 'video/x-h264,profile=constrained-baseline')
    ;;
  "D-Robotics RDK X5"*)
    encoder=(hoboth264enc bitrate=2000)
    ;;
  *)
    printf 'Неизвестная модель платы: %s\n' "$model" >&2
    exit 1
    ;;
esac

printf 'Камера: %s, энкодер: %s\n' "$model" "${encoder[0]}"

exec gst-launch-1.0 -e \
  v4l2src device=/dev/video0 ! \
  'image/jpeg,width=640,height=480,framerate=30/1' ! \
  jpegdec ! videoconvert ! 'video/x-raw,format=NV12' ! \
  "${encoder[@]}" ! \
  h264parse config-interval=-1 ! \
  rtspclientsink "location=rtsp://localhost:${RTSP_PORT}/${MTX_PATH}" protocols=tcp
