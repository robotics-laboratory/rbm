#!/usr/bin/env python3

import asyncio
import time
import abc
import json
from pathlib import Path
from typing import Callable, ClassVar
from nicegui import ui
from starlette.requests import Request
from dataclasses import dataclass
import traceback
from serial import Serial
import socket
import struct
import math
import yaml
import re


class BaseTest(abc.ABC):
    name: ClassVar[str] = ...
    tests: ClassVar[dict] = {}

    def __init__(self):
        self.status = "NOT RUN"
        self.log_func: Callable[[str], None] = None
        self.output: ui.column = None
        self.run_btn: ui.button = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        BaseTest.tests[cls] = True

    def log(self, msg: str, color: str = "default"):
        COLORS = {
            "red": "\x1b[91m",
            "green": "\x1b[92m",
            "yellow": "\x1b[93m",
            "blue": "\x1b[94m",
            "reset": "\x1b[0m",
        }
        if color != "default":
            reset = COLORS["reset"]
            code = COLORS.get(color, reset)
            msg = f"{code}{msg}{reset}"
        self.log_func(msg)

    async def shell(self, cmd: str, check: bool = True, timeout: float = 10):
        self.log(f">>> $ {cmd}")
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        logs = ""
        async def read_stream(stream):
            nonlocal logs
            while True:
                line = await stream.readline()
                if not line: break
                line = line.decode().rstrip()
                logs += line + "\n"
                self.log(line)

        try:
            gather = asyncio.gather(read_stream(proc.stdout), read_stream(proc.stderr))
            await asyncio.wait_for(gather, timeout=timeout)
            await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            assert False, f"Command timed out after {timeout}s"

        assert not check or proc.returncode == 0, f"Bad return code: {proc.returncode}"
        return logs

    async def docker_shell(self, cmd: str, check: bool = True, timeout: float = 10):
        cmd = f"docker exec ros bash -c 'export PS1=\"dummy\" && source ~/.bashrc && {cmd}'"
        return await self.shell(cmd=cmd, check=check, timeout=timeout)

    async def docker_inject(self, config: dict, timeout: float = None):
        duration = float(config["duration"])
        timeout = duration + 8 if timeout is None else timeout

        data = {
            "duration": duration,
            "pub_data": config.get("pub_data", []),
            "sub_topics": config.get("sub_topics", []),
        }
        
        cmd = 'export PS1="dummy" && source /root/.bashrc && python3 /src/scripts/inject.py'
        cmd = f"docker exec -i ros bash -c 'export PS1=\"dummy\" && source ~/.bashrc && {cmd}'"
        self.log(f">>> [INJECT] $ {cmd}")
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        started = time.perf_counter()
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate((json.dumps(data) + "\n").encode()),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            self.log(
                f"<<< inject TIMEOUT after {time.perf_counter() - started:.2f}s "
                f"(limit {timeout:.1f}s)",
                color="red",
            )
            raise AssertionError(f"Inject timed out after {timeout}s")

        stderr = stderr.decode().strip()
        if stderr:
            self.log(stderr)

        assert proc.returncode == 0, f"Inject failed with return code {proc.returncode}"
        output = stdout.decode().strip()
        try:
            return json.loads(output)
        except json.JSONDecodeError as err:
            raise AssertionError(f"Bad inject JSON output: {err}: {output}") from err

    async def run(self):
        self.log(f"\r\n===== START: {self.name} =====\r\n", color="yellow")
        try:
            self.output.clear()
            self.output.set_visibility(False)
            self.run_btn.disable()
            self.status = "RUNNING"
            res = await self.test()
            self.status = "PASS" if res else "FAIL"
        except AssertionError as err:
            self.log(f"----- ASSERTION FAILED -----\n", color="red")
            self.log(str(err).replace("\n", "\n\r") + "\n")
            self.status = "FAIL"
        except Exception as err:
            self.log(f"----- UNHANDLED TEST ERROR -----\n", color="red")
            self.log(traceback.format_exc().replace("\n", "\n\r"))
            self.status = "FAIL"
        color = "green" if self.status == "PASS" else "red"
        self.log(f"\r\n===== [{self.status}] {self.name} =====", color=color)
        self.run_btn.enable()

    @abc.abstractmethod
    async def test(self):
        pass


class CameraTest(BaseTest):
    name = "CAMERA"

    async def test(self):
        output_file = Path("/tmp/camera-test.png")
        output_file.unlink(missing_ok=True)
        Path("/tmp/camera-test.jpg").unlink(missing_ok=True)

        cmd = (
            "ffmpeg -loglevel fatal "
            "-f v4l2 -input_format mjpeg -video_size 1920x1080 -i /dev/video0 "
            f"-ss 00:00:02 -frames:v 1 -y {output_file}"
        )

        self.log("Waiting 2s for camera warm-up, then capturing one frame...", color="yellow")
        await self.shell(cmd, timeout=10)
        assert output_file.exists(), f"Output file missing: {output_file}"

        assert output_file.stat().st_size > 0, f"Output file empty: {output_file}"
        self.log("[OK] Camera image captured", color="green")

        with self.output.classes("h-60 items-center"):
            self.output.set_visibility(True)
            img = ui.image(output_file).classes("max-h-full").props("fit=contain")
            img.force_reload()

        return True


class SpeakerMicTest(BaseTest):
    name = "SPEAKER + MIC"

    async def test(self):
        for old_file in Path("/tmp").glob("mic-test*.wav"):
            old_file.unlink(missing_ok=True)

        output_file = Path(f"/tmp/mic-test-{time.time_ns()}.wav")
        record_proc = self.shell(
            "arecord -c2 -r 48000 -f S32_LE -t wav "
            f"-V stereo -d 2 -v {output_file}"
        )
        speaker_proc = self.shell("speaker-test -t wav -c2 -s2")
        await asyncio.gather(record_proc, speaker_proc)
        assert output_file.exists(), f"Output file missing: {output_file}"
        assert output_file.stat().st_size != 0, f"Output file empty: {output_file}"
        self.log("NOTICE: Check recorded audio manually", color="yellow")

        with self.output:
            self.output.set_visibility(True)
            ui.audio(output_file).classes("w-full")
        return True


class DockerROSTest(BaseTest):
    name = "DOCKER + ROS"

    EXPECTED_NODES = [
        "/hardware_node",
        "/ld19_node",
        "/icp_odom",
        "/robot_state_publisher",
        "/foxglove_bridge",
        "/slam_toolbox",
        "/nav2_container",
        "/bt_navigator",
        "/behavior_server",
        "/controller_server",
        "/planner_server",
        "/global_costmap/global_costmap",
        "/local_costmap/local_costmap",
        "/lifecycle_manager_navigation",
    ]

    TOLERANCE = 0.9

    TRANSFORMS = [
        ("lidar", "base_link", -1),
        ("base_link", "odom", 10.0),
        ("odom", "map", 1.0),
    ]

    TOPICS = [
        ("/scan", 10.0, 3),
        ("/hardware/imu", 50.0, 3),
        ("/hardware/odom", 50.0, 3),
        ("/icp/odom", 10.0, 3),
        ("/local_costmap/costmap", 1.5, 10),
        ("/global_costmap/costmap", 0.5, 10),
        ("/map", 0.2, 20),
    ]

    async def _docker_exec(self, cmd: str, check: bool = True, timeout: float = 10.0) -> str:
        cmd = f"docker exec ros bash -c 'export PS1=\"dummy\" && source ~/.bashrc && {cmd}'"
        return await self.shell(cmd, check=check, timeout=timeout)

    async def _start_container(self):
        Path("/home/robomarvel/.autostart").touch()

        state = await self.shell(
            "docker inspect --format '{{.State.Running}}' ros",
            check=False,
            timeout=5,
        )
        if state.strip() == "true":
            self.log("ROS container is already running", color="green")
            return

        await self.shell("docker start ros", timeout=10)
        self.log("Waiting 15s for ROS to initialize...", color="yellow")
        await asyncio.sleep(15)

    async def _check_nodes(self):
        self.log("\n--- Checking ROS nodes ---", color="yellow")
        output = await self._docker_exec("ros2 node list", timeout=10)
        nodes = set(line.strip() for line in output.splitlines() if line.strip())
        missing = set(self.EXPECTED_NODES) - nodes
        assert not missing, f"Missing nodes: {sorted(missing)}"
        self.log(f"All {len(self.EXPECTED_NODES)} expected nodes found", color="green")

    async def _check_transforms(self):
        self.log("\n--- Checking transforms via view_frames ---", color="yellow")
        cmd = "ros2 run tf2_tools view_frames -o /tmp/frames --wait-time 5"
        output = await self._docker_exec(cmd, timeout=20)

        match = re.search(r'Result:tf2_msgs\.srv\.FrameGraph_Response\(frame_yaml="(.*)"\)', output, re.DOTALL)
        assert match, "Could not extract frame_yaml from view_frames output"
        data = match.group(1)
        data = data.replace('\\"', '"')
        data = data.replace("\\n", "\n")
        self.log("\r\nVIEW FRAMES RESULT:", color="yellow")
        msg = data.replace("\n", "\r\n")
        self.log(msg)
        frames = yaml.safe_load(data)

        for child, parent, min_rate in self.TRANSFORMS:
            self.log(f"Checking transform: {child} -> {parent}")
            assert child in frames, f"Child frame '{child}' not found"
            info = frames[child]
            actual_parent = info.get("parent")
            assert actual_parent == parent, f"Transform {child} has parent '{actual_parent}', expected '{parent}'"
            if min_rate > 0:
                rate = info.get("rate")
                assert rate is not None, f"Rate not available for dynamic transform {child}"
                required_rate = min_rate * self.TOLERANCE
                assert rate >= required_rate, (
                    f"Transform {child} rate too low: {rate:.3f} Hz < "
                    f"{required_rate:.1f} Hz (nominal: {min_rate:.1f} Hz)"
                )
                self.log(
                    f"--> OK: rate = {rate:.3f} Hz "
                    f"(minimum: {required_rate:.1f} Hz, nominal: {min_rate:.1f} Hz)",
                    color="green",
                )
            else:
                self.log(f"--> OK: static transform", color="green")

    async def _check_topic(self, topic: str, min_rate: float, timeout: float):
        self.log(f"\n--- Checking topic: {topic} ---", color="yellow")
        command_timeout = max(timeout, 8)
        cmd = f"timeout {command_timeout} ros2 topic hz {topic}"
        output = await self._docker_exec(
            cmd,
            timeout=command_timeout + 5,
            check=False,
        )
        avg_rate = None
        for line in output.splitlines():
            if "average rate" in line:
                match = re.search(r"average rate:\s+([0-9.]+)", line)
                if match:
                    avg_rate = float(match.group(1))
                    break
        if avg_rate is None or avg_rate == 0.0:
            if "no new messages" in output or not output.strip():
                assert False, f"No messages received"
            assert False, f"Could not determine message rate"
        required_rate = min_rate * self.TOLERANCE
        assert avg_rate >= required_rate, (
            f"Rate too low: {avg_rate:.1f} Hz < {required_rate:.1f} Hz "
            f"(nominal: {min_rate:.1f} Hz)"
        )
        self.log(
            f"Topic rate OK: {avg_rate:.3f} Hz "
            f"(minimum: {required_rate:.1f} Hz, nominal: {min_rate:.1f} Hz)",
            color="green",
        )

    async def _run_check(self, name, check, failures):
        try:
            await check()
        except Exception as err:
            message = str(err) or type(err).__name__
            failures.append(f"{name}: {message}")
            self.log(f"[FAIL] {name}: {message}; continuing...", color="red")

    async def test(self):
        failures = []

        await self._run_check("container", self._start_container, failures)
        await self._run_check("nodes", self._check_nodes, failures)
        await self._run_check("transforms", self._check_transforms, failures)

        for topic, min_rate, timeout in self.TOPICS:
            await self._run_check(
                topic,
                lambda topic=topic, min_rate=min_rate, timeout=timeout:
                    self._check_topic(topic, min_rate, timeout),
                failures,
            )

        assert not failures, "Failed checks:\n- " + "\n- ".join(failures)
        return True


class USBTest(BaseTest):
    name = "USB"

    EXPECTED_USB = {
         "ESP32": "1a86:7523",
         "Camera": "1bcf:0b09",
         "Lidar": "10c4:ea60",
         "Audio": "0c76:1203"
    }

    async def test(self):
        output = await self.shell("lsusb", timeout=5)

        miss = []

        for name, usb_id in self.EXPECTED_USB.items():
            if usb_id.lower() in output.lower():
                self.log(f"[OK] {name}: {usb_id}", color="green")
            else:
                self.log(f"[MISSING] {name}: {usb_id}", color="red")
                miss.append(name)

        assert not miss, f"Missing USB devices: {miss}"

        return True


class HWStatusTest(BaseTest):
    name = "HW STATUS"

    SENSORS = {
        "INA": 1,
        "ToF": 2,
        "IMU": 3,
        "Screen": 0,
    }

    async def test(self):
        output = await self.docker_inject({
            "duration": 1.0,
            "pub_data": [],
            "sub_topics": [[
                "/hardware/status",
                "std_msgs.msg.Float32MultiArray",
            ]],
        })
        samples = output.get("/hardware/status", [])
        assert samples, "No /hardware/status feedback received"

        values = samples[-1][1].get("data", [])
        assert len(values) > 19, (
            f"Bad /hardware/status data length: {len(values)}, expected at least 20"
        )

        flags = int(values[19])
        fail = []

        for name, bit in self.SENSORS.items():
            ok = bool(flags & (1 << bit))
            if (ok):
                self.log(f"[OK] {name}", color="green")
            else:
                self.log(f"[FAIL] {name}", color="red")
                fail.append(name)

        assert not fail, f"HW sensors failed: {', '.join(fail)}"
        return True


class MotorsTest(BaseTest):
    name = "MOTORS"

    WHEELS = [
        # name, index, status index, sign
        ("FRONT LEFT", 1, 1),
        ("FRONT RIGHT", 13, -1),
        ("REAR LEFT", 5, 1),
        ("REAR RIGHT", 9, -1),
    ]

    SPEED = 10.0
    DELAY = 2.0
    CHECK_MARGIN = 0.3
    RMS_THRESHOLD = 0.5

    async def stop(self):
        config = {
            "duration": 1.0,
            "pub_data": [{
                "topic": "/hardware/wheel_targets",
                "type": "std_msgs.msg.Float32MultiArray",
                "data": [[0.0, {"data": [0.0, 0.0, 0.0, 0.0]}]],
            }],
            "sub_topics": [],
        }
        await self.docker_inject(config)

    async def test(self):
        pub_data = []
        for i in range(4):
            speeds = [0.0] * 4
            speeds[i] = self.SPEED * self.WHEELS[i][2]
            pub_data.append([i * self.DELAY, {"data": speeds}])
        pub_data.append([4 * self.DELAY, {"data": [0.0] * 4}])
        
        config = {
            "duration": 4 * self.DELAY + 0.5,
            "pub_data": [{
                "topic": "/hardware/wheel_targets",
                "type": "std_msgs.msg.Float32MultiArray",
                "data": pub_data,
            }],
            "sub_topics": [[
                "/hardware/status",
                "std_msgs.msg.Float32MultiArray",
            ]],
        }
        
        output = await self.docker_inject(config)
        data = output.get("/hardware/status", [])
        assert data, f"No /hardware/status data received"

        ok = True
        for i in range(4):
            name, index, sign = self.WHEELS[i]
            start_ts = i * self.DELAY + self.CHECK_MARGIN
            end_ts = (i + 1) * self.DELAY - self.CHECK_MARGIN
            start = next(iter(i for i, x in enumerate(data) if x[0] > start_ts), 0)
            end = next(iter(i for i, x in enumerate(data) if x[0] > end_ts), 0)
            speeds = [x[1]["data"][index] for x in data[start:end]]
            msg = [f"{x:.1f}" for x in speeds]
            self.log(f"[{name}] Speeds: {', '.join(msg)}")
            if not speeds:
                self.log(f"[{name}] No speed data", color="red")
                ok = False
                continue
            target = self.SPEED * sign
            rms = math.sqrt(sum((x - target) ** 2 for x in speeds) / len(speeds))
            if rms > self.RMS_THRESHOLD:
                self.log(f"[{name}] Speed RMS fail: {rms:.2f} > {self.RMS_THRESHOLD}", color="red")
                ok = False
                continue
            self.log(f"[{name}] RMS OK: {rms:.2f} < {self.RMS_THRESHOLD}", color="green")

        return ok


class MoveTest(BaseTest):
    name = "MOVE TEST"

    MIN_FEEDBACK_SPEED = 0.5

    SPEED_INDICES = {
        "front_left": 1,
        "front_right": 13,
        "rear_left": 5,
        "rear_right": 9,
    }

    @staticmethod
    def cmd(linear=0.0, angular=0.0):
        return {
            "linear": {"x": linear},
            "angular": {"z": angular},
        }

    async def stop(self):
        config = {
            "duration": 1.0,
            "pub_data": [{
                "topic": "/cmd_vel",
                "type": "geometry_msgs.msg.Twist",
                "data": [[0.0, self.cmd()]],
            }],
            "sub_topics": [[
                "/hardware/status",
                "std_msgs.msg.Float32MultiArray",
            ]],
        }
        try:
            output = await self.docker_inject(config)
            samples = output.get("/hardware/status", [])
            if samples:
                data = samples[-1][1].get("data", [])
                speeds = {
                    name: data[index]
                    for name, index in self.SPEED_INDICES.items()
                    if len(data) > index
                }
                if speeds:
                    stopped = all(abs(speed) < 1.0 for speed in speeds.values())
                    if stopped:
                        self.log("[OK] Robot stopped", color="green")
                    else:
                        self.log("Robot may still be moving", color="yellow")
        except Exception as err:
            self.log(f"Inject stop failed: {err}; using fallback stop", color="red")
            await self.docker_shell(
                "timeout 3 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "
                '"{linear: {x: 0.0}, angular: {z: 0.0}}"',
                check=False,
                timeout=5,
            )

    async def test(self):
        config = {
            "duration": 10.0,
            "pub_data": [{
                "topic": "/cmd_vel",
                "type": "geometry_msgs.msg.Twist",
                "data": [
                    [0.0, self.cmd(linear=0.2)],
                    [2.0, self.cmd()],
                    [2.5, self.cmd(angular=1.5)],
                    [4.5, self.cmd()],
                    [5.0, self.cmd(linear=0.2)],
                    [7.0, self.cmd()],
                    [7.5, self.cmd(angular=-1.5)],
                    [9.5, self.cmd()],
                ],
            }],
            "sub_topics": [[
                "/hardware/status",
                "std_msgs.msg.Float32MultiArray",
            ]],
        }

        try:
            self.log(
                "Forward -> Left -> Forward -> Right",
                color="yellow",
            )
            output = await self.docker_inject(config)
            samples = output.get("/hardware/status", [])
            assert samples, "No hardware status received during move test"
            self.log(
                f"[OK] Feedback received: {len(samples)} samples",
                color="green",
            )

            forward_signs = {
                "front_left": 1,
                "front_right": -1,
                "rear_left": 1,
                "rear_right": -1,
            }
            phases = [
                ("Forward 1", 0.8, 1.8, forward_signs),
                ("Left", 3.0, 4.3, dict.fromkeys(self.SPEED_INDICES, -1)),
                ("Forward 2", 5.8, 6.8, forward_signs),
                ("Right", 8.0, 9.3, dict.fromkeys(self.SPEED_INDICES, 1)),
            ]
            for phase, start, end, expected_signs in phases:
                phase_samples = [
                    msg.get("data", [])
                    for ts, msg in samples
                    if start <= ts < end
                    and len(msg.get("data", [])) > max(self.SPEED_INDICES.values())
                ]
                assert phase_samples, f"No feedback received during {phase}"

                average_speeds = {
                    name: sum(
                        data[index]
                        for data in phase_samples
                    ) / len(phase_samples)
                    for name, index in self.SPEED_INDICES.items()
                }
                bad_wheels = [
                    name
                    for name, sign in expected_signs.items()
                    if average_speeds[name] * sign < self.MIN_FEEDBACK_SPEED
                ]
                assert not bad_wheels, (
                    f"{phase} feedback mismatch: {', '.join(bad_wheels)}"
                )
            self.log("[OK] Wheel encoder feedback matches commands", color="green")
        finally:
            self.log("Stopping robot", color="yellow")
            await self.stop()
        return True

# ----------------------------------------------------------------


class StatusLabel(ui.label):
    COLORS = {
        "running": "text-warning",
        "pass": "text-positive",
        "fail": "text-negative",
        "not run": "text-grey",
    }

    def _handle_text_change(self, text: str) -> None:
        super()._handle_text_change(text)
        self.classes(remove=(" ".join(self.COLORS.values())))
        res = self.COLORS.get(text.lower())
        if res is not None: self.classes(add=res)


INTRO = """
  ___ ___ __  __   _____   _____ _____ ___ __  __   _____ ___ ___ _____ ___ 
 │ _ ╲ _ )  ╲╱  │ ╱ __╲ ╲ ╱ ╱ __│_   _│ __│  ╲╱  │ │_   _│ __╱ __│_   _╱ __│
 │   ╱ _ ╲ │╲╱│ │ ╲__ ╲╲ V ╱╲__ ╲ │ │ │ _││ │╲╱│ │   │ │ │ _│╲__ ╲ │ │ ╲__ ╲
 │_│_╲___╱_│  │_│ │___╱ │_│ │___╱ │_│ │___│_│  │_│   │_│ │___│___╱ │_│ │___╱
                                                                            
"""

HOSTNAME = socket.gethostname()
TESTS = [
    USBTest,
    CameraTest,
    SpeakerMicTest,
    HWStatusTest,
    MotorsTest,
    MoveTest,
    DockerROSTest,
]


@ui.page("/tests", favicon="✅")
def main_page():
    ui.dark_mode(value=True)
    ui.query(".nicegui-content").classes("p-0")
    ui.page_title(f"{HOSTNAME.upper()} | TESTS")
    test_instances = []

    with ui.splitter(value=25).classes("w-full h-screen") as splitter:
        with splitter.before:
            with ui.column().classes("w-full p-4 overflow-auto"):
                with ui.row().classes("w-full items-center"):
                    ui.label("RBM SYSTEM TESTS").classes("text-h5 col")

                    async def run_all():
                        run_all_btn.disable()
                        for test in test_instances:
                            await test.run()
                        run_all_btn.enable()
                    run_all_btn = ui.button("RUN ALL", on_click=run_all, icon="play_arrow")

                ui.separator()

                for test_class in TESTS:
                    test = test_class()
                    test_instances.append(test)

                    with ui.row().classes("items-center gap-4 p-2 border rounded w-full").style("border-color: rgba(255, 255, 255, 0.25)"):
                        ui.label(test.name).classes("font-bold col")
                        StatusLabel().bind_text_from(test, "status")
                        btn = ui.button("RUN", on_click=test.run).props("outline")
                        output = ui.row().classes("w-full")
                        output.set_visibility(False)

                        test.log_func = lambda line: terminal.write(line + "\r\n")
                        test.output = output
                        test.run_btn = btn

        with splitter.after:
            with ui.column().classes("w-full h-full p-4"):
                terminal = ui.xterm().classes("size-full")
                ui.element("q-resize-observer").on("resize", terminal.fit)
                intro = INTRO + "—" * (len(INTRO.splitlines()[-1]) + 1) + "\n"
                intro = intro.replace("\n", "\r\n")
                terminal.write(intro)


# ----------------------------------------------------------------

LINKS = [
    ("Foxglove", "category", "https://foxglove-ssl.robotics-lab.ru/?ds=foxglove-websocket&ds.url=ws%3A%2F%2F{ip}%3A8765"),
    ("Jupyter Lab", "code", "http://{ip}:8080"),
    ("Terminal (host)", "terminal", "http://{ip}:8100"),
    ("Terminal (docker)", "terminal", "http://{ip}:8200"),
    ("System Tests", "checklist", "/tests"),
    ("Camera Stream", "videocam", "http://{ip}:8889/cam"),
]

@ui.page("/", favicon="🚀")
async def welcome_page(request: Request):
    ui.dark_mode(value=True)
    ui.query(".nicegui-content").classes("p-0")
    ui.page_title(f"{HOSTNAME.upper()} | HOME")
    ip = request.url.hostname

    with ui.column().classes("items-center justify-center w-full h-screen gap-2"):
        ui.label(f"{HOSTNAME.upper()}").classes("text-h2 font-mono")
        ui.label(f"IP: {ip}").classes("text-h6 font-mono mb-5")

        with ui.card().classes("w-100 p-6 shadow-lg"):
            for label, icon, url in LINKS:
                with ui.link(
                    target=url.format(ip=ip),
                    new_tab=True
                ).classes("bg-red-900 text-white no-underline rounded w-full p-2"):
                    with ui.row().classes("items-center justify-center"):
                        ui.icon(icon, size="md")
                        ui.label(label.upper())


ui.run(
    title="ROBOMARVEL",
    show=False,
    port=80,
    favicon="✅",
    reconnect_timeout=10,
    reload=False,
)
