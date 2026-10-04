from nicegui import APIRouter, ui, app
from webui.tests import BaseTest
from starlette.requests import Request
import socket
import asyncio


router = APIRouter()

INTRO = r"""
  ___ ___ __  __   _____   _____ _____ ___ __  __   ___ ___ _____ _   _ ___ 
 | _ \ _ )  \/  | / __\ \ / / __|_   _| __|  \/  | / __| __|_   _| | | | _ \
 |   / _ \ |\/| | \__ \\ V /\__ \ | | | _|| |\/| | \__ \ _|  | | | |_| |  _/
 |_|_\___/_|  |_| |___/ |_| |___/ |_| |___|_|  |_| |___/___| |_|  \___/|_|  
                                                                            
"""

SETTINGS = [
    "UpdateWifiSettings",
    "UpdateConfig",
    "RestartDocker",
    "WriteFirmware",
    "SystemUpdate",
]
TESTS = [
    "USBTest",
    "CameraTest",
    "SpeakerMicTest",
    "HWStatusTest",
    "MotorsTest",
    "MoveTest",
    "DockerROSTest",
]


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


async def action_block(terminal: ui.xterm, class_name: str):
    test = BaseTest.subclasses[class_name]()

    with ui.row().classes("items-center gap-4 p-2 border rounded w-full").style("border-color: rgba(255, 255, 255, 0.25)"):
        ui.label(test.name).classes("font-bold col")
        StatusLabel().bind_text_from(test, "status")
        btn = ui.button("RUN", on_click=test.run).props("outline")
        output = ui.row().classes("w-full")
        output.set_visibility(False)

        test.log_func = lambda line: terminal.write(line + "\r\n")
        test.output = output
        test.run_btn = btn
        asyncio.create_task(test.mounted())
    
    return test


async def settings_section(terminal: ui.xterm):
    for class_name in SETTINGS:
        await action_block(terminal, class_name)


async def tests_section(terminal: ui.xterm):
    test_instances = []

    with ui.row().classes("w-full items-center"):
        async def run_all():
            run_all_btn.disable()
            for test in test_instances:
                if test.autorun: await test.run()
            run_all_btn.enable()
        run_all_btn = ui.button("RUN ALL", on_click=run_all, icon="play_arrow")

    ui.separator()

    for class_name in TESTS:
        test = await action_block(terminal, class_name)
        test_instances.append(test)


@router.page("/system", favicon="⚙️")
async def main_page():
    hostname = app.state.hostctl.hostname
    ui.dark_mode(value=True)
    ui.query(".nicegui-content").classes("p-0")
    ui.page_title(f"{hostname.upper()} | SYSTEM SETUP")

    with ui.splitter(value=25).classes("w-full h-screen") as splitter:
        with splitter.after:
            with ui.column().classes("w-full h-full p-4"):
                terminal = ui.xterm().classes("size-full")
                ui.element("q-resize-observer").on("resize", terminal.fit)
                intro = INTRO + "—" * (len(INTRO.splitlines()[-1]) + 1) + "\n"
                intro = intro.replace("\n", "\r\n")
                terminal.write(intro)

        with splitter.before:
            with ui.column().classes("w-full p-0 py-4 gap-2 overflow-auto"):
                ui.label(f"{hostname.upper()} SYSTEM SETUP").classes("text-h5 w-full text-center")

                with ui.tabs().classes("w-full").props("dense").style("background: rgba(255, 255, 255, 0.1)") as tabs:
                    settings = ui.tab("SETTINGS").classes("flex-1")
                    tests = ui.tab("TESTS").classes("flex-1")
                with ui.tab_panels(tabs, value=settings).classes("w-full"):
                    with ui.tab_panel(settings):
                        await settings_section(terminal)
                    with ui.tab_panel(tests):
                        await tests_section(terminal)


LINKS = [
    ("lichtblick", "category", "https://viz.robomarvel.ru/?ds=foxglove-websocket&ds.url=ws%3A%2F%2F{ip}%3A8765&layoutId=id1"),
    ("vscode web", "code", "http://{ip}:8000/?folder=/src"),
    ("jupyter lab", "code", "http://{ip}:8080"),
    ("docker terminal", "terminal", "http://{ip}:8200"),
    ("host terminal", "terminal", "http://{ip}:8100"),
    ("camera stream", "videocam", "http://{ip}:8889/cam"),
    ("system setup", "settings", "/system"),
]

@router.page("/", favicon="🚀")
async def welcome_page(request: Request):
    hostname = app.state.hostctl.hostname
    ui.dark_mode(value=True)
    ui.query(".nicegui-content").classes("p-0")
    ui.page_title(f"{hostname.upper()} | HOME")
    ip = request.url.hostname

    with ui.column().classes("items-center justify-center w-full h-screen gap-2"):
        ui.label(f"{hostname.upper()}").classes("text-h2 font-mono")

        with ui.card().classes("w-100 p-6 shadow-lg"):
            for label, icon, url in LINKS:
                with ui.link(
                    target=url.format(ip=ip),
                    new_tab=True
                ).classes("bg-red-900 text-white no-underline rounded w-full p-2"):
                    with ui.row().classes("items-center justify-center"):
                        ui.icon(icon, size="md")
                        ui.label(label.upper())
