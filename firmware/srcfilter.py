Import("env")
import subprocess

def skip_from_build(node):
    file_path = node.get_path()

    if "ESP32HWEncoder.cpp" in file_path:
        print(f"--> Excluding library file from build: {file_path}")
        return None

    return node


def set_quiet_mode(value):
    data = "{data: true}" if value else "{data: false}"

    command = (
        "source /opt/ros/jazzy/setup.bash && "
        "ros2 topic pub --once /hardware/quiet_mode std_msgs/msg/Bool "
        f"'{data}'"
    )

    subprocess.run(["bash", "-c", command], check=True)

def before_upload(source, target, env):
    set_quiet_mode(True)

def after_upload(source, target, env):
    set_quiet_mode(False)

env.AddPreAction("upload", before_upload)
env.AddPostAction("upload", after_upload)
env.AddBuildMiddleware(skip_from_build, "*")
