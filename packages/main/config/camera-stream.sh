#!/bin/bash
set -euo pipefail

# 640x480, 1280x720, 1920x1080
WIDTH=640
HEIGHT=480
BITRATE=2000

model=$(cat /opt/rbm/model)
encoder=""

if [ "$model" = "raspberry" ]; then
  encoder=(x264enc tune=zerolatency speed-preset=ultrafast bitrate=$BITRATE key-int-max=30)
elif [ "$model" = "rdk" ]; then
  encoder=(hoboth264enc bitrate=$BITRATE)
else
  echo "Unknown board model: $model" >&2
  exit 1
fi

exec gst-launch-1.0 -e \
  v4l2src device=/dev/video0 ! \
  "image/jpeg,width=$WIDTH,height=$HEIGHT,framerate=30/1" ! \
  jpegdec ! videoconvert ! 'video/x-raw,format=NV12' ! \
  "${encoder[@]}" ! \
  h264parse config-interval=-1 ! \
  rtspclientsink "location=rtsp://localhost:${RTSP_PORT}/${MTX_PATH}" protocols=tcp
