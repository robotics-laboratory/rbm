from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager
import subprocess as sp
import socket
import psutil
import asyncio
import uvicorn

# TODO: На подумать: nicegui использует FastAPI под капотом, в целом можно вклиниться в тот же app
app = FastAPI()
INTERFACES = {"wlan0": "wifi", "eth0": "eth", "tailscale0": "vpn"}
clients: list[WebSocket] = []

@app.websocket("/ws")
async def websocket(websocket: WebSocket):
    await websocket.accept()
    print("Client connected")
    clients.append(websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            print(data)
    except WebSocketDisconnect:
        print("Client disconnected")
        clients.remove(websocket)

def get_stats():
    cpu = psutil.cpu_percent(interval=1.0)
    mem = psutil.virtual_memory().percent
    bpu = 0.0  # TODO
    # TODO: Можно частично переписать на парсинг hrut_somstatus
    temp = int(open('/sys/class/hwmon/hwmon0/temp3_input').read()) / 1000
    return {"cpu": cpu, "mem": mem, "bpu": bpu, "temp": temp}

def get_networks():
    addrs = {}
    for name, if_addrs in psutil.net_if_addrs().items():
        name = INTERFACES.get(name)
        if name is None: continue
        for addr in if_addrs:
            if addr.family == socket.AF_INET:
                addrs[name] = addr.address
                break

    keys = list(INTERFACES.values())
    pairs = list(addrs.items())
    pairs.sort(key=lambda x: keys.index(x[0]))
    return dict(pairs[:3])

async def updater():
    while True:
        try:
            stats = await asyncio.to_thread(get_stats)
            networks = await asyncio.to_thread(get_networks)
            data = {"load": stats, "networks": networks}
            print(">>>", data)
            for client in clients:
                try: await client.send_json(data)
                except Exception as err: print(f"err: {err}")
        except Exception as err:  print(f"err: {err}")

@asynccontextmanager
async def lifespan(_):
    update_task = asyncio.create_task(updater())
    yield
    update_task.cancel()
    await asyncio.gather(update_task, return_exceptions=True)

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=6767)
