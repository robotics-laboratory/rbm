#!/usr/bin/python3
import argparse
import asyncio
import contextlib
import json
import os
import re
import signal
import sys
from pathlib import Path

BLUEZ = 'org.bluez'
ADAPTER = 'org.bluez.Adapter1'
DEVICE = 'org.bluez.Device1'
PROPERTIES = 'org.freedesktop.DBus.Properties'
MANAGER = 'org.freedesktop.DBus.ObjectManager'
AGENT = 'org.bluez.AgentManager1'
AGENT_PATH = '/org/robomarvel/GamepadAgent'
GAMEPAD = re.compile(r'Wireless\s+Controller|DualShock|PS4|Gamepad|DGP|DEX', re.I)


def plain(value):
    if hasattr(value, 'value'):
        return plain(value.value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def atomic(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(value, encoding='utf-8')
    temp.replace(path)


def text(value):
    return ''.join(c if c.isprintable() else ' ' for c in str(value))


class Bluetooth:
    def __init__(self, directory, adapter):
        self.directory = directory
        self.adapter_name = adapter
        self.adapter = None
        self.objects = {}
        self.bus = None
        self.agent = None
        self.pairing = None
        self.scanning = False
        self.lock = asyncio.Lock()
        self.stopping = asyncio.Event()
        self.tasks = set()
        self.lost = False

    async def call(self, path, interface, member, signature='', body=None, timeout=5):
        from dbus_next import Message, MessageType
        reply = await asyncio.wait_for(self.bus.call(Message(
            destination=BLUEZ, path=path, interface=interface, member=member,
            signature=signature, body=body or [])), timeout)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f'{reply.error_name}: ' + ' '.join(map(str, reply.body)))
        return plain(reply.body)

    async def set_property(self, path, interface, key, signature, value):
        from dbus_next import Variant
        await self.call(path, PROPERTIES, 'Set', 'ssv',
                        [interface, key, Variant(signature, value)])

    async def refresh(self):
        self.objects = (await self.call('/', MANAGER, 'GetManagedObjects'))[0]
        self.save()

    async def properties(self, path, interface):
        values = (await self.call(path, PROPERTIES, 'GetAll', 's', [interface]))[0]
        self.objects.setdefault(path, {})[interface] = values
        self.save()
        return values

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def restore_properties(self, path, interface):
        try:
            await self.properties(path, interface)
        except Exception:
            pass

    async def monitor_bus(self):
        with contextlib.suppress(Exception):
            await self.bus.wait_for_disconnect()
        self.lost = True
        self.objects.clear()
        self.save()
        atomic(self.directory / 'backend-error', 'The system D-Bus connection closed. Select an action to reconnect.\n')
        self.stopping.set()

    def changed(self, message):
        from dbus_next import MessageType
        if message.message_type != MessageType.SIGNAL:
            return
        body = plain(message.body)
        if message.interface == 'org.freedesktop.DBus' and message.member == 'NameOwnerChanged':
            if body[0] == BLUEZ and body[1]:
                self.lost = True
                self.objects.clear()
                self.save()
                atomic(self.directory / 'backend-error', 'BlueZ restarted. Select an action to reconnect.\n')
                self.stopping.set()
            return
        if message.interface == MANAGER and message.member == 'InterfacesAdded':
            self.objects.setdefault(body[0], {}).update(body[1])
        elif message.interface == MANAGER and message.member == 'InterfacesRemoved':
            for interface in body[1]:
                self.objects.get(body[0], {}).pop(interface, None)
        elif message.interface == PROPERTIES and message.member == 'PropertiesChanged':
            interface, changed, invalidated = body
            properties = self.objects.setdefault(message.path, {}).setdefault(interface, {})
            properties.update(changed)
            for key in invalidated:
                properties.pop(key, None)
            if invalidated and interface in (ADAPTER, DEVICE):
                self.spawn(self.restore_properties(message.path, interface))
        else:
            return
        self.save()

    def gamepads(self):
        devices = {}
        for path, interfaces in self.objects.items():
            value = interfaces.get(DEVICE, {})
            if value.get('Adapter') != self.adapter:
                continue
            if value.get('Icon') != 'input-gaming' and not GAMEPAD.search(
                    value.get('Name', '') + ' ' + value.get('Alias', '')):
                continue
            address = value.get('Address', '')
            if re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', address):
                devices[address.upper()] = (path, value)
        return devices

    def save(self):
        cache = self.directory / 'cache'
        cache.mkdir(exist_ok=True)
        devices = self.gamepads()
        for address, (_, value) in devices.items():
            lines = [f'Device {address}']
            for key in ('Name', 'Alias', 'Paired', 'Bonded', 'Trusted', 'Connected', 'RSSI'):
                if key in value:
                    item = value[key]
                    if isinstance(item, bool):
                        item = 'yes' if item else 'no'
                    lines.append(f'    {key}: {text(item)}')
            atomic(cache / address, '\n'.join(lines) + '\n')
        atomic(cache / 'index', ''.join(address + '\n' for address in sorted(devices)))
        for old in cache.iterdir():
            if ':' in old.name and old.name not in devices:
                old.unlink(missing_ok=True)

    def device(self, address):
        item = self.gamepads().get(address.upper())
        if item is None:
            raise RuntimeError('This gamepad is no longer available. Refresh or scan again.')
        return item

    async def powered(self):
        if self.lost:
            raise RuntimeError('BlueZ is no longer available.')
        if self.adapter not in self.objects or ADAPTER not in self.objects[self.adapter]:
            raise RuntimeError('The Bluetooth adapter was removed. Restart the utility.')
        values = await self.properties(self.adapter, ADAPTER)
        if not values.get('Powered'):
            await self.set_property(self.adapter, ADAPTER, 'Powered', 'b', True)
            values = await self.properties(self.adapter, ADAPTER)
            if not values.get('Powered'):
                raise RuntimeError('The Bluetooth adapter is powered off. Check rfkill status.')

    async def start(self):
        from dbus_next import BusType, Message
        from dbus_next.aio import MessageBus
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self.spawn(self.monitor_bus())
        self.bus.add_message_handler(self.changed)
        for rule in ("type='signal',sender='org.bluez'",
                     "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.bluez'"):
            reply = await asyncio.wait_for(self.bus.call(Message(
                destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus', member='AddMatch', signature='s', body=[rule])), 5)
            if reply.error_name:
                raise RuntimeError(reply.error_name)
        await self.refresh()
        adapters = sorted(path for path, interfaces in self.objects.items() if ADAPTER in interfaces)
        if self.adapter_name:
            adapters = [p for p in adapters if p.rsplit('/', 1)[-1] == self.adapter_name]
        if not adapters:
            raise RuntimeError('No Bluetooth adapter is available.')
        self.adapter = next((p for p in adapters if self.objects[p][ADAPTER].get('Powered')), adapters[0])
        self.agent = make_agent(self)
        self.bus.export(AGENT_PATH, self.agent)
        await self.call('/org/bluez', AGENT, 'RegisterAgent', 'os', [AGENT_PATH, 'NoInputNoOutput'])
        await self.powered()
        self.save()

    async def perform(self, command, args):
        if command == 'ready':
            return 'Bluetooth is ready.'
        await self.powered()
        if command == 'refresh':
            await self.refresh()
            return 'Gamepad information updated.'
        if command == 'scan':
            from dbus_next import Variant
            seconds = int(args[0])
            if not 1 <= seconds <= 30:
                raise ValueError('Scan duration must be between 1 and 30 seconds.')
            await self.call(self.adapter, ADAPTER, 'SetDiscoveryFilter', 'a{sv}',
                            [{'Transport': Variant('s', 'auto'), 'DuplicateData': Variant('b', False)}])
            await self.call(self.adapter, ADAPTER, 'StartDiscovery')
            self.scanning = True
            try:
                await asyncio.sleep(seconds)
            finally:
                await self.stop_scan()
            return 'Scan complete.'
        path, _ = self.device(args[0])
        values = await self.properties(path, DEVICE)
        if command == 'info':
            return 'Gamepad information updated.'
        if command == 'pair':
            new = not values.get('Paired')
            if new:
                await self.set_property(self.adapter, ADAPTER, 'Pairable', 'b', True)
                if not (await self.properties(self.adapter, ADAPTER)).get('Pairable'):
                    raise RuntimeError('The adapter is not ready for pairing.')
                self.pairing = path
                try:
                    await self.call(path, DEVICE, 'Pair', timeout=30)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    with contextlib.suppress(Exception):
                        await self.call(path, DEVICE, 'CancelPairing', timeout=2)
                    raise
                finally:
                    self.pairing = None
                values = await self.properties(path, DEVICE)
            if not values.get('Paired') or values.get('Bonded') is False:
                raise RuntimeError('Pairing keys were not saved. Forget this gamepad and pair it again.')
            if not values.get('Trusted'):
                await self.set_property(path, DEVICE, 'Trusted', 'b', True)
                values = await self.properties(path, DEVICE)
            if not values.get('Trusted'):
                raise RuntimeError('The gamepad is paired, but could not be marked as trusted.')
            return 'New pairing: ' + ('yes' if new else 'no')
        if command == 'connect':
            if values.get('Connected'):
                return 'The gamepad is already connected.'
            if not values.get('Paired') or values.get('Bonded') is False:
                raise RuntimeError('This gamepad has no saved pairing. Use Pair New Gamepad first.')
            await self.call(path, DEVICE, 'Connect', timeout=30)
            if not (await self.properties(path, DEVICE)).get('Connected'):
                raise RuntimeError('Connection did not remain active. Wake the gamepad and try again.')
            return 'The gamepad is connected.'
        if command == 'disconnect':
            if not values.get('Connected'):
                return 'The gamepad is already disconnected.'
            await self.call(path, DEVICE, 'Disconnect', timeout=30)
            if (await self.properties(path, DEVICE)).get('Connected'):
                raise RuntimeError('The gamepad is still connected.')
            return 'The gamepad is disconnected.'
        if command == 'rename':
            name = args[1]
            if not name.strip() or len(name) > 248 or name != text(name):
                raise ValueError('Use a name of 1 to 248 printable characters.')
            await self.set_property(path, DEVICE, 'Alias', 's', name)
            if (await self.properties(path, DEVICE)).get('Alias') != name:
                raise RuntimeError('Could not verify the new name.')
            return 'Gamepad renamed.'
        if command == 'remove':
            await self.call(self.adapter, ADAPTER, 'RemoveDevice', 'o', [path])
            await self.refresh()
            if DEVICE in self.objects.get(path, {}):
                raise RuntimeError('The gamepad is still present.')
            return 'The gamepad has been removed.'
        raise ValueError('Unknown Bluetooth operation.')

    async def stop_scan(self):
        if self.scanning:
            await self.call(self.adapter, ADAPTER, 'StopDiscovery', timeout=2)
            self.scanning = False

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        operation = disconnected = None
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
            request = json.loads(line)
            command, args = request['command'], request.get('args', [])
            counts = {'ready': 0, 'refresh': 0, 'scan': 1, 'info': 1, 'pair': 1,
                      'connect': 1, 'disconnect': 1, 'rename': 2, 'remove': 1}
            if command not in counts or not isinstance(args, list) or len(args) != counts[command]:
                raise ValueError('Invalid Bluetooth request.')
            if not all(isinstance(arg, str) for arg in args):
                raise ValueError('Invalid Bluetooth arguments.')
            if self.lock.locked():
                raise RuntimeError('Another Bluetooth operation is still running.')
            async with self.lock:
                operation = asyncio.create_task(self.perform(command, args))
                disconnected = asyncio.create_task(reader.read(1))
                done, _ = await asyncio.wait((operation, disconnected), return_when=asyncio.FIRST_COMPLETED)
                if operation not in done:
                    operation.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await operation
                    return
                result = {'ok': True, 'message': operation.result()}
            writer.write((json.dumps(result) + '\n').encode())
            await writer.drain()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            detail = str(error) or ('Bluetooth operation timed out.' if isinstance(error, asyncio.TimeoutError) else type(error).__name__)
            with contextlib.suppress(ConnectionError):
                writer.write((json.dumps({'ok': False, 'message': detail}) + '\n').encode())
                await writer.drain()
        finally:
            for pending in (operation, disconnected):
                if pending:
                    pending.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await pending
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
            self.tasks.discard(task)

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await self.stop_scan()
        if self.bus:
            with contextlib.suppress(Exception):
                await self.call('/org/bluez', AGENT, 'UnregisterAgent', 'o', [AGENT_PATH], timeout=2)
            self.bus.disconnect()


def make_agent(backend):
    from dbus_next import DBusError
    from dbus_next.service import ServiceInterface, method

    class GamepadAgent(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.Agent1')

        def selected(self, device):
            if device != backend.pairing:
                raise DBusError('org.bluez.Error.Rejected', 'No pairing was requested for this device.')

        @method()
        def Release(self):
            pass

        @method()
        def Cancel(self):
            pass

        @method()
        def RequestConfirmation(self, device: 'o', passkey: 'u'):
            self.selected(device)

        @method()
        def RequestAuthorization(self, device: 'o'):
            self.selected(device)

        @method()
        def AuthorizeService(self, device: 'o', uuid: 's'):
            self.selected(device)
            if uuid.lower() not in ('00001124-0000-1000-8000-00805f9b34fb',
                                    '00001812-0000-1000-8000-00805f9b34fb'):
                raise DBusError('org.bluez.Error.Rejected', 'Only gamepad input services are supported.')

        @method()
        def RequestPinCode(self, device: 'o') -> 's':
            raise DBusError('org.bluez.Error.Rejected', 'This gamepad requires a PIN; PIN pairing is not supported.')

        @method()
        def RequestPasskey(self, device: 'o') -> 'u':
            raise DBusError('org.bluez.Error.Rejected', 'This gamepad requires a passkey; passkey pairing is not supported.')

    return GamepadAgent()


async def serve(directory, adapter):
    backend = Bluetooth(directory, adapter)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, backend.stopping.set)
    server = None
    startup = asyncio.create_task(backend.start())
    stopping = asyncio.create_task(backend.stopping.wait())
    try:
        done, _ = await asyncio.wait((startup, stopping), return_when=asyncio.FIRST_COMPLETED)
        if stopping in done:
            return
        await startup
        socket = directory / 'bluez.sock'
        socket.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(backend.handle, path=str(socket), limit=8192)
        atomic(directory / 'backend-ready', 'ready\n')
        await backend.stopping.wait()
    finally:
        for task in (startup, stopping):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        (directory / 'backend-ready').unlink(missing_ok=True)
        if server:
            server.close()
            await server.wait_closed()
        await backend.close()
        (directory / 'bluez.sock').unlink(missing_ok=True)


async def request(directory, command, args):
    if command == 'ready':
        for _ in range(150):
            if (directory / 'backend-error').exists():
                raise RuntimeError((directory / 'backend-error').read_text())
            if (directory / 'backend-ready').exists():
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError('Timed out preparing Bluetooth.')
    reader, writer = await asyncio.open_unix_connection(str(directory / 'bluez.sock'))
    try:
        writer.write((json.dumps({'command': command, 'args': args}) + '\n').encode())
        await writer.drain()
        result = json.loads(await asyncio.wait_for(reader.readline(), 45))
        if not result['ok']:
            raise RuntimeError(result['message'])
        print(result['message'])
    finally:
        writer.close()
        await writer.wait_closed()


def progress(pid, title, description):
    import curses
    import textwrap
    import time
    import unicodedata

    def fit(value, width):
        result = ''
        used = 0
        for char in value:
            size = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1)
            if used + size > width:
                break
            result += char
            used += size
        return result

    def draw(screen):
        started = time.monotonic()
        tick = 0
        spinner = '|/-\\'
        with contextlib.suppress(curses.error):
            curses.curs_set(0)
        background = body = heading = 0
        if curses.has_colors():
            curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
            curses.init_pair(3, curses.COLOR_RED, curses.COLOR_WHITE)
            background, body, heading = (curses.color_pair(n) for n in (1, 2, 3))
        screen.timeout(100)
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            rows, columns = screen.getmaxyx()
            screen.bkgd(' ', background)
            screen.erase()
            elapsed = int(time.monotonic() - started)
            status = f'{spinner[tick % 4]}  Working...  Elapsed: {elapsed} s'
            if rows < 8 or columns < 24:
                with contextlib.suppress(curses.error):
                    screen.addstr(0, 0, fit(status, max(0, columns - 1)))
                screen.refresh()
            else:
                width = min(78, columns - 4)
                lines = []
                for line in description.splitlines():
                    lines.extend(textwrap.wrap(line, width - 6) or [''])
                height = min(max(10, len(lines) + 6), rows - 2)
                top, left = (rows - height) // 2, (columns - width) // 2
                screen.noutrefresh()
                window = curses.newwin(height, width, top, left)
                window.bkgd(' ', body)
                window.erase()
                window.border('|', '|', '-', '-', '+', '+', '+', '+')
                caption = ' ' + fit(title, width - 6) + ' '
                window.addstr(0, max(1, (width - len(caption)) // 2), caption, heading)
                for row, line in enumerate(lines[:height - 6], 2):
                    window.addstr(row, 3, fit(line, width - 6), body)
                window.addstr(height - 3, 3, fit(status, width - 6), body)
                window.addstr(height - 2, 3, fit('Ctrl+C to exit', width - 6), body)
                window.noutrefresh()
                curses.doupdate()
            screen.getch()
            tick += 1

    curses.wrapper(draw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['serve', 'request', 'progress'])
    parser.add_argument('directory', type=Path)
    parser.add_argument('command', nargs='?', default='ready')
    parser.add_argument('args', nargs='*')
    parser.add_argument('--adapter', default='')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.mode == 'serve':
            asyncio.run(serve(args.directory, args.adapter))
        elif args.mode == 'progress':
            progress(int(args.command), *args.args)
        else:
            asyncio.run(request(args.directory, args.command, args.args))
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        message = text(str(error) or type(error).__name__)
        if args.mode == 'serve':
            atomic(args.directory / 'backend-error', message + '\n')
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
