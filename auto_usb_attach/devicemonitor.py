import asyncio
from typing import Dict, Iterable, Optional
from glob import glob

import pyudev

from .xenusb import XenUsb
from .device import Device
from .options import Options
from .xendomain import XenDomain
from .asyncevent import AsyncEvent

SYSFS_ROOT = "/sys/bus/usb/devices"


class DeviceMonitor:
    __context = None

    def __devices_of_interest(self, device: Device) -> Iterable['Device']:
        for dev in device.children:
            if self.__is_a_device_we_care_about(dev, device):
                yield dev

    def __is_a_device_we_care_about(self, device: Device, hub_device: Optional['Device'] = None) -> bool:
        devices = [hub_device] if hub_device else self.__root_devices
        for monitored_device in devices:
            if device.device_path.startswith(monitored_device.device_path):
                return not device.is_a_hub() and device.is_a_root_device()

        if hub_device is not None:
            return False

        for specific_device in self.__specific_devices:
            if specific_device[0] == device.vendor_id and specific_device[1] == device.product_id:
                return True

        return False

    async def __attach_device(self, device: Device) -> Dict[str, XenUsb]:
        dev_map = await self.__domain.find_device_mapping(device.sys_name)
        if dev_map is None:
            dev_map = await self.__domain.attach_device_to_xen(device)
        if dev_map is not None:
            return {device.sys_name: dev_map}

        return {}

    async def __get_connected_devices(self, hub_device: Device) -> Dict[str, XenUsb]:
        device_map = {}
        for device in self.__devices_of_interest(hub_device):
            self.__options.print_verbose("Found at startup: {0.device_path}".format(device))
            device_map.update(await self.__attach_device(device))

        return device_map

    def __find_devices(self, vendor_id: str, product_id: str) -> Iterable[Device]:
        for dev_file in glob("{}/*".format(SYSFS_ROOT)):
            if dev_file.split("/")[-1].startswith("usb"):
                continue

            dev = Device(pyudev.Devices.from_path(self.__context, dev_file))
            if not dev.is_a_root_device:
                continue

            if dev.vendor_id == vendor_id and dev.product_id == product_id:
                yield dev

    async def __add_hub(self, device: Device) -> Dict[str, XenUsb]:
        if device not in self.__root_devices:
            self.__root_devices.append(device)

        return await self.__get_connected_devices(device)

    async def add_hub(self, device_name: str) -> Dict[str, XenUsb]:
        inner = pyudev.Devices.from_path(self.__context, "{0}/{1}".format(SYSFS_ROOT, device_name))

        dev = Device(inner)
        if not dev.is_a_root_device():
            raise RuntimeError("Device {0} is not a root device node".format(dev.sys_name))
        if not dev.is_a_hub():
            raise RuntimeError("Device {0} is not a hub".format(dev.sys_name))

        return await self.__add_hub(dev)

    async def add_specific_device(self, device_id: str) -> Dict[str, XenUsb]:
        ret = {}
        vendor_id, product_id = device_id.split(":")
        if (vendor_id, product_id) in self.__specific_devices:
            return ret

        if vendor_id is None or product_id is None:
            raise RuntimeError("Device {} is not formatted properly. (Should be <vendor_id>:<product_id>)")

        self.__options.print_debug("Searching for {}".format(device_id))
        for dev in self.__find_devices(vendor_id, product_id):
            self.__options.print_debug("Found device: {!r}".format(dev))
            if dev.is_a_hub():
                return await self.__add_hub(dev)
            ret.update(await self.__attach_device(dev))

        self.__specific_devices.append((vendor_id, product_id))
        return ret

    def shutdown(self):
        self.__shutdown = True

    async def monitor_devices(self) -> None:
        monitor = pyudev.Monitor.from_netlink(self.__context)
        monitor.filter_by('usb')

        while True:
            if self.__shutdown:
                break

            device = monitor.poll(0)
            if device is None:
                await asyncio.sleep(1.0)
                continue

            device = Device(device)
            self.__options.print_very_verbose('{0.action} on {0.device_path}'.format(device))
            if device.action == "add":
                if self.__is_a_device_we_care_about(device):
                    await self.device_added.fire(device)
            elif device.action == "remove":
                await self.device_removed.fire(device)

    def __init__(self, opts: Options, xen_domain: XenDomain):
        self.__context = pyudev.Context()
        self.__options = opts
        self.__domain = xen_domain
        self.__root_devices = []
        self.__specific_devices = []
        self.__shutdown = False

        self.device_added = AsyncEvent()
        self.device_removed = AsyncEvent()

    def __repr__(self):
        return "DeviceMonitor({!r}, {!r})".format(self.__options, self.__domain)
