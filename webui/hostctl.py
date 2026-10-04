from fastapi import WebSocket, WebSocketDisconnect
from pathlib import Path
import socket
import psutil
import asyncio
import yaml


class HostControl:
    NETWORKS = {"wlan0": "wifi", "eth0": "eth", "wlan1": "hotspot"}
    CONFIG_PATH = Path("/opt/rbm/esp-config.yaml")
    HOTSPOT_CONN_FILE = Path("/etc/NetworkManager/system-connections/hotspot.nmconnection")
    
    def __init__(self):
        self.clients: list[WebSocket] = []
        self.stats = None
        self.esp_config = None
        self.hostname = self.get_hostname()
        self.saved_config = self.read_saved_config()

    def log(self, msg: str):
        print(f"[hostctl] {msg}")

    def read_saved_config(self):
        try:
            if self.CONFIG_PATH.exists():
                return yaml.safe_load(open(self.CONFIG_PATH))
        except Exception as err:
            self.log(f"read config error: {err}")

    def get_stats(self):
        cpu = psutil.cpu_percent(interval=1.0)
        mem = psutil.virtual_memory().percent
        bpu = 0.0  # TODO
        temp = int(open('/sys/class/hwmon/hwmon0/temp3_input').read()) / 1000
        return {"cpu": cpu, "mem": mem, "bpu": bpu, "temp": temp}

    def get_networks(self):
        addrs = {}
        for name, if_addrs in psutil.net_if_addrs().items():
            name = self.NETWORKS.get(name)
            if name is None: continue
            for addr in if_addrs:
                if addr.family == socket.AF_INET:
                    addrs[name] = addr.address
                    break
        keys = list(self.NETWORKS.values())
        pairs = list(addrs.items())
        pairs.sort(key=lambda x: keys.index(x[0]))
        return dict(pairs[:3])

    async def broadcast(self, data: dict):
        for client in self.clients:
            try:
                await client.send_json(data)
            except Exception as err:
                self.log(f"broadcast err: {err}")

    async def update_loop(self):
        while True:
            try:
                stats = await asyncio.to_thread(self.get_stats)
                networks = await asyncio.to_thread(self.get_networks)
                self.stats = {"load": stats, "networks": networks}
                await self.broadcast({"type": "stats", "data": self.stats})
            except Exception as err:
                self.log(f"update loop err: {err}")

    async def ensure_hotspot_interface(self):
        cmd = "iw dev wlan1 info"
        proc = await asyncio.subprocess.create_subprocess_shell(cmd)
        await proc.communicate()
        if proc.returncode != 0:
            cmd = "iw dev wlan0 interface add wlan1 type __ap"
            proc = await asyncio.subprocess.create_subprocess_shell(cmd)
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                self.log(stderr.decode().strip())
                return False
        return True

    async def hotspot(self, enabled : bool):
        self.log(f"Hotspot mode {'ON' if enabled else 'OFF'}")
        if enabled:
            ok = await self.ensure_hotspot_interface()
            if not ok: return
        cmd = f"nmcli connection {'up' if enabled else 'down'} hotspot"
        proc = await asyncio.create_subprocess_shell(cmd)
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            self.log(f"nmcli error:\n{stdout.decode()}\n{stderr.decode()}")

    def round_floats(self, obj, digits=5):
        if isinstance(obj, float):
            return round(obj, digits)
        elif isinstance(obj, dict):
            return {k: self.round_floats(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.round_floats(item) for item in obj]
        return obj

    def get_hostname(self):
        return open("/etc/hostname").read().strip()

    async def update_hostname(self, hostname: str):
        self.log(f"Updating hostname {self.hostname} -> {hostname}")
        self.hostname = hostname
        cmd = f"hostnamectl hostname {hostname}"
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()
        cmd = f"sed -i 's/^ssid=.*/ssid={hostname}/' {self.HOTSPOT_CONN_FILE}"
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()
        cmd = "nmcli connection reload"
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()

    async def on_config(self, data):
        self.esp_config = self.round_floats(data)
        if self.saved_config != self.esp_config:
            self.log("Updating saved config...")
            with open(self.CONFIG_PATH, "w") as file:
                yaml.safe_dump(self.esp_config, file)
                self.saved_config = self.esp_config
            hostname = self.esp_config.get("robot_id")
            if hostname is not None and hostname != self.hostname:
                await self.update_hostname(hostname)

    async def reboot(self):
        await asyncio.subprocess.create_subprocess_shell("reboot now")

    async def ws_handler(self, websocket: WebSocket):
        await websocket.accept()
        self.log("WS client connected")
        self.clients.append(websocket)
        await websocket.send_json({"type": "get-config"})
        try:
            while True:
                data = await websocket.receive_json()
                self.log(f"Incoming message: {data}")
                type, payload = data.get("type"), data.get("data")
                if type == "config":
                    await self.on_config(payload)
                elif type == "action":
                    if payload == "modem_on":
                        await self.hotspot(True)
                    elif payload == "modem_off":
                        await self.hotspot(False)
                    elif payload == "reboot":
                        await self.reboot()
        except WebSocketDisconnect:
            self.log("WS client disconnected")
        except Exception as err:
            self.log(f"Unhandled err: {err}")
        finally:
            self.clients.remove(websocket)
