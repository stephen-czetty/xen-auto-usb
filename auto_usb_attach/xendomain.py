import asyncio
from functools import partial
from typing import Tuple, Optional, Callable, Iterable, List
from collections import AsyncIterable
import re
import pyxs

from .device import Device
from .options import Options
from .qmp import Qmp, QmpError
from .xenusb import XenUsb

# There is a bug in the latest version of pyxs.
# There is a pending PR for it: https://github.com/selectel/pyxs/pull/13
# In the meantime, this should fix it.
pyxs.client._re_7bit_ascii = re.compile(b"^[\x00\x20-\x7f]*$")


# xenstore paths of interest:
# /local/domain/* -- List of running domains (0, 1, etc.)
# /local/domain/*/name -- Names of the domains
# /libxl/*/device/vusb/* -- Virtual USB controllers
# /libxl/*/device/vusb/*/port/* -- Mapped ports (look up in /sys/bus/usb/devices)
class XenDomain:
    def __set_xs_value(self, xs_path: str, xs_value: str) -> None:
        self.__xs_client[bytes(xs_path, "ascii")] = bytes(xs_value, "ascii")

    def __get_xs_list(self, xs_path: str) -> Iterable[str]:
        return (_.decode("ascii") for _ in self.__xs_client.list(bytes(xs_path, "ascii")))

    def __get_xs_value(self, xs_path: str) -> str:
        return self.__xs_client[bytes(xs_path, "ascii")].decode("ascii")

    def __get_qmp_add_usb(self, busnum: int, devnum: int, controller: int, port: int) -> Callable[[], None]:
        return partial(self.__qmp.attach_usb_device, busnum, devnum, controller, port)

    def __get_qmp_del_usb(self, busnum: int, devnum: int) -> Callable[[], None]:
        return partial(self.__qmp.detach_usb_device, busnum, devnum)

    def __get_qmp_add_controller(self, controller: int) -> Callable[[], None]:
        return partial(self.__qmp.create_usb_controller, controller)

    async def __set_xenstore_and_send_command(self, xs_list: List[Tuple[str, str]],
                                              qmp_command: Callable[[], None]) -> None:
        txn_id = self.__xs_client.transaction()
        try:
            for xs_path, xs_value in xs_list:
                self.__set_xs_value(xs_path, xs_value)
            await qmp_command()
        except (pyxs.PyXSError, QmpError) as e:
            if txn_id is not None:
                self.__xs_client.rollback()
            self.__options.print_unless_quiet("Caught exception: {}".format(e))
            raise XenError(e)

        self.__xs_client.commit()

    async def __create_controller(self, controller: int) -> None:
        path = "/libxl/{}/device/vusb".format(self.__domain_id)
        num_ports = [2, 6, 15][self.__options.usb_version-1]
        xenstore_entries = [
            (path, ""),
            ("{}/{}".format(path, controller), ""),
            ("{}/{}/type".format(path, controller), "devicemodel"),
            ("{}/{}/usb-ver".format(path, controller), str(self.__options.usb_version)),
            ("{}/{}/num-ports".format(path, controller), str(num_ports)),
            ("{}/{}/port".format(path, controller), "")
        ]
        for port in range(1, num_ports+1):
            xenstore_entries.append(("{}/{}/port/{}".format(path, controller, port), ""))

        await self.__set_xenstore_and_send_command(xenstore_entries, self.__get_qmp_add_controller(controller))

    def __check_for_vusb(self) -> bool:
        path = "/libxl/{}/device".format(self.__domain_id)
        devices = self.__get_xs_list(path)
        return "vusb" in devices

    async def __find_next_open_controller_and_port(self) -> Tuple[int, int]:
        path = "/libxl/{}/device/vusb".format(self.__domain_id)
        last_controller = -1

        if self.__check_for_vusb():
            for controller in self.__get_xs_list(path):
                last_controller = int(controller)
                c_path = "{}/{}/port".format(path, controller)
                for port in self.__get_xs_list(c_path):
                    d_path = "{}/{}".format(c_path, port)
                    if self.__get_xs_value(d_path) == "":
                        self.__options.print_verbose("Choosing Controller {0}, Slot {1}"
                                                     .format(controller, port))
                        return int(controller), int(port)

        # Create a new controller
        new_controller = last_controller + 1
        self.__options.print_verbose("No available slot found, creating new controller id {}"
                                     .format(new_controller))
        await self.__create_controller(new_controller)
        self.__options.print_verbose("Choosing Controller {}, Slot 1".format(new_controller))
        return new_controller, 1

    @property
    def domain_id(self) -> Optional[int]:
        return self.__domain_id

    def get_domain_id(self, name: str) -> int:
        for domain_id in self.__get_xs_list("/local/domain"):
            path = "/local/domain/{}/name".format(domain_id)
            if self.__get_xs_value(path) == name:
                return int(domain_id)
        raise NameError("Could not find domain {}".format(name))

    @staticmethod
    async def wait_for_domain(opts: Options, qmp: Qmp) -> "XenDomain":
        while True:
            try:
                return XenDomain(opts, qmp)
            except NameError:
                if opts.no_wait:
                    opts.print_unless_quiet("Could not find domain {}, exiting.".format(opts.domain))
                    return XenDomain(None, qmp)

                opts.print_unless_quiet("Could not find domain {}, waiting 5 seconds...".format(opts.domain))
                await asyncio.sleep(5.0)

    async def attach_device_to_xen(self, dev: Device) -> XenUsb:
        # Find an open controller and slot
        controller, port = await self.__find_next_open_controller_and_port()

        # Add the entry to xenstore
        path = "/libxl/{}/device/vusb/{}/port/{}".format(self.__domain_id, controller, port)
        busnum = dev.busnum
        devnum = dev.devnum

        await self.__set_xenstore_and_send_command([(path, dev.sys_name)],
                                                   self.__get_qmp_add_usb(busnum, devnum, controller, port))

        return XenUsb(controller, port, busnum, devnum)

    async def detach_device_from_xen(self, device: XenUsb) -> bool:
        if device.hostaddr <= 0:
            # We don't have enough information to remove it.  Just leave things alone.
            self.__options.print_unless_quiet("WARN: Not enough information to automatically detach device at "
                                              "controller {}, port {}".format(device.controller, device.port))
            return False

        path = "/libxl/{}/device/vusb/{}/port/{}".format(self.__domain_id, device.controller, device.port)
        await self.__set_xenstore_and_send_command([(path, "")], self.__get_qmp_del_usb(device.hostbus,
                                                                                        device.hostaddr))

        return True

    async def find_device_mapping(self, sys_name: str) -> Optional[XenUsb]:
        if self.__check_for_vusb():
            path = "/libxl/{}/device/vusb".format(self.__domain_id)
            for controller in self.__get_xs_list(path):
                c_path = "{}/{}/port".format(path, controller)
                for port in self.__get_xs_list(c_path):
                    d_path = "{}/{}".format(c_path, port)
                    if self.__get_xs_value(d_path) == sys_name:
                        usb_host = await self.__qmp.get_usb_host(int(controller), int(port))
                        if usb_host is not None:
                            self.__options.print_verbose("Controller {}, Port {}, HostBus {}, HostAddress {}"
                                                         .format(usb_host.controller,
                                                                 usb_host.port,
                                                                 usb_host.hostbus,
                                                                 usb_host.hostaddr))
                        else:
                            self.__options.print_verbose("Device {} not found".format(sys_name))
                        return usb_host
        return None

    def get_attached_devices(self) -> AsyncIterable:
        return self.__qmp.get_usb_devices()

    def __init__(self, opts: Optional[Options], qmp: Qmp):
        self.__options = opts
        self.__qmp = qmp
        with pyxs.Client() as self.__xs_client:
            self.__domain_id = self.get_domain_id(self.__options.domain) if self.__options is not None else None
        self.__xs_client = pyxs.Client()

    def __repr__(self):
        return "XenDomain({!r}, {!r})".format(self.__options, self.__qmp)

    def __enter__(self):
        if self.__domain_id is None:
            return None

        self.__xs_client.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.__qmp is not None:
            self.__qmp.__exit__(exc_type, exc_val, exc_tb)
            self.__qmp = None

        self.__xs_client.close()


class XenError(Exception):
    @property
    def inner_exception(self):
        return self.__inner

    def __init__(self, inner: Exception):
        self.__inner = inner

    def __repr__(self):
        return "XenError({!r})".format(self.__inner)
