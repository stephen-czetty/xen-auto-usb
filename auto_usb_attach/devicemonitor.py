from typing import Dict

from .xenusb import XenUsb
from .device import Device
from .options import Options
from .xendomain import XenDomain
from .event import Event

import pyudev

sysfs_root = "/sys/bus/usb/devices"


class DeviceMonitor:
    __context = None

    def __get_connected_devices(self, hub_device: Device) -> Dict[str, XenUsb]:
        device_map = {}
        for device in hub_device.devices_of_interest():
            self.__options.print_verbose("Found at startup: {0.device_path}".format(device))
            dev_map = self.__domain.find_device_mapping(device.sys_name)
            if dev_map is None:
                dev_map = self.__domain.attach_device_to_xen(device)
            if dev_map is not None:
                device_map[device.sys_name] = dev_map
        return device_map

    def add_hub(self, device_name: str) -> Dict[str, XenUsb]:
        inner = pyudev.Devices.from_path(self.__context, "{0}/{1}".format(sysfs_root, device_name))

        dev = Device(inner)
        if not dev.is_a_root_device():
            raise RuntimeError("Device {0} is not a root device node".format(dev.sys_name))
        if not dev.is_a_hub():
            raise RuntimeError("Device {0} is not a hub".format(dev.sys_name))

        if dev not in self.__root_devices:
            self.__root_devices.append(dev)

        return self.__get_connected_devices(dev)

    # This method never returns unless there's an exception.  Good?  Bad?
    def monitor_devices(self) -> None:
        monitor = pyudev.Monitor.from_netlink(self.__context)
        monitor.filter_by('usb')

        def monitor_callback(device: pyudev.Device) -> None:
            device = Device(device)
            self.__options.print_very_verbose('{0.action} on {0.device_path}'.format(device))
            if device.action == "add":
                if device.is_a_device_we_care_about(self.__root_devices):
                    self.device_added(device)
            elif device.action == "remove":
                self.device_removed(device)

        self.__observer = pyudev.MonitorObserver(monitor, callback=monitor_callback)
        self.__observer.start()

    def wait(self):
        if self.__observer is not None:
            self.__observer.join()

    def __init__(self, opts: Options, xen_domain: XenDomain):
        self.__context = pyudev.Context()
        self.__options = opts
        self.__domain = xen_domain
        self.__root_devices = []
        self.__observer = None

        self.device_added = Event()
        self.device_removed = Event()

    def __repr__(self):
        return "DeviceMonitor({!r}, {!r})".format(self.__options, self.__domain)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.__observer is not None:
            self.__observer.stop()
            self.__started = False
            self.__observer = None
