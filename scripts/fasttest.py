from serial import Serial
from threading import Thread
from argparse import ArgumentParser
import proto
import time

PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
SPEED = 921600


class FakeNode:
    def __init__(self):
        self.ser = Serial(port=PORT, baudrate=921600)
        self.first_status_recieved = False
        self.read_thread = Thread(target=self.read_loop, daemon=True)
        self.read_thread.start()

    def read_loop(self):
        while True:
            ret = proto.read_packet(self.ser)
            if ret is None:
                continue
            type, payload = ret
            if type == proto.PacketType.STATUS:
                self.handle_status(payload)
            elif type == proto.PacketType.GET_CONFIG:
                self.handle_config(payload)

    def handle_status(self, status: proto.StatusPacket):
        if self.first_status_recieved:
            return
        motors = ("front_left", "front_right", "rear_left", "rear_right")
        msg = ""
        for name in motors:
            motor = getattr(status, name)
            msg += f"[{name}] T={motor.target:.1f} S={motor.speed:.1f} E={motor.effort:.1f} "
        print(msg)

    def handle_config(self, config):
        print("GET CONFIG:", config)

    def send_speeds(self, A, B, C, D):
        print("SEND:", A, B, C, D)
        pack = proto.ControlPacket(float(A), float(B), float(C), float(D))
        proto.write_packet(self.ser, pack)

    def set_config(self, config: proto.SetConfig):
        proto.write_packet(self.ser, config)
        proto.write_null_packet(self.ser, proto.PacketType.SAVE_CONFIG)
        proto.write_null_packet(self.ser, proto.PacketType.GET_CONFIG)


def run_test(node: FakeNode):
    SPEED = 5
    try:
        time.sleep(1)
        node.send_speeds(SPEED, 0, 0, 0)
        time.sleep(1)
        node.send_speeds(0, SPEED, 0, 0)
        time.sleep(1)
        node.send_speeds(0, 0, SPEED, 0)
        time.sleep(1)
        node.send_speeds(0, 0, 0, SPEED)
        time.sleep(1)
    finally:
        node.send_speeds(0, 0, 0, 0)


def gen_config(data):
    config = proto.ConfigV1()
    config.robot_id = data["robot_id"].encode().ljust(16, b"\x00")
    config.encoder_cpr = int(data["encoder_cpr"])

    motors = [
        ("front_left", config.motors.front_left),
        ("front_right", config.motors.front_right),
        ("rear_left", config.motors.rear_left),
        ("rear_right", config.motors.rear_right),
    ]

    for name, motor in motors:
        motor.motor_dir = data["motors"][name]["motor_dir"]
        motor.encoder_dir = data["motors"][name]["encoder_dir"]

    pack = proto.SetConfig()
    pack.new_config = config

    pack.mask = (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4)
    return pack


CONFIG_PRESETS = {
    "200": {
        "encoder_cpr": 330,
        "motors": {
            "front_left": {"motor_dir": True, "encoder_dir": True},
            "front_right": {"motor_dir": False, "encoder_dir": True},
            "rear_left": {"motor_dir": True, "encoder_dir": True},
            "rear_right": {"motor_dir": False, "encoder_dir": True},
        },
    },
    "170": {
        "encoder_cpr": 616,
        "motors": {
            "front_left": {"motor_dir": True, "encoder_dir": False},
            "front_right": {"motor_dir": False, "encoder_dir": False},
            "rear_left": {"motor_dir": True, "encoder_dir": False},
            "rear_right": {"motor_dir": False, "encoder_dir": False},
        },
    },
}


def set_config(node, rpm: str, id: str):
    assert rpm and id
    config = CONFIG_PRESETS[rpm]
    config = {**config, "robot_id": id}
    pack = gen_config(config)
    node.set_config(pack)
    time.sleep(1.0)


def main(action, rpm: str, id: str):
    node = FakeNode()
    if action == "test":
        run_test(node)
    if action == "config":
        set_config(node, rpm, id)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("-a", "--action", default="test")
    parser.add_argument("--rpm", default="200")
    parser.add_argument("--id", default="rbm-000")
    args = parser.parse_args()
    main(args.action, args.rpm, args.id)
