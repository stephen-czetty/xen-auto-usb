import asyncio
from typing import Dict, cast, Iterable, Optional

from .xenusb import XenUsb
from .device import Device
from .options import Options
from .xendomain import XenDomain
from .asyncevent import AsyncEvent

import pyudev

sysfs_root = "/sys/bus/usb/devices"


class DeviceMonitor:
    __context = None

    async def __get_connected_devices(self, hub_device: Device) -> Dict[str, XenUsb]:
        device_map = {}
        for device in hub_device.devices_of_interest():
            self.__options.print_verbose("Found at startup: {0.device_path}".format(device))
            dev_map = await self.__domain.find_device_mapping(device.sys_name)
            if dev_map is None:
                dev_map = await self.__domain.attach_device_to_xen(device)
            if dev_map is not None:
                device_map[device.sys_name] = dev_map
        return device_map

    async def add_hub(self, device_name: str) -> Dict[str, XenUsb]:
        inner = pyudev.Devices.from_path(self.__context, "{0}/{1}".format(sysfs_root, device_name))

        dev = Device(inner)
        if not dev.is_a_root_device():
            raise RuntimeError("Device {0} is not a root device node".format(dev.sys_name))
        if not dev.is_a_hub():
            raise RuntimeError("Device {0} is not a hub".format(dev.sys_name))

        if dev not in self.__root_devices:
            self.__root_devices.append(dev)

        return await self.__get_connected_devices(dev)

    async def monitor_devices(self) -> None:
        monitor = pyudev.Monitor.from_netlink(self.__context)
        monitor.filter_by('usb')

        while True:
            device = monitor.poll(0)
            if device is None:
                await asyncio.sleep(1.0)
                continue

            device = Device(device)
            self.__options.print_very_verbose('{0.action} on {0.device_path}'.format(device))
            if device.action == "add":
                if device.is_a_device_we_care_about(self.__root_devices):
                    await self.device_added.fire(device)
            elif device.action == "remove":
                await self.device_removed.fire(device)

    def __init__(self, opts: Options, xen_domain: XenDomain):
        self.__context = pyudev.Context()
        self.__options = opts
        self.__domain = xen_domain
        self.__root_devices = []

        self.device_added = AsyncEvent()
        self.device_removed = AsyncEvent()

    def __repr__(self):
        return "DeviceMonitor({!r}, {!r})".format(self.__options, self.__domain)
