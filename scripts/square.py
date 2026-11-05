import math
import time
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from drive import Drive
from turn import Turn

SIDE_LENGTH = 1.0
TURN_ANGLE = 90.0
TURN_MARGIN = 8.0


class OdomMonitor(Node):
    def __init__(self):
        super().__init__('square_odom_monitor')

        self.odom_sub = self.create_subscription(Odometry, '/hardware/odom', self.odom_callback, 10)

        self.stop_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.pose = None
        self.last_odom_time = None

    def odom_callback(self, msg):
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        )

        self.pose = (x, y, yaw)
        self.last_odom_time = time.monotonic()

    def stop_robot(self):
        self.stop_pub.publish(Twist())


def run_controller(executor, monitor, node, label):
    executor.add_node(node)
    try:
        while rclpy.ok() and not node.done:
            executor.spin_once(timeout_sec=0.1)
        if not node.done:
            raise RuntimeError('ROS 2 stopped unexpectedly')
        if not node.success:
            raise RuntimeError(f'Failed: {label}')

    finally:
        monitor.stop_robot()
        executor.remove_node(node)
        node.destroy_node()


def main():
    rclpy.init()
    monitor = OdomMonitor()
    executor = SingleThreadedExecutor()
    executor.add_node(monitor)
    try:
        deadline = time.monotonic() + 5.0

        while rclpy.ok() and monitor.pose is None:
            if time.monotonic() > deadline:
                raise RuntimeError('Odometry unavailable')

            executor.spin_once(timeout_sec=0.1)

        if monitor.pose is None:
            raise RuntimeError('No initial odometry')

        start_x, start_y, start_yaw = monitor.pose

        for side in range(1, 5):
            run_controller(executor, monitor, Drive(SIDE_LENGTH), f'Side {side}/4: drive {SIDE_LENGTH} m')

            run_controller(executor, monitor, Turn(TURN_ANGLE, TURN_MARGIN), f'Corner {side}/4: turn {TURN_ANGLE} deg')

        if (monitor.pose is None or monitor.last_odom_time is None or time.monotonic() - monitor.last_odom_time > 0.5):
            raise RuntimeError('Final odometry unavailable')

        end_x, end_y, end_yaw = monitor.pose
        dx = end_x - start_x
        dy = end_y - start_y
        position_error = math.hypot(dx, dy)
        yaw_error = (end_yaw - start_yaw + math.pi) % (2.0 * math.pi) - math.pi

    except KeyboardInterrupt:
        print('\nSquare test interrupted')

    except Exception as error:
        print(f'\nSquare test aborted: {error}')

    finally:
        for _ in range(10):
            monitor.stop_robot()
            executor.spin_once(timeout_sec=0.05)

        executor.remove_node(monitor)
        monitor.destroy_node()
        executor.shutdown()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()

