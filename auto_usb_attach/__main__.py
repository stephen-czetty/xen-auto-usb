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


def remove_disconnected_devices(domain: XenDomain, devices: List[XenUsb]):
    for dev in list(domain.get_attached_devices()):
        if dev not in devices:
            domain.detach_device_from_xen(dev)


def main(args: List[str]) -> None:
    global opts, device_map
    opts = Options(args)

    with XenDomain(opts) as xen_domain:
        with DeviceMonitor(opts, xen_domain) as monitor:
            monitor.device_added += partial(add_device, xen_domain)
            monitor.device_removed += partial(remove_device, xen_domain)

            try:
                with device_map_lock:
                    for h in opts.hubs:
                        device_map.update(monitor.add_hub(h))
                    remove_disconnected_devices(xen_domain, device_map.values())

                monitor.monitor_devices()
                monitor.wait()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main(sys.argv[1:])
