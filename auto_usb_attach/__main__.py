#!/usr/bin/env /usr/bin/python3.6

import sys
from functools import partial
from typing import List, Dict
from threading import Lock, Thread

import asyncio

from .options import Options
from .xendomain import XenDomain, XenError
from .devicemonitor import DeviceMonitor
from .device import Device
from .xenusb import XenUsb


class MainThread(Thread):
    async def __do_add_device(self, domain: XenDomain, device: Device):
        self.__opts.print_very_verbose("Adding device: {}".format(device))
        if device.sys_name not in self.__device_map:
            self.__opts.print_verbose("Device added: {}".format(device))

            try:
                dev_map = await domain.attach_device_to_xen(device)
                with self.__device_map_lock:
                    self.__device_map[device.sys_name] = dev_map
            except XenError:
                pass

    async def add_device(self, domain: XenDomain, device: Device):
        self.__opts.print_very_verbose("Adding device {}".format(device))
        await self.__do_add_device(domain, device)

    async def __do_remove_device(self, domain: XenDomain, device: Device):
        if device.sys_name in self.__device_map:
            self.__opts.print_verbose("Removing device: {}".format(device))
            if await domain.detach_device_from_xen(self.__device_map[device.sys_name]):
                with self.__device_map_lock:
                    del self.__device_map[device.sys_name]

    async def remove_device(self, domain: XenDomain, device: Device):
        self.__opts.print_very_verbose("Removing device {}".format(device))
        await self.__do_remove_device(domain, device)

    @staticmethod
    async def remove_disconnected_devices(domain: XenDomain, devices: List[XenUsb]):
        async for dev in domain.get_attached_devices():
            if dev not in devices:
                await domain.detach_device_from_xen(dev)

    def run(self):
        async def callback():
            with XenDomain(self.__opts) as xen_domain:
                monitor = DeviceMonitor(self.__opts, xen_domain)
                monitor.device_added += partial(self.add_device, xen_domain)
                monitor.device_removed += partial(self.remove_device, xen_domain)

                try:
                    with self.__device_map_lock:
                        for h in self.__opts.hubs:
                            self.__device_map.update(await monitor.add_hub(h))
                        await self.remove_disconnected_devices(xen_domain, list(self.__device_map.values()))

                    await monitor.monitor_devices()
                except KeyboardInterrupt:
                    pass

        self.__event_loop.run_until_complete(callback())
        self.__event_loop.close()

    def __init__(self, args):
        super().__init__()
        self.__args = args
        self.__opts = Options(args)
        self.__device_map: Dict[str, XenUsb] = {}
        self.__device_map_lock = Lock()
        self.__event_loop = asyncio.get_event_loop()

    def __repr__(self):
        return "MainThread({!r})".format(self.__args)


def main(args: List[str]) -> None:
    MainThread(args).run()


if __name__ == "__main__":
    main(sys.argv[1:])
