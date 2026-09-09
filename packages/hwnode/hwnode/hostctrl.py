from threading import Thread
from hwnode.proto import HostStatusPacket, HostLoad, HostNetwork
import websocket
import socket
import struct
import json

def get_host_ip():
    with open("/proc/net/route") as file:
        for line in file:
            fields = line.strip().split()
            if fields[1] == '00000000': 
                return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    return "127.0.0.1"


class HostBridge:
    def __init__(self, callback, logger):
        self.callback = callback
        self.logger = logger
        self.url = f"ws://{get_host_ip()}:6767/ws"
        self.ws = websocket.WebSocketApp(
            self.url,
            on_message=self.on_message,
            on_open=lambda _: self.logger.info(f"Host control socket connected: {self.url}"),
            on_error=lambda _: self.logger.info(f"Host control socket error"),
        )
        self.thread = Thread(target=self.ws.run_forever, kwargs={"reconnect": 5}, daemon=True)
        self.thread.start()

    def on_message(self, _, data):
        try:
            data = json.loads(data)
            status = HostStatusPacket()
            for i, (name, ip) in enumerate(data["networks"].items()):
                if i >= 3: break
                net = HostNetwork(name=name.encode(), ip=ip.encode())
                status.networks[i] = net
            status.load=HostLoad(**data["load"])
            self.callback(status)
        except Exception as err:
            self.logger.error(f"callback err: {err}")
