import rclpy
from rclpy.node import Node
from rosidl_runtime_py import message_to_ordereddict, set_message_fields
from rosidl_runtime_py.utilities import get_message
from collections import defaultdict
import time
import json
import sys


CONFIG = json.loads(input())
DURATION = CONFIG["duration"]
PUB_DATA = CONFIG["pub_data"]
SUB_TOPICS = CONFIG["sub_topics"]
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
    if ts > DURATION: break
    for i, pub_data in enumerate(PUB_DATA):
        next_index = next_pub_index[i]
        if next_index >= len(pub_data["data"]):
            pub_ts, data = float("+inf"), None
        else:
            pub_ts, data = pub_data["data"][next_index]
        if ts >= pub_ts:
            type, pub = pubs[pub_data["topic"]]
            msg = type()
            set_message_fields(msg, data)
            pub.publish(msg)
            next_pub_index[i] += 1
            pub_last_ts[i] = ts
            pub_last_msg[i] = msg
        elif pub_last_ts[i] is not None and (ts - pub_last_ts[i]) >= 0.1:
            msg = pub_last_msg[i]
            pub.publish(msg)
            pub_last_ts[i] = ts

print(json.dumps(SUB_DATA))
rclpy.shutdown()
