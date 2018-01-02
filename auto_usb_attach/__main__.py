#!/usr/bin/env /usr/bin/python3.6

import sys
from functools import partial
from typing import List, Dict

import asyncio

from auto_usb_attach.qmp import Qmp
from .options import Options
from .xendomain import XenDomain, XenError
from .devicemonitor import DeviceMonitor
from .device import Device
from .xenusb import XenUsb


class MainThread:
    async def add_device(self, domain: XenDomain, device: Device):
        self.__options.print_debug("add_device event fired: {}".format(device))
        if device.sys_name not in self.__device_map:
            self.__options.print_verbose("Device added: {}".format(device.device_path))

            try:
                dev_map = await domain.attach_device_to_xen(device)
                with (await self.__device_map_lock):
                    self.__device_map[device.sys_name] = dev_map
            except XenError:
                pass

    async def remove_device(self, domain: XenDomain, device: Device):
        self.__options.print_debug("remove_device event fired: {}".format(device))
        if device.sys_name in self.__device_map:
            self.__options.print_verbose("Removing device: {}".format(device.device_path))
            if await domain.detach_device_from_xen(self.__device_map[device.sys_name]):
                with (await self.__device_map_lock):
                    del self.__device_map[device.sys_name]

    async def domain_reboot(self, domain: XenDomain):
        self.__options.print_very_verbose("domain_reboot event fired on domain {}".format(domain.domain_id))

    async def domain_shutdown(self, domain: XenDomain):
        self.__options.print_very_verbose("domain_shutdown event fired on domain {}".format(domain.domain_id))

    @staticmethod
    async def remove_disconnected_devices(domain: XenDomain, devices: List[XenUsb]):
        async for dev in domain.get_attached_devices():
            if dev not in devices:
                await domain.detach_device_from_xen(dev)

    def run(self):
        qmp = Qmp(self.__options)

        async def usb_monitor():
            with await XenDomain.wait_for_domain(self.__options, qmp) as xen_domain:
                if xen_domain is None:
                    return

                if self.__options.qmp_socket is None:
                    qmp.set_socket_path("/run/xen/qmp-libxl-{}".format(xen_domain.domain_id))

                monitor = DeviceMonitor(self.__options, xen_domain)
                monitor.device_added += partial(self.add_device, xen_domain)
                monitor.device_removed += partial(self.remove_device, xen_domain)
                qmp.domain_reboot += partial(self.domain_reboot, xen_domain)
                qmp.domain_shutdown += partial(self.domain_shutdown, xen_domain)

                try:
                    with (await self.__device_map_lock):
                        for h in self.__options.hubs:
                            self.__device_map.update(await monitor.add_hub(h))
                        for d in self.__options.specific_devices:
                            self.__device_map.update(await monitor.add_specific_device(d))
                        await self.remove_disconnected_devices(xen_domain, list(self.__device_map.values()))

                    await monitor.monitor_devices()
                except KeyboardInterrupt:
                    pass

        try:
            if self.__options.qmp_socket is not None:
                asyncio.ensure_future(qmp.monitor_domain())
            self.__event_loop.run_until_complete(usb_monitor())
        except KeyboardInterrupt:
            pass

    def __init__(self, args):
        super().__init__()
        self.__args = args
        self.__options = Options(args)
        self.__device_map: Dict[str, XenUsb] = {}
        self.__device_map_lock = asyncio.Lock()
        self.__event_loop = asyncio.get_event_loop()

    def __repr__(self):
        return "MainThread({!r})".format(self.__args)


def main(args: List[str]) -> None:
    MainThread(args).run()


if __name__ == "__main__":
    main(sys.argv[1:])
