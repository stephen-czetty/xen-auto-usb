from typing import Dict, Tuple, Iterable, Optional, cast
from .device import Device
from .options import Options
from .xendomain import XenDomain

import pyudev

sysfs_root = "/sys/bus/usb/devices"


class DeviceMonitor:
    __context = None

    def __get_device(self, device_name: str) -> Device:
        inner = pyudev.Devices.from_path(self.__context, "{0}/{1}".format(sysfs_root, device_name))

        return Device(inner)

    def get_connected_devices(self) -> Dict[str, Tuple[int, int, int, int]]:
        device_map = {}
        for monitored_device in self.__root_devices:
            for device in monitored_device.devices_of_interest():
                self.__options.print_verbose("Found at startup: {0.device_path}".format(device))
                dev_map = self.__domain.find_device_mapping(device.sys_name)
                if dev_map is None:
                    dev_map = self.__domain.attach_device_to_xen(device)
                if dev_map is not None:
                    device_map[device.sys_name] = dev_map
        return device_map

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
                if device.is_a_device_we_care_about(self.__root_devices):
                    if device.sys_name not in device_map:
                        self.__options.print_verbose("Device added: {0}".format(device))
                        dev_map = self.__domain.attach_device_to_xen(device)
                        if dev_map is not None:
                            device_map[device.sys_name] = dev_map
            elif device.action == "remove" and device.sys_name in device_map:
                self.__options.print_verbose("Removing device: {0}".format(device))
                if self.__domain.detach_device_from_xen(device_map[device.sys_name]):
                    del device_map[device.sys_name]

    def __init__(self, opts: Options, xen_domain: 'XenDomain'):
        self.__context = pyudev.Context()
        self.__root_devices = [self.__get_device(x) for x in opts.hubs]
        self.__options = opts
        self.__domain = xen_domain

        for d in self.__root_devices:
            if not d.is_a_root_device():
                raise RuntimeError("Device {0} is not a root device node".format(d.sys_name))
            if not d.is_a_hub():
                raise RuntimeError("Device {0} is not a hub".format(d.sys_name))
