#!/usr/bin/env /usr/bin/python3.6

# xenstore paths of interest:
# /local/domain/* -- List of running domains (0, 1, etc.)
# /local/domain/*/name -- Names of the domains
# /libxl/*/device/vusb/* -- Virtual USB controllers
# /libxl/*/device/vusb/*/port/* -- Mapped ports (look up in /sys/bus/usb/devices)
import sys
from functools import partial
from typing import List, Dict, Tuple

from .options import Options
from .xendomain import XenDomain
from .devicemonitor import DeviceMonitor
from .device import Device

opts = None
device_map = {}


def add_device(domain: XenDomain, root_devices: List[Device], device: Device):
    if device.is_a_device_we_care_about(root_devices):
        if device.sys_name not in device_map:
            opts.print_verbose("Device added: {0}".format(device))
            dev_map = domain.attach_device_to_xen(device)
            if dev_map is not None:
                device_map[device.sys_name] = dev_map


def remove_device(domain: XenDomain, device: Device):
    if device.sys_name in device_map:
        opts.print_verbose("Removing device: {0}".format(device))
        if domain.detach_device_from_xen(device_map[device.sys_name]):
            del device_map[device.sys_name]


def get_connected_devices(domain: XenDomain, root_devices: List[Device]) -> Dict[str, Tuple[int, int, int, int]]:
    for monitored_device in root_devices:
        for device in monitored_device.devices_of_interest():
            opts.print_verbose("Found at startup: {0.device_path}".format(device))
            dev_map = domain.find_device_mapping(device.sys_name)
            if dev_map is None:
                dev_map = domain.attach_device_to_xen(device)
            if dev_map is not None:
                device_map[device.sys_name] = dev_map
    return device_map


def main(args: List[str]) -> None:
    global opts, device_map
    opts = Options(args)

    xen_domain = XenDomain(opts)

    monitor = DeviceMonitor(opts, xen_domain)
    root_devices = [monitor.add_monitored_device(x) for x in opts.hubs]
    monitor.device_added += partial(add_device, xen_domain, root_devices)
    monitor.device_removed += partial(remove_device, xen_domain)

    try:
        device_map = get_connected_devices(xen_domain, root_devices)
        monitor.monitor_devices(device_map)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
