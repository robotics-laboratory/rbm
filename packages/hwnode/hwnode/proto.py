from cobs import cobs
from anycrc import Model
from serial import Serial
from enum import IntEnum
import logging
import struct
import ctypes

CRC = Model("CRC8-SMBUS")   # poly=0x07, init=0x00, ref_in=False, ref_out=False, xor_out=0x00


class PacketType(IntEnum):
    STATUS = 1
    IMU = 2
    TOF = 3
    CONTROL = 4
    PID = 5
    HOST_STATUS = 6
    HOST_CONTROL = 7
    GET_CONFIG = 8
    SET_CONFIG = 9
    SAVE_CONFIG = 10
    LOG = 11


class MotorState(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("target", ctypes.c_float),
        ("speed", ctypes.c_float),
        ("angle", ctypes.c_float),
        ("effort", ctypes.c_float),
    ]

    def __repr__(self):
        fields = {name: getattr(self, name) for name, _ in self._fields_}
        return f"{self.__class__.__name__}({fields})"


class PidState(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("kp", ctypes.c_float),
        ("ki", ctypes.c_float),
        ("kd", ctypes.c_float),
        ("limit", ctypes.c_float),
        ("lpf_tf", ctypes.c_float),
    ]

    def __repr__(self):
        fields = {name: getattr(self, name) for name, _ in self._fields_}
        return f"{self.__class__.__name__}({fields})"


class StatusPacket(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("front_left", MotorState),
        ("front_right", MotorState),
        ("rear_left", MotorState),
        ("rear_right", MotorState),
        ("batt_voltage", ctypes.c_float),
        ("batt_current", ctypes.c_float),
        ("batt_percent", ctypes.c_float),
    ]

    def __repr__(self):
        fields = {name: getattr(self, name) for name, _ in self._fields_}
        return f"{self.__class__.__name__}({fields})"


class ImuPacket(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("acc", ctypes.c_float * 3),
        ("gyr", ctypes.c_float * 3),
        ("quat", ctypes.c_float * 4),
    ]

    def __repr__(self):
        return str({"acc": list(self.acc), "gyr": list(self.gyr), "quat": list(self.quat),})


class TofPacket(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("distance_mm", ctypes.c_int16 * 64),
        ("reflectance", ctypes.c_uint8 * 64),
        ("status", ctypes.c_uint8 * 64),
    ]

    def __repr__(self):
        return str({"dist_mm": list(self.distance_mm), "ref": list(self.reflectance), "status": list(self.status)})

class ControlPacket(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("front_left", ctypes.c_float),
        ("front_right", ctypes.c_float),
        ("rear_left", ctypes.c_float),
        ("rear_right", ctypes.c_float),
    ]

    def __repr__(self):
        fields = {name: getattr(self, name) for name, _ in self._fields_}
        return f"{self.__class__.__name__}({fields})"

class HostNetwork(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("name", ctypes.c_char * 4),
        ("ip", ctypes.c_char * 15),
    ]

class HostLoad(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("mem", ctypes.c_float),
        ("cpu", ctypes.c_float),
        ("npu", ctypes.c_float),
        ("temp", ctypes.c_float),
    ]

class HostStatusPacket(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("networks", HostNetwork * 3),
        ("load", HostLoad),
        ("hotspot_mode", ctypes.c_bool)
    ]

    def __repr__(self):
        return str({
            "networks": list(self.networks),
            "load": self.load
        })

class HostControlPacket(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("act", ctypes.c_char * 16),
    ]

    def __repr__(self):
        return self.act.decode("utf-8", errors="ignore").rstrip("\x00") 

#Fixme переписать, когда будет норм структура на стороне прошивки
# Переименовал моторы, но структуру все равно поменять
class MotorDir(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("motor_dir", ctypes.c_bool),
        ("encoder_dir", ctypes.c_bool),
    ]

class MotorDirConfig(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("front_left", MotorDir),
        ("front_right", MotorDir),
        ("rear_left", MotorDir),
        ("rear_right", MotorDir),
    ]

class ConfigV1(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("config_v", ctypes.c_uint32),
        ("firmware_v", ctypes.c_uint32),
        ("robot_id", ctypes.c_char * 16),
        ("encoder_cpr", ctypes.c_uint32),
        ("pid", PidState),
        ("motors", MotorDirConfig),
    ]

class SetConfig(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("mask", ctypes.c_uint8),
        ("new_config", ConfigV1),
    ]

class LogPacket(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("message", ctypes.c_char * 192)
    ]

def ctypes_to_dict(obj):
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="ignore")
    elif isinstance(obj, ctypes.Structure):
        return {field: ctypes_to_dict(getattr(obj, field)) for field, _ in obj._fields_}
    elif isinstance(obj, ctypes.Array):
        return [ctypes_to_dict(element) for element in obj]
    else:
        return obj


def read_packet(ser: Serial):
    try:
        frame = ser.read_until(b"\x00")
        frame = frame.rstrip(b"\x00")
        if len(frame) < 3:
            logging.error(f"FRAME TOO SMALL: {frame}")
            return
        frame = cobs.decode(frame)
        type, payload, crc = frame[0], frame[1:-1], frame[-1]
        type = PacketType(type)
        crc_check =  CRC.calc(payload)
        assert crc == crc_check, "crc check failed"
        if type == PacketType.STATUS:
            return type, StatusPacket.from_buffer_copy(payload)
        elif type == PacketType.IMU:
            return type, ImuPacket.from_buffer_copy(payload)
        elif type == PacketType.TOF:
            return type, TofPacket.from_buffer_copy(payload)
        elif type == PacketType.HOST_CONTROL:
            return type, HostControlPacket.from_buffer_copy(payload)
        elif type == PacketType.GET_CONFIG:
            return type, ConfigV1.from_buffer_copy(payload)
        elif type == PacketType.LOG:
            return type, LogPacket.from_buffer_copy(payload)

    except Exception as err:
        logging.error(f"PROTO ERR: {err}")


def write_packet(ser: Serial, packet):
    if isinstance(packet, ControlPacket):
        msg_type = PacketType.CONTROL
    elif isinstance(packet, PidState):
        msg_type = PacketType.PID
    elif isinstance(packet, HostStatusPacket):
        msg_type = PacketType.HOST_STATUS
    elif isinstance(packet, SetConfig):
        msg_type = PacketType.SET_CONFIG
    else:
        raise RuntimeError(f"Unknown packet type: {type(packet)}")

    payload = bytes(packet)
    crc = CRC.calc(payload).to_bytes(1, 'little')
    frame = cobs.encode(msg_type.to_bytes(1, 'little') + payload + crc) + b'\x00'
    ser.write(frame)
    ser.flush()


# FIXME: Сделать универсальную функцию (объединить с write_packet)
def write_null_packet(ser : Serial, msg_type: PacketType, payload : bytes = b""):
    crc = CRC.calc(payload).to_bytes(1, "little")
    frame = cobs.encode(msg_type.to_bytes(1, "little") + payload + crc) + b"\x00"
    ser.write(frame)
    ser.flush()


if __name__ == "__main__":
    from threading import Thread, main_thread
    import time
    
    PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
    SPEED = 921600
    ser = Serial(port=PORT, baudrate=SPEED)
    print("START") 
    while True:
        ret = read_packet(ser)

        if ret is None:
            continue

        packet_type, packet = ret

        if packet_type == PacketType.HOST_CONTROL:
            print(f"RECV <<< {packet_type.name}: {packet}")

    def send_speeds(a, b, c, d):
        pack = ControlPacket(float(a), float(-b), float(c), float(-d))
        print(f"SENDING >>> {pack}")
        #write_packet(ser, pack)

    def read_loop():
        while main_thread().is_alive():
            ret = read_packet(ser)
            if ret is not None:
                type, pack = ret
                print (f"RECV <<< {type.name}: {pack}")
    read_thread = Thread(target=read_loop, daemon=True)
    read_thread.start()

    for i in range(4):
        arr = [0] * 4
        arr[i] = 10
        send_speeds(*arr)
        time.sleep(1.0)

    send_speeds(0, 0, 0, 0)
