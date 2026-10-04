#!/bin/bash
if [ ! -d /src/install ]; then make build; fi
if [ -f /src/.autostart ]; then tmuxp load -d /src/tmuxp.yaml; fi
openvscode-server --host 0.0.0.0 --port 8000 --without-connection-token &
trap : TERM INT; sleep infinity & wait
