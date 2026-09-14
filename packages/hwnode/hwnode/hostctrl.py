from threading import Thread
from hwnode import proto
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
    def __init__(self, logger, on_stats, on_get_config, on_set_config):
        self.stats_cb = on_stats or (lambda *_: None)
        self.get_config_cb = on_get_config or (lambda *_: None)
        self.set_config_cb = on_set_config or (lambda *_: None)
        self.logger = logger
        self.url = f"ws://{get_host_ip()}/hostctl"
        self.ws = websocket.WebSocketApp(
            self.url,
            on_message=self.on_message,
            on_open=lambda *_: self.logger.info(f"Host control socket connected: {self.url}"),
            on_error=lambda _, err: self.logger.info(f"Host control socket error: {err}"),
        )
        self.thread = Thread(target=self.ws.run_forever, kwargs={"reconnect": 5}, daemon=True)
        self.thread.start()

    def on_message(self, _, data):
        try:
            payload = json.loads(data)
            type = payload.get("type")
            data = payload.get("data")
            if type == "stats": self.on_stats(data)
            if type == "get-config": self.on_get_config(data)
            if type == "set-config": self.on_set_config(data)
        except Exception as err:
            self.logger.error(f"on message err: {err}")

    def on_stats(self, data: dict):
        status = proto.HostStatusPacket()
        for i, (name, ip) in enumerate(data["networks"].items()):
            if i >= 3: break
            net = proto.HostNetwork(name=name.encode(), ip=ip.encode())
            status.networks[i] = net
        status.load = proto.HostLoad(**data["load"])
        self.stats_cb(status)

    def on_get_config(self, _):
        self.logger.info("on get config")
        self.get_config_cb()

    def on_set_config(self, data: dict):
        self.logger.info(f"on set config: {data}")
        config = proto.ConfigV0()
        config.robot_id = data["robot_id"].encode().ljust(16, b"\x00")
        config.encoder_cpr = int(data["encoder_cpr"])
        for i, (name, _) in enumerate(proto.Dir._fields_):
            setattr(config.direction_mot, name, data["direction_mot"][i])
            setattr(config.direction_enc, name, data["direction_enc"][i])
        pack = proto.SetConfig()
        pack.new_config = config
        # FIXME: хардкод, поменять на енамы
        pack.mask = (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4)
        self.set_config_cb(pack)

    def send_act(self, act: str):
        try:
            data = {"type": "action", "data": act}
            self.ws.send(json.dumps(data))
        except Exception as err:
            self.logger.error(f"send act err: {err}")

    def send_config(self, config):
        try:
            data = proto.ctypes_to_dict(config)
            data = {"type": "config", "data": data}
            self.ws.send(json.dumps(data))
        except Exception as err:
            self.logger.error(f"send config err: {err}")
