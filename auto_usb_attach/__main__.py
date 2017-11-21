#!/usr/bin/env /usr/bin/python3.6

import sys
from functools import partial
from typing import List, Dict
from threading import Lock

from .options import Options
from .xendomain import XenDomain, XenError
from .devicemonitor import DeviceMonitor
from .device import Device
from .xenusb import XenUsb

opts = None
device_map = {}
device_map_lock = Lock()


def add_device(domain: XenDomain, device: Device):
    if device.sys_name not in device_map:
        opts.print_verbose("Device added: {0}".format(device))

        try:
            dev_map = domain.attach_device_to_xen(device)
            with device_map_lock:
                device_map[device.sys_name] = dev_map
        except XenError:
            pass


def remove_device(domain: XenDomain, device: Device):
    if device.sys_name in device_map:
        opts.print_verbose("Removing device: {0}".format(device))
        if domain.detach_device_from_xen(device_map[device.sys_name]):
            with device_map_lock:
                del device_map[device.sys_name]


def remove_disconnected_devices(domain: XenDomain, devices: Dict[str, XenUsb]):
    for dev in list(domain.get_attached_devices()):
        if dev not in devices.values():
            domain.detach_device_from_xen(dev)


def main(args: List[str]) -> None:
    global opts, device_map
    opts = Options(args)

    with XenDomain(opts) as xen_domain:
        monitor = DeviceMonitor(opts, xen_domain)
        for h in opts.hubs:
            monitor.add_monitored_device(h)

        monitor.device_added += partial(add_device, xen_domain)
        monitor.device_removed += partial(remove_device, xen_domain)

        try:
            with device_map_lock:
                device_map = monitor.get_connected_devices(xen_domain)
                remove_disconnected_devices(xen_domain, device_map)
            monitor.monitor_devices()
            monitor.wait()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main(sys.argv[1:])
