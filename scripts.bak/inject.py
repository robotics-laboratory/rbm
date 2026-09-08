import rclpy
from rclpy.node import Node
from rosidl_runtime_py import message_to_ordereddict, set_message_fields
from rosidl_runtime_py.utilities import get_message
from collections import defaultdict
import time
import json
import sys


DURATION = 10.0
PUB_DATA = [
    {
        "topic": "/cmd_vel",
        "type": "geometry_msgs.msg.Twist",
        "data": [
            [0.0, {"linear": {"x": 0.2}}],
            [2.0, {"linear": {"x": 0.0}}],
            [2.5, {"angular": {"z": 1.5}}],
            [4.5, {"angular": {"z": 0.0}}],
            [5.0, {"linear": {"x": 0.2}}],
            [7.0, {"linear": {"x": 0.0}}],
            [7.5, {"angular": {"z": -1.5}}],
            [9.5, {"angular": {"z": 0.0}}],
        ]
    }
]
SUB_TOPICS = [
    ["/hardware/status", "std_msgs.msg.Float32MultiArray"],
]

#DURATION = {duration}
#PUB_DATA = {pub_data}
#SUB_TOPICS = {sub_topics}
SUB_DATA = defaultdict(list)

rclpy.init()
node = Node("test_inject_node")
start = time.perf_counter()

def make_sub_callback(topic):
    def callback(msg):
        ts = time.perf_counter() - start
        data = message_to_ordereddict(msg)
        SUB_DATA[topic].append((ts, data))
    return callback

for topic, type in SUB_TOPICS:
    type = get_message(type.replace(".", "/"))
    cb = make_sub_callback(topic)
    node.create_subscription(type, topic, cb, 1)

pubs = {}
for pub_data in PUB_DATA:
    type = get_message(pub_data["type"].replace(".", "/"))
    pub = node.create_publisher(type, pub_data["topic"], 1)
    pubs[pub_data["topic"]] = (type, pub)

next_pub_index = [0] * len(PUB_DATA)
pub_last_ts = [None] * len(PUB_DATA)
pub_last_msg = [None] * len(PUB_DATA)
start = time.perf_counter()
while True:
    rclpy.spin_once(node, timeout_sec=0.1)
    ts = time.perf_counter() - start
    #print(f"ts: {ts:.3f}")
    if ts > DURATION: break
    for i, pub_data in enumerate(PUB_DATA):
        next_index = next_pub_index[i]
        if next_index >= len(pub_data["data"]):
            pub_ts, data = float("+inf"), None
        else:
            pub_ts, data = pub_data["data"][next_index]
        #print(f"pub ts: {pub_ts:.3f}, ts: {ts:.3f}")
        if ts >= pub_ts:
            type, pub = pubs[pub_data["topic"]]
            msg = type()
            set_message_fields(msg, data)
            pub.publish(msg)
            #print(f"pub {pub_data['topic']}, index {next_pub_index[i]}, ts {pub_ts:.3f}: {msg}")
            next_pub_index[i] += 1
            pub_last_ts[i] = ts
            pub_last_msg[i] = msg
        elif pub_last_ts[i] is not None and (ts - pub_last_ts[i]) >= 0.1:
            msg = pub_last_msg[i]
            pub.publish(msg)
            #print(f"pub {pub_data['topic']}, index {next_pub_index[i]}, ts {pub_ts:.3f}: {msg}")
            pub_last_ts[i] = ts

print(json.dumps(SUB_DATA))
rclpy.shutdown()
