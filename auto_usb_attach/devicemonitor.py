from typing import Dict, Tuple, Iterable, Optional, cast, List
from .device import Device
from .options import Options
from .xendomain import XenDomain
from .event import Event

import pyudev

sysfs_root = "/sys/bus/usb/devices"


class DeviceMonitor:
    __context = None

    def add_monitored_device(self, device_name: str) -> Device:
        inner = pyudev.Devices.from_path(self.__context, "{0}/{1}".format(sysfs_root, device_name))

        dev = Device(inner)
        if not dev.is_a_root_device():
            raise RuntimeError("Device {0} is not a root device node".format(dev.sys_name))
        if not dev.is_a_hub():
            raise RuntimeError("Device {0} is not a hub".format(dev.sys_name))

        return dev

    # This method never returns unless there's an exception.  Good?  Bad?
    def monitor_devices(self, known_devices: Dict[str, Tuple[int, int, int, int]]) \
            -> Dict[str, Tuple[int, int, int, int]]:
        device_map = known_devices.copy()
        monitor = pyudev.Monitor.from_netlink(self.__context)
        monitor.filter_by('usb')

        for device in cast(Iterable[Optional[pyudev.Device]], iter(monitor.poll, None)):
            if device is None:
                return device_map

            device = Device(device)
            self.__options.print_very_verbose('{0.action} on {0.device_path}'.format(device))
            if device.action == "add":
                self.device_added(device)
            elif device.action == "remove":
                self.device_removed(device)

    def __init__(self, opts: Options, xen_domain: XenDomain):
        self.__context = pyudev.Context()
        self.__options = opts
        self.__domain = xen_domain

        self.device_added = Event()
        self.device_removed = Event()
