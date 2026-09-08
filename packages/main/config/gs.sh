gst-launch-1.0 -e v4l2src device=/dev/video0 ! \
video/x-raw,width=1920,height=1080,framerate=30/1 ! \
v4l2h264enc ! \
h264parse ! \
rtph264pay config-interval=1 pt=96 ! \
rtspclientsink location=rtsp://localhost:8554/yolo
#gdppay ! \
#udpsink host=127.0.0.1 port=8554
