#!/usr/bin/env /usr/bin/python3.6

import sys
from functools import partial
from typing import List, Dict
import os
import asyncio

import psutil
from pyxs import PyXSError

from auto_usb_attach.qmp import Qmp
from .options import Options
from .xendomain import XenDomain, XenError
from .devicemonitor import DeviceMonitor
from .device import Device
from .xenusb import XenUsb


class MainThread:
    async def __add_device(self, domain: XenDomain, device: Device) -> None:
        self.__options.print_debug("add_device event fired: {}".format(device))
        if device.sys_name not in self.__device_map:
            self.__options.print_verbose("Device added: {}".format(device.device_path))

            try:
                dev_map = await domain.attach_device_to_xen(device)
                with (await self.__device_map_lock):
                    self.__device_map[device.sys_name] = dev_map
            except XenError:
                pass

    async def __remove_device(self, domain: XenDomain, device: Device) -> None:
        self.__options.print_debug("remove_device event fired: {}".format(device))
        if device.sys_name in self.__device_map:
            self.__options.print_verbose("Removing device: {}".format(device.device_path))
            if await domain.detach_device_from_xen(self.__device_map[device.sys_name]):
                with (await self.__device_map_lock):
                    del self.__device_map[device.sys_name]

    async def __restart_program(self):
        if self.__options.wrapper_name is None:
            self.__options.print_unless_quiet("No setuid wrapper found, cannot restart.  Exiting instead.")
            return

        self.__options.print_very_verbose("sleeping for 5 seconds to allow domain to shut down")
        await asyncio.sleep(5.0)

        self.__options.print_unless_quiet("Restarting.")

        # Adapted from https://stackoverflow.com/a/33334183
        p = psutil.Process(os.getpid())
        for handler in p.open_files() + p.connections():
            os.close(handler.fd)

        os.execl(self.__options.wrapper_name, *sys.argv)

    async def __domain_reboot(self, domain: XenDomain, monitor: DeviceMonitor) -> None:
        self.__options.print_very_verbose("domain_reboot event fired on domain {}".format(domain.domain_id))
        await self.__restart_program()
        monitor.shutdown()

    async def __domain_shutdown(self, domain: XenDomain, monitor: DeviceMonitor) -> None:
        self.__options.print_very_verbose("domain_shutdown event fired on domain {}".format(domain.domain_id))
        if self.__options.wait_on_shutdown:
            await self.__restart_program()

        monitor.shutdown()

    def __drop_privileges(self):
        ruid = int(os.getuid() or os.environ.get("SUDO_UID") or 0)
        self.__options.print_debug("Original uid: {}".format(ruid))
        os.setreuid(ruid, ruid)
        self.__options.print_debug("New euid: {}".format(os.geteuid()))

    @staticmethod
    async def __remove_disconnected_devices(domain: XenDomain, devices: List[XenUsb]):
        async for dev in domain.get_attached_devices():
            if dev not in devices:
                await domain.detach_device_from_xen(dev)

    def run(self) -> None:
        qmp = Qmp(self.__options)

        async def usb_monitor() -> None:
            with await XenDomain.wait_for_domain(self.__options, qmp) as xen_domain:
                if xen_domain is None:
                    return

                if self.__options.qmp_socket is None:
                    qmp.set_socket_path("/run/xen/qmp-libxl-{}".format(xen_domain.domain_id))
                else:
                    await qmp.is_connected.wait()

                monitor = DeviceMonitor(self.__options, xen_domain)
                monitor.device_added += partial(self.__add_device, xen_domain)
                monitor.device_removed += partial(self.__remove_device, xen_domain)
                qmp.domain_reboot += partial(self.__domain_reboot, xen_domain, monitor)
                qmp.domain_shutdown += partial(self.__domain_shutdown, xen_domain, monitor)

                if self.__options.qmp_socket is not None:
                    self.__drop_privileges()

                while True:
                    try:
                        with (await self.__device_map_lock):
                            for h in self.__options.hubs:
                                self.__device_map.update(await monitor.add_hub(h))
                            for d in self.__options.specific_devices:
                                self.__device_map.update(await monitor.add_specific_device(d))
                            await self.__remove_disconnected_devices(xen_domain, list(self.__device_map.values()))
                            break
                    except PyXSError:
                        await asyncio.sleep(1.0)

                try:
                    await monitor.monitor_devices()
                    return
                except KeyboardInterrupt:
                    return

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
    main(sys.argv)
