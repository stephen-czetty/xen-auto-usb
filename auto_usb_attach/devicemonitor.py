import asyncio
from typing import Dict, Iterable, Optional
from glob import glob

from .xenusb import XenUsb
from .device import Device
from .options import Options
from .xendomain import XenDomain
from .asyncevent import AsyncEvent

import pyudev

sysfs_root = "/sys/bus/usb/devices"


class DeviceMonitor:
    __context = None

    def __devices_of_interest(self, device: Device) -> Iterable['Device']:
        for d in device.children:
            if self.__is_a_device_we_care_about(d, device):
                yield d

    def __is_a_device_we_care_about(self, device: Device, device_to_check: Optional['Device'] = None) -> bool:
        devices = [device_to_check] if device_to_check else self.__root_devices
        for monitored_device in devices:
            if device.device_path.startswith(monitored_device.device_path):
                return not device.is_a_hub() and device.is_a_root_device()

        return False

    async def __get_connected_devices(self, hub_device: Device) -> Dict[str, XenUsb]:
        device_map = {}
        for device in self.__devices_of_interest(hub_device):
            self.__options.print_verbose("Found at startup: {0.device_path}".format(device))
            dev_map = await self.__domain.find_device_mapping(device.sys_name)
            if dev_map is None:
                dev_map = await self.__domain.attach_device_to_xen(device)
            if dev_map is not None:
                device_map[device.sys_name] = dev_map
        return device_map

    def __find_devices(self, vendor_id: str, product_id: str) -> Iterable[Device]:
        for dev_file in glob("{}/*".format(sysfs_root)):
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
        inner = pyudev.Devices.from_path(self.__context, "{0}/{1}".format(sysfs_root, device_name))

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
            attached_device = await self.__domain.attach_device_to_xen(dev)
            ret[dev.sys_name] = attached_device

        self.__specific_devices.append((vendor_id, product_id))
        return ret

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

        self.device_added = AsyncEvent()
        self.device_removed = AsyncEvent()

    def __repr__(self):
        return "DeviceMonitor({!r}, {!r})".format(self.__options, self.__domain)
