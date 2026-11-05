
import argparse
import math
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry


class Turn(Node):
    def __init__(self, angle_deg, margin_deg):
        super().__init__('turn')

        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)

        self.odom_sub = self.create_subscription(Odometry, '/hardware/odom', self.odom_callback, 10)

        self.target_angle = math.radians(angle_deg)
        self.direction = 1.0 if angle_deg > 0 else -1.0
        self.stop_margin = math.radians(margin_deg)
        self.angular_command = 0.2 * self.direction
        self.prev_yaw = None
        self.total_yaw = 0.0
        self.state = 'WAITING'
        self.done = False
        self.created_at = time.monotonic()
        self.started_at = None
        self.last_odom_time = None
        self.stop_time = None
        self.last_log_time = 0.0
        self.success = False

        self.timeout = max(10.0, abs(self.target_angle) / 0.8 * 3.0 + 5.0)
        self.timer = self.create_timer(0.1, self.control_loop)

    def odom_callback(self, msg):
        q = msg.pose.pose.orientation

        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        )

        now = time.monotonic()
        self.last_odom_time = now

        if self.prev_yaw is None:
            self.prev_yaw = yaw

            if self.state == 'WAITING':
                self.started_at = now
                self.state = 'TURNING'

            return

        delta_yaw = (yaw - self.prev_yaw + math.pi) % (2 * math.pi) - math.pi
        self.prev_yaw = yaw
        self.total_yaw += delta_yaw

    def stop_robot(self):
        self.cmd_pub.publish(Twist())

    def finish(self, reason, success=False):
        if self.state == 'STOPPING':
            return

        self.state = 'STOPPING'
        self.success = success
        self.stop_time = time.monotonic()
        self.stop_robot()

        self.get_logger().info(reason)

    def control_loop(self):
        now = time.monotonic()

        if self.state == 'STOPPING':
            self.stop_robot()

            if now - self.stop_time >= 2.0:
                final_angle = math.degrees(self.total_yaw)

                self.get_logger().info(f'Final odometry angle: {final_angle:+.2f} deg')
                self.done = True
            return

        if self.state == 'WAITING':
            self.stop_robot()
            if now - self.created_at > 10.0:
                self.finish('Odometry unavailable')
            return

        if now - self.last_odom_time > 0.5:
            self.finish('Odometry timeout')
            return

        if now - self.started_at > self.timeout:
            self.finish('Movement timeout')
            return

        progress = self.direction * self.total_yaw

        remaining = abs(self.target_angle) - progress

        if remaining <= self.stop_margin:
            self.finish(f'Stopping at {math.degrees(self.total_yaw):+.2f} deg', success=True)
            return

        msg = Twist()
        msg.linear.x = 0.0
        msg.angular.z = self.angular_command
        self.cmd_pub.publish(msg)
        if now - self.last_log_time >= 0.5:
            self.last_log_time = now


def main():
    parser = argparse.ArgumentParser(
        description='Turn robot by a specified angle'
    )

    parser.add_argument('angle', type=float, help='Angle in degrees (positive=CCW, negative=CW)')

    parser.add_argument('--margin', type=float, default=8.0, help='Early stopping margin in degrees')

    args = parser.parse_args()

    if (not math.isfinite(args.angle) or abs(args.angle) < 1.0 or abs(args.angle) > 180.0):
        parser.error('Angle must be between -180 and 180 degrees, excluding angles smaller than 1 degree')

    if (not math.isfinite(args.margin) or args.margin < 0 or args.margin >= abs(args.angle)):
        parser.error('Invalid stopping margin')
    rclpy.init()
    node = Turn(args.angle, args.margin)

    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.1)

    except KeyboardInterrupt:
        node.get_logger().warning('Interrupted')

    finally:
        for _ in range(10):
            node.stop_robot()
            time.sleep(0.05)

        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()

