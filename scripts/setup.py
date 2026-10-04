from pydantic import BaseModel
from pathlib import Path
import subprocess as sp
import argparse
import logging
import httpx
import yaml
import stat
import shutil
import sys
import os

ROOT = Path("/opt/rbm")
HOME = Path("/home/robomarvel")
REPO_DIR = HOME / "robomarvel"
SETUP_URL = "https://setup.robomarvel.ru"
REPO_URL = "https://github.com/robotics-laboratory/rbm"
SERIAL_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"

HOTSPOT_CONN_FILE = Path("/etc/NetworkManager/system-connections/hotspot.nmconnection")
HOTSPOT_CONN_TEMPLATE = """
[connection]
id=hotspot
uuid=7b2d7b6d-32e7-4a3b-855b-d0cf76a10b06
type=wifi
autoconnect=false
interface-name=wlan1

[wifi]
mode=ap
ssid={hostname}

[wifi-security]
key-mgmt=wpa-psk
psk=robomarvel

[ipv4]
address1=10.10.10.10/24
method=shared

[ipv6]
addr-gen-mode=stable-privacy
method=disabled

[proxy]
"""
SYSTEMD_UNIT_TEMPLATE = """
[Unit]
Description={description}
After=docker.service
Requires=docker.service

[Service]
Type=simple
User={user}
WorkingDirectory={workdir}
ExecStart={cmd}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
AUDIO_UDEV = (
    'SUBSYSTEM=="sound", DEVPATH=="*/sound/card*", '
    'ATTRS{idVendor}=="0c76", ATTRS{idProduct}=="1203", ATTR{id}="ws-usb-audio"'
)
ASOUND_CONFIG = """
defaults.pcm.!card "ws-usb-audio"
defaults.ctl.!card "ws-usb-audio"

pcm.!default {
    type asym
    playback.pcm "playback_route"
    capture.pcm "capture_plug"
}

pcm.playback_route {
    type route
    slave.pcm "hw:ws-usb-audio"
    slave.channels 2
    ttable.0.0 0.5
    ttable.1.0 0.5
    ttable.0.1 0.5
    ttable.1.1 0.5
}

pcm.capture_plug {
    type plug
    slave.pcm "hw:ws-usb-audio"
}

ctl.!default {
    type hw
    card "ws-usb-audio"
}
"""


class ReleaseInfo(BaseModel):
    release: str = None
    firmware: str = None
    docker: str = None
    webui: str = None


class SetupConfig(BaseModel):
    old: ReleaseInfo
    new: ReleaseInfo


class SetupManager:
    def __init__(self, logger: logging.Logger = None):
        self.log = logger or logging.getLogger("rbm-setup")
        self.current_release: ReleaseInfo = None
        self.target_release: ReleaseInfo = None
        self.do_restore_esp_config = False

    def prepare(self, release: str = "latest"):
        self.log.info(f"Preparing system upgrade to '{args.release}'")
        self.current_release = self.get_current_release()
        self.target_release = self.get_target_release(release)
        self.log.info(f"Current version: {self.current_release}")
        self.log.info(f"Target version: {self.target_release}")

    def get_current_release(self):
        version_file = ROOT / "version.yaml"
        if not version_file.exists():
            return ReleaseInfo()
        data = yaml.safe_load(open(version_file).read())
        return ReleaseInfo(**data)

    def get_target_release(self, release: str):
        url = f"{SETUP_URL}/release/{release}/version.yaml"
        res = httpx.get(url, follow_redirects=True)
        data = yaml.safe_load(res.text)
        return ReleaseInfo(**data)

    def get_hostname(self):
        return open("/etc/hostname").read().strip() or "rbm-x5"

    def needs_update(self, component: str):
        current = getattr(self.current_release, component)
        target = getattr(self.target_release, component)
        return current != target

    def ensure_file(self, path: Path, content: str, mode: int = 0o600):
        path = Path(path)
        content = content.strip() + "\n"

        path.parent.mkdir(parents=True, exist_ok=True)
        exists = path.exists()
        created, updated = False, False
        needs_update = not exists or path.read_text() != content
        
        if needs_update:
            updated = True
            created = not exists
            with open(path, "w") as file:
                file.write(content)
        
        if stat.S_IMODE(path.stat().st_mode) != mode:
            updated = True
            os.chmod(path, mode)

        self.log.info(f"{path} [mode {mode:o}] created={created} updated={updated}")
        return created, updated

    def ensure_service(self, name: str, description: str, user: str, workdir: str, cmd: str):
        path = Path(f"/etc/systemd/system/{name}.service")
        content = SYSTEMD_UNIT_TEMPLATE.format(
            description=description,
            workdir=workdir,
            user=user,
            cmd=cmd,
        )
        self.ensure_file(path, content)
        self.shell(f"systemctl enable --now {name}.service")

    def shell(self, cmd: str, check: bool = True, capture: bool = True, timeout: int = None, cwd = None):
        try:
            self.log.info(f"$ {cmd}")
            res = sp.run(
                cmd,
                shell=True,
                capture_output=capture,
                text=True,
                timeout=timeout,
                check=check,
                cwd=cwd,
            )
            return res.stdout or "", res.stderr or ""
        except sp.CalledProcessError as err:
            self.log.error(f"Command failed with return code {err.returncode}")
            self.log.error(f"STDOUT:\n{err.stdout or ''}")
            self.log.error(f"STDERR:\n{err.stderr or ''}")
            raise err
        except sp.TimeoutExpired as err:
            self.log.error("Command timed out after {timeout} seconds")
            raise err

    def upgrade(self):
        self.check_running_as_root()
        self.create_hotspot_connection()
        self.set_default_audio_device()
        self.stop_container()
        self.setup_repository()
        if self.needs_update("webui"):
            self.setup_webui()
            self.setup_webtmux()
        if self.needs_update("docker"):
            self.pull_container()
        if self.needs_update("firmware"):
            self.backup_esp_config()
            self.update_firmware()
        self.start_container()
        self.write_version()
        self.log.info("Setup completed")

    def check_running_as_root(self):
        is_root = os.geteuid() == 0
        assert is_root, "Setup script must be run as root (try with sudo)"
    
    def create_hotspot_connection(self):
        self.log.info("Creating hotspot connection...")
        hostname = self.get_hostname()
        content = HOTSPOT_CONN_TEMPLATE.format(hostname=hostname)
        created, updated = self.ensure_file(HOTSPOT_CONN_FILE, content)
        if created or updated:
            self.shell("nmcli connection reload")
        stdout, _ = self.shell("nmcli connection show")
        assert "hotspot" in stdout

    def set_default_audio_device(self):
        udev_path = Path("/etc/udev/rules.d/99-usb-audio.rules")
        created, updated = self.ensure_file(udev_path, AUDIO_UDEV)
        if created or updated:
            self.shell("udevadm control --reload-rules && udevadm trigger")
        asound_path = Path("/etc/asound.conf")
        self.ensure_file(asound_path, ASOUND_CONFIG)

    def setup_repository(self):
        self.log.info("Setting up repository...")
        if REPO_DIR.exists():
            self.log.info("Repository exists - deleting")
            self.shell(f"rm -rf {REPO_DIR}")
        self.shell(f"git clone -b {self.target_release.release} {REPO_URL} {REPO_DIR}")
        self.shell(f"chown -R robomarvel {REPO_DIR}")

    def backup_esp_config(self):
        config_path = ROOT / "esp-config.yaml"
        backup_config_path = ROOT / "esp-config.backup.yaml"
        if config_path.exists():
            self.log.info("Backup esp config...")
            shutil.copyfile(config_path, backup_config_path)
            self.do_restore_esp_config = True

    def setup_webui(self):
        self.log.info("Setting up webui...")
        repo_webui_path = REPO_DIR / "webui"
        opt_webui_path = ROOT / "webui"
        if opt_webui_path.exists():
            shutil.rmtree(opt_webui_path)
        shutil.copytree(repo_webui_path, opt_webui_path)
        self.ensure_service(
            name="rbm-webui",
            description="RBM Web UI",
            user="root",
            workdir=ROOT,
            cmd=f"/opt/rbm/venv/bin/python -m webui.main",
        )

    def setup_webtmux(self):
        ttyd = ROOT / "ttyd"
        if not ttyd.is_file():
            self.shell(f"wget -O /opt/rbm/ttyd {SETUP_URL}/static/ttyd")
            self.shell("chmod +x /opt/rbm/ttyd")
        self.ensure_service(
            name="rbm-webtmux-host",
            description="RBM Web Terminal (host)",
            user="robomarvel",
            workdir=ROOT,
            cmd=f"{ttyd} -W -p 8100 tmux new -A -s webtmux bash",
        )
        self.ensure_service(
            name="rbm-webtmux-docker",
            description="RBM Web Terminal (docker)",
            user="robomarvel",
            workdir=ROOT,
            cmd=f"{ttyd} -W -p 8200 docker exec -it ros tmux new -A -s main bash",
        )

    def stop_container(self):
        self.log.info("Stopping docker container...")
        self.shell("docker stop ros", check=False)

    def pull_container(self):
        self.log.info("Pulling docker image...")
        self.shell("docker compose pull", cwd=REPO_DIR, capture=False)

    def start_container(self):
        self.log.info("Starting docker container...")
        (REPO_DIR / ".autostart").touch()
        self.shell("docker compose up -d --no-build", cwd=REPO_DIR, capture=False)

    def update_firmware(self):
        self.log.info("Downloading firmware...")
        url = f"{SETUP_URL}/release/{self.target_release.release}/firmware.bin"
        path = ROOT / "firmware.bin"
        self.shell(f"wget -O {path} {url}")
        self.log.info("Flashing...")
        cmd = (
            f"{sys.executable} -m esptool --chip esp32 "
            f"--port {SERIAL_PORT} --baud 921600 "
            f"write-flash -z 0x10000 {path}"
        )
        self.shell(cmd, capture=False, check=False)

    def write_version(self):
        self.log.info("Writing version file...")
        version_file = ROOT / "version.yaml"
        with open(version_file, "w") as file:
            yaml.safe_dump(self.target_release.model_dump(), file, sort_keys=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="{levelname} | {name} :: {message}", style="{")

    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=str, default="latest", help="target release (default: latest)")
    args = parser.parse_args()

    manager = SetupManager()
    manager.prepare(release=args.release)
    manager.upgrade()
