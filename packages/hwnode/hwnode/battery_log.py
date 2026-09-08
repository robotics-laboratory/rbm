import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray
#from datetime import datetime
import os

class BatteryLogger(Node):
    def __init__(self):
        super().__init__("battery_logger")

        self.voltage = 0.0
        self.current = 0.0
        self.percent = 0.0

        self.have_data = False

        self.file = open("/src/battery.txt", "a")

        self.subscription = self.create_subscription(
            Float32MultiArray,
            "/hardware/status",
            self.status_callback,
            10
        )
        self.start_time = self.get_clock().now()

        self.timer = self.create_timer(
            10.0,
            self.log_data
        )

        self.get_logger().info("Battery logger started")

    def status_callback(self, msg):
        if len(msg.data) < 19:
            return

        self.voltage = msg.data[16]
        self.current = msg.data[17]
        self.percent = msg.data[18]

        self.have_data = True

    def log_data(self):
        if not self.have_data:
            return

        elapsed = (
            self.get_clock().now() - self.start_time
        ).nanoseconds * 1e-9

        #time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.file.write(
            f"time={elapsed:.1f}s "
            f"voltage={self.voltage:.3f}V "
            f"current={self.current:.3f}mA "
            f"percent={self.percent:.2f}%\n"
        )

        self.file.flush()
        os.fsync(self.file.fileno())


def main(args=None):
    rclpy.init(args=args)

    node = BatteryLogger()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.file.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
