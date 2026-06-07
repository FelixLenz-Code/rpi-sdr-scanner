"""
core/bluetooth.py – BlueZ-Wrapper für SDR-Scanner BT-Audio (A2DP).

Scannt auf ALLEN verfügbaren Adaptern gleichzeitig (hci0 löst Namen auf,
hci1/USB-Dongle hat bessere Reichweite). Ergebnisse werden zusammengeführt.
Verbindung wird über den Adapter hergestellt, auf dem das Gerät bekannt ist.
"""

import dbus
import os
import re
import subprocess
import threading
import time
import logging

log = logging.getLogger(__name__)

_BLUEZ      = 'org.bluez'
_ADAPTER_IF = 'org.bluez.Adapter1'
_DEVICE_IF  = 'org.bluez.Device1'
_PROPS_IF   = 'org.freedesktop.DBus.Properties'
_OBJMGR_IF  = 'org.freedesktop.DBus.ObjectManager'

# BlueZ-Alias der automatisch als "AA-BB-CC-DD-EE-FF" generiert wird → kein echter Name
_MAC_RE = re.compile(r'^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$')


class BTDevice:
    def __init__(self, address, name, rssi, paired, connected, adapter_path, trusted=False):
        self.address      = address
        self.name         = name or address
        self.rssi         = rssi
        self.paired       = paired
        self.connected    = connected
        self.trusted      = trusted
        self.adapter_path = adapter_path   # welcher hci hat dieses Gerät gefunden

    def display_name(self, maxlen=22) -> str:
        return self.name[:maxlen]

    @property
    def has_name(self) -> bool:
        return self.name != self.address


class BluetoothManager:
    def __init__(self):
        self._bus             = None
        self._connected_addr: str | None = None
        self._connected_adapter: str | None = None
        self._scan_devices:  list[BTDevice] = []
        self._lock           = threading.Lock()
        self.on_disconnect   = None   # callback() nach Trennung

    # ── Bus / Adapter ─────────────────────────────────────────────────────────

    def _bus_get(self):
        if self._bus is None:
            self._bus = dbus.SystemBus()
        return self._bus

    def _all_adapter_paths(self) -> list[str]:
        bus = self._bus_get()
        mgr = dbus.Interface(bus.get_object(_BLUEZ, '/'), _OBJMGR_IF)
        paths = sorted(
            str(p) for p, ifaces in mgr.GetManagedObjects().items()
            if _ADAPTER_IF in ifaces
        )
        return paths  # ['…/hci0', '…/hci1']

    def available(self) -> bool:
        try:
            return len(self._all_adapter_paths()) > 0
        except Exception:
            return False

    def _power_on_all(self) -> None:
        """RF-Kill entsperren und alle Adapter hochbringen."""
        try:
            subprocess.run(['rfkill', 'unblock', 'bluetooth'],
                           timeout=3, capture_output=True)
            time.sleep(0.3)
        except Exception:
            pass
        for ap in self._all_adapter_paths():
            name = os.path.basename(ap)
            try:
                subprocess.run(['hciconfig', name, 'up'],
                               timeout=3, capture_output=True)
            except Exception:
                pass
        time.sleep(0.5)

    # ── Scan ──────────────────────────────────────────────────────────────────

    def scan(self, duration: float = 10.0,
             progress_cb=None) -> list[BTDevice]:
        """
        Startet Discovery auf ALLEN Adaptern gleichzeitig.
        progress_cb(elapsed, total) wird alle 0.5 s aufgerufen.
        """
        self._power_on_all()
        bus      = self._bus_get()
        adapters = self._all_adapter_paths()
        started  = []

        for ap in adapters:
            try:
                iface = dbus.Interface(bus.get_object(_BLUEZ, ap), _ADAPTER_IF)
                iface.StartDiscovery()
                started.append(ap)
                log.info("BT-Scan: Discovery auf %s gestartet", ap)
            except dbus.DBusException as e:
                log.warning("StartDiscovery %s: %s", ap, e)

        total = duration + 3.0   # +3 s für Namensauflösung
        t0    = time.monotonic()
        while time.monotonic() - t0 < total:
            time.sleep(0.5)
            with self._lock:
                self._scan_devices = self._collect_devices()
            if progress_cb:
                progress_cb(min(time.monotonic() - t0, total), total)

        for ap in started:
            try:
                dbus.Interface(bus.get_object(_BLUEZ, ap), _ADAPTER_IF).StopDiscovery()
            except Exception:
                pass

        devices = self._collect_devices()
        with self._lock:
            self._scan_devices = devices
        log.info("BT-Scan abgeschlossen: %d Geräte", len(devices))
        return devices

    def _collect_devices(self) -> list[BTDevice]:
        """
        Liest alle Geräte aus ALLEN Adaptern, dedupliziert nach MAC.
        Eintrag mit echtem Namen gewinnt über MAC-only Eintrag.
        """
        try:
            bus = self._bus_get()
            mgr = dbus.Interface(bus.get_object(_BLUEZ, '/'), _OBJMGR_IF)
            seen: dict[str, BTDevice] = {}

            for path, ifaces in mgr.GetManagedObjects().items():
                if _DEVICE_IF not in ifaces:
                    continue
                p    = ifaces[_DEVICE_IF]
                addr = str(p.get('Address', ''))
                if not addr:
                    continue

                adapter_path = str(path).rsplit('/dev_', 1)[0]

                # Echten Namen ermitteln (MAC-ähnliche Aliases ignorieren)
                raw_name  = str(p.get('Name', ''))
                raw_alias = str(p.get('Alias', ''))
                if raw_name and not _MAC_RE.match(raw_name):
                    name = raw_name
                elif raw_alias and not _MAC_RE.match(raw_alias):
                    name = raw_alias
                else:
                    name = addr

                rssi = int(p['RSSI']) if 'RSSI' in p else None
                dev  = BTDevice(
                    addr, name, rssi,
                    bool(p.get('Paired', False)),
                    bool(p.get('Connected', False)),
                    adapter_path,
                    trusted=bool(p.get('Trusted', False)),
                )

                # Bestehenden Eintrag nur überschreiben wenn neuer echten Namen hat
                existing = seen.get(addr)
                if existing is None:
                    seen[addr] = dev
                elif dev.has_name and not existing.has_name:
                    seen[addr] = dev
                elif dev.rssi and (not existing.rssi or dev.rssi > existing.rssi):
                    # Gleichwertige Namen: besseres RSSI bevorzugen
                    if existing.has_name == dev.has_name:
                        seen[addr] = dev

            out     = list(seen.values())
            named   = sorted([d for d in out if d.has_name],
                             key=lambda d: d.rssi or -999, reverse=True)
            unnamed = sorted([d for d in out if not d.has_name],
                             key=lambda d: d.rssi or -999, reverse=True)
            return named + unnamed

        except Exception as e:
            log.warning("_collect_devices: %s", e)
            return []

    # ── Pairing & Connect ─────────────────────────────────────────────────────

    def _find_device_path(self, address: str) -> str | None:
        """Sucht den D-Bus-Pfad eines Geräts über alle Adapter."""
        try:
            bus = self._bus_get()
            mgr = dbus.Interface(bus.get_object(_BLUEZ, '/'), _OBJMGR_IF)
            suffix = 'dev_' + address.replace(':', '_')
            for path in mgr.GetManagedObjects():
                if str(path).endswith(suffix):
                    return str(path)
        except Exception:
            pass
        # Fallback: Pfad konstruieren (bevorzugt höchster Adapter-Index)
        adapters = self._all_adapter_paths()
        if adapters:
            return f"{adapters[-1]}/dev_{address.replace(':', '_')}"
        return None

    def pair(self, address: str) -> bool:
        try:
            path = self._find_device_path(address)
            if not path:
                return False
            bus  = self._bus_get()
            props = dbus.Interface(bus.get_object(_BLUEZ, path), _PROPS_IF)
            if bool(props.Get(_DEVICE_IF, 'Paired')):
                log.info("BT: %s bereits gekoppelt", address)
                return True
            dev = dbus.Interface(bus.get_object(_BLUEZ, path), _DEVICE_IF)
            dev.Pair()
            log.info("BT: %s gekoppelt via %s", address, path)
            return True
        except dbus.DBusException as e:
            log.error("BT-Pair %s: %s", address, e)
            return False

    def connect(self, address: str) -> bool:
        try:
            path = self._find_device_path(address)
            if not path:
                log.error("BT-Connect: Gerät %s nicht gefunden", address)
                return False
            bus = self._bus_get()
            dev = dbus.Interface(bus.get_object(_BLUEZ, path), _DEVICE_IF)
            try:
                dev.Connect()
            except dbus.DBusException as e:
                if 'AlreadyConnected' not in str(e):
                    raise
                log.info("BT: %s bereits verbunden", address)
            self._connected_addr    = address
            self._connected_adapter = path.rsplit('/dev_', 1)[0]
            log.info("BT: %s verbunden", address)
            return True
        except dbus.DBusException as e:
            log.error("BT-Connect %s: %s", address, e)
            return False

    def set_audio_sink(self, address: str) -> bool:
        """Wartet auf A2DP-Sink und setzt ihn als PA-Default (bis 20s).

        Sucht flexibel per MAC-Substring – funktioniert mit PulseAudio
        (bluez_sink.XX.a2dp_sink) und PipeWire (bluez_output.XX.1).
        """
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            sink_name = self._find_pa_sink(address)
            if sink_name:
                self._set_pa_sink(sink_name)
                log.info("BT: PA-Sink gesetzt: %s", sink_name)
                return True
            time.sleep(0.5)
        log.warning("BT: A2DP-Sink für %s nach 45s nicht erschienen", address)
        return False

    def disconnect(self) -> None:
        if not self._connected_addr:
            return
        try:
            path = self._find_device_path(self._connected_addr)
            if path:
                bus = self._bus_get()
                dbus.Interface(bus.get_object(_BLUEZ, path), _DEVICE_IF).Disconnect()
        except Exception as e:
            log.warning("BT-Disconnect: %s", e)
        self._restore_default_sink()
        log.info("BT: getrennt (%s)", self._connected_addr)
        self._connected_addr    = None
        self._connected_adapter = None
        if self.on_disconnect:
            threading.Thread(target=self.on_disconnect,
                             daemon=True, name="bt-ondisconnect").start()

    def remove_device(self, address: str) -> bool:
        """Entfernt (unpaired) ein Gerät vollständig aus BlueZ."""
        try:
            path = self._find_device_path(address)
            if not path:
                return False
            bus          = self._bus_get()
            adapter_path = path.rsplit('/dev_', 1)[0]
            adapter      = dbus.Interface(bus.get_object(_BLUEZ, adapter_path), _ADAPTER_IF)
            adapter.RemoveDevice(path)
            if self._connected_addr == address:
                self._connected_addr    = None
                self._connected_adapter = None
            log.info("BT: Gerät %s entfernt", address)
            return True
        except dbus.DBusException as e:
            log.error("BT-Remove %s: %s", address, e)
            return False

    def trust(self, address: str) -> None:
        try:
            path = self._find_device_path(address)
            if not path:
                return
            bus   = self._bus_get()
            props = dbus.Interface(bus.get_object(_BLUEZ, path), _PROPS_IF)
            props.Set(_DEVICE_IF, 'Trusted', dbus.Boolean(True))
        except Exception as e:
            log.warning("BT trust: %s", e)

    # ── Status ────────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        if not self._connected_addr:
            return False
        try:
            path = self._find_device_path(self._connected_addr)
            if not path:
                return False
            bus   = self._bus_get()
            props = dbus.Interface(bus.get_object(_BLUEZ, path), _PROPS_IF)
            return bool(props.Get(_DEVICE_IF, 'Connected'))
        except Exception:
            return False

    def connected_name(self) -> str | None:
        if not self._connected_addr:
            return None
        try:
            path = self._find_device_path(self._connected_addr)
            if not path:
                return self._connected_addr
            bus   = self._bus_get()
            props = dbus.Interface(bus.get_object(_BLUEZ, path), _PROPS_IF)
            return str(props.Get(_DEVICE_IF, 'Name'))
        except Exception:
            return self._connected_addr

    @property
    def connected_address(self) -> str | None:
        return self._connected_addr

    @connected_address.setter
    def connected_address(self, v: str | None):
        self._connected_addr = v

    def get_paired_devices(self) -> list[BTDevice]:
        """
        Liefert alle Geräte, mit denen der User bewusst interagiert hat:
        - Paired=True  → vollständig gekoppelt (LinkKey vorhanden)
        - Trusted=True → vom Scanner als vertraut markiert (nach Connect),
                         auch wenn das Pairing auf einem anderen Adapter lag

        Beide Gruppen erscheinen im BT-Menü, auch wenn das Gerät gerade
        ausgeschaltet / nicht in Reichweite ist.
        """
        result = [d for d in self._collect_devices() if d.paired or d.trusted]
        result.sort(key=lambda d: (not d.connected, d.name.lower()))
        return result

    def last_scan_results(self) -> list[BTDevice]:
        with self._lock:
            return list(self._scan_devices)

    # ── PulseAudio ────────────────────────────────────────────────────────────

    @staticmethod
    def _pa_env() -> dict:
        """Stellt sicher dass pactl den richtigen PulseAudio-Socket findet."""
        import os
        env = os.environ.copy()
        uid = os.getuid()
        env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{uid}')
        env.setdefault('PULSE_RUNTIME_PATH', f'/run/user/{uid}/pulse')
        return env

    @staticmethod
    def _find_pa_sink(address: str) -> str | None:
        normalized = address.replace(':', '_').lower()
        try:
            out = subprocess.check_output(
                ['pactl', 'list', 'sinks', 'short'], text=True, timeout=5,
                env=BluetoothManager._pa_env()
            )
            for line in out.splitlines():
                if normalized in line.lower():
                    return line.split('\t')[1]
        except Exception as e:
            log.warning("pactl list sinks: %s", e)
        return None

    @staticmethod
    def _set_pa_sink(sink: str) -> None:
        env = BluetoothManager._pa_env()
        try:
            subprocess.run(['pactl', 'set-default-sink', sink],
                           check=True, timeout=5, env=env)
            out = subprocess.check_output(
                ['pactl', 'list', 'sink-inputs', 'short'], text=True, timeout=5, env=env
            )
            for line in out.splitlines():
                idx = line.split('\t')[0].strip()
                if idx.isdigit():
                    subprocess.run(['pactl', 'move-sink-input', idx, sink],
                                   timeout=5, env=env)
        except Exception as e:
            log.warning("_set_pa_sink: %s", e)

    @staticmethod
    def _restore_default_sink() -> None:
        env = BluetoothManager._pa_env()
        try:
            out = subprocess.check_output(
                ['pactl', 'list', 'sinks', 'short'], text=True, timeout=5, env=env
            )
            for line in out.splitlines():
                if 'bluez' not in line.lower():
                    sink = line.split('\t')[1]
                    subprocess.run(['pactl', 'set-default-sink', sink],
                                   check=True, timeout=5, env=env)
                    out2 = subprocess.check_output(
                        ['pactl', 'list', 'sink-inputs', 'short'], text=True, timeout=5, env=env
                    )
                    for l2 in out2.splitlines():
                        idx = l2.split('\t')[0].strip()
                        if idx.isdigit():
                            subprocess.run(['pactl', 'move-sink-input', idx, sink],
                                           timeout=5, env=env)
                    return
        except Exception as e:
            log.warning("_restore_default_sink: %s", e)
