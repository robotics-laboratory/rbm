#!/usr/bin/env python3

import math
import time

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.clock import Clock, ClockType

from sensor_msgs.msg import Joy
from geometry_msgs.msg import Twist


class GamepadTeleop(Node):

    def __init__(self):
        super().__init__('gamepad_teleop')

        self.declare_parameter('max_linear', Parameter.Type.DOUBLE)
        self.declare_parameter('max_angular', Parameter.Type.DOUBLE)

        self.declare_parameter('linear_axis', Parameter.Type.INTEGER)
        self.declare_parameter('angular_axis', Parameter.Type.INTEGER)

        self.declare_parameter('linear_sign', Parameter.Type.DOUBLE)
        self.declare_parameter('angular_sign', Parameter.Type.DOUBLE)

        self.declare_parameter('joy_timeout', Parameter.Type.DOUBLE)

        self.max_linear = self.get_parameter('max_linear').value
        self.max_angular = self.get_parameter('max_angular').value
        
        self.linear_axis = self.get_parameter('linear_axis').value
        self.angular_axis = self.get_parameter('angular_axis').value
        
        self.linear_sign = self.get_parameter('linear_sign').value
        self.angular_sign = self.get_parameter('angular_sign').value
        
        self.joy_timeout = self.get_parameter('joy_timeout').value

        self.pub = self.create_publisher(Twist, '/cmd_vel_joy', 1)
        self.sub = self.create_subscription(Joy, '/joy', self.joy_callback, 1)

        self.last_joy = None
        self.active = False
        self.armed = False

        self.timer = self.create_timer(
            0.05,
            self.watchdog,
            clock=Clock(clock_type=ClockType.STEADY_TIME)
        )

        self.get_logger().info('Gamepad teleop started')

    @staticmethod
    def axis(msg, index):
        if not 0 <= index < len(msg.axes):
            raise ValueError('Invalid axis index')

        value = msg.axes[index]

        if not math.isfinite(value):
            raise ValueError('Invalid axis value')

        return max(-1.0, min(1.0, value))

    def stop(self):
        if self.active:
            self.pub.publish(Twist())
            self.active = False

    def watchdog(self):
        if self.last_joy is None:
            return

        if time.monotonic() - self.last_joy > self.joy_timeout:
            self.stop()
            self.armed = False
            self.last_joy = None

            self.get_logger().warn('Gamepad timeout')

    def joy_callback(self, msg):
        self.watchdog()
        self.last_joy = time.monotonic()

        try:
            stick_v = (
                self.axis(msg, self.linear_axis)
                * self.linear_sign
            )

            stick_w = (
                self.axis(msg, self.angular_axis)
                * self.angular_sign
            )

        except ValueError:
            self.stop()
            self.armed = False
            return

        neutral = (
            abs(stick_v) < 1e-6
            and abs(stick_w) < 1e-6
        )

        if not self.armed:
            if neutral:
                self.armed = True
            return

        if neutral:
            self.stop()
            return

        cmd = Twist()

        cmd.linear.x = stick_v * self.max_linear
        cmd.angular.z = stick_w * self.max_angular

        self.pub.publish(cmd)
        self.active = True


def main(args=None):
    rclpy.init(args=args)

    node = GamepadTeleop()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        if rclpy.ok():
            node.stop()

        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
