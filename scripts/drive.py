import argparse
import math
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

class Drive(Node):
    def __init__(self, targ_dist):
        super().__init__('drive_distance')
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.odom_sub = self.create_subscription(Odometry, '/hardware/odom', self.odom_callback, 10)
        self.targ_dist = targ_dist
        self.max_speed = 0.1
        self.min_speed = 0.02
        self.brake_accel = 0.03
        self.start_x = None
        self.start_y = None
        self.start_yaw = None
        self.distance = 0.0
        self.started = False
        self.finished = False
        self.done = False
        self.created_at = time.monotonic()
        self.started_at = None
        self.last_odom_time = None
        self.stop_time = None
        self.timeout = max(15.0,self.targ_dist / self.max_speed * 2.0 + 10.0)
        self.timer = self.create_timer(0.1, self.control_loop)
        self.success = False


    def odom_callback(self, msg):
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y

        q = msg.pose.pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))

        now = time.monotonic()
        self.last_odom_time = now

        if not self.started:
            self.start_x = x
            self.start_y = y
            self.start_yaw = yaw

            self.started_at = now
            self.started = True
            return
        dx = x - self.start_x
        dy = y - self.start_y

        self.distance = (dx * math.cos(self.start_yaw) + dy * math.sin(self.start_yaw))

    def stop_robot(self):
        self.cmd_pub.publish(Twist())

    def finish(self, reason, success=False):
        if self.finished:
            return

        self.finished = True
        self.success = success
        self.stop_time = time.monotonic()
        self.stop_robot()
        self.get_logger().info(reason)

    def control_loop(self):
        now = time.monotonic()
        if self.finished:
            self.stop_robot()
            if now - self.stop_time >= 1.5:
                self.get_logger().info(f'Final odometry distance: {self.distance:.4f} m')
                self.done = True

            return

        if not self.started:
            if now - self.created_at > 10.0:
                self.finish('Odometry unavailable')
            return

        if now - self.last_odom_time > 0.5:
            self.finish('Odometry timeout')
            return

        if now - self.started_at > self.timeout:
            self.finish('Movement timeout')
            return

        remaining = self.targ_dist - self.distance

        if remaining <= 0.0:
            self.finish(f'Target reached: {self.distance:.4f} m', success=True)
            return
        
        v_brake = math.sqrt(2.0 * self.brake_accel * remaining)

        target_speed = min(self.max_speed, v_brake)
        target_speed = max(self.min_speed, target_speed)

        msg = Twist()
        msg.linear.x = target_speed
        msg.angular.z = 0.0

        self.cmd_pub.publish(msg)

def main():
    parser = argparse.ArgumentParser(description='Drive a specified distance using wheel odometry')

    parser.add_argument('distance', type=float, help='Target distance in meters')
    args = parser.parse_args()

    if not math.isfinite(args.distance) or args.distance <= 0:
        parser.error('Distance must be a positive finite number')

    rclpy.init()
    node = Drive(args.distance)

    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.1)

    except KeyboardInterrupt:
        node.get_logger().warning('Interrupted')

    finally:
        for _ in range(5):
            node.stop_robot()
            time.sleep(0.05)

        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()


