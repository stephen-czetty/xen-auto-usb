from functools import partial
from typing import Tuple, Optional, Callable, Iterable
import pyxs
import re

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
    @staticmethod
    def __get_domain_id(name: str) -> int:
        with pyxs.Client() as c:
            for domain_id in XenDomain.__get_xs_list(c, "/local/domain"):
                path = "/local/domain/{}/name".format(domain_id)
                if XenDomain.__get_xs_value(c, path) == name:
                    return int(domain_id)
            raise NameError("Could not find domain {}".format(name))

    @staticmethod
    def __set_xs_value(xs_client: pyxs.Client, xs_path: str, xs_value: str) -> None:
        xs_client[bytes(xs_path, "ascii")] = bytes(xs_value, "ascii")

    @staticmethod
    def __get_xs_list(xs_client: pyxs.Client, xs_path: str) -> Iterable[str]:
        return (_.decode("ascii") for _ in xs_client.list(bytes(xs_path, "ascii")))

    @staticmethod
    def __get_xs_value(xs_client: pyxs.Client, xs_path: str) -> str:
        return xs_client[bytes(xs_path, "ascii")].decode("ascii")

    def __get_qmp_add_usb(self, busnum: int, devnum: int, controller: int, port: int) -> Callable[[], None]:
        return partial(self.__qmp.attach_usb_device, busnum, devnum, controller, port)

    def __get_qmp_del_usb(self, busnum: int, devnum: int) -> Callable[[], None]:
        return partial(self.__qmp.detach_usb_device, busnum, devnum)

    async def __set_xenstore_and_send_command(self, xs_path: str, xs_value: str,
                                              qmp_command: Callable[[], None]) -> None:
        with pyxs.Client() as c:
            txn_id = c.transaction()
            try:
                XenDomain.__set_xs_value(c, xs_path, xs_value)
                await qmp_command()
            except (pyxs.PyXSError, QmpError) as e:
                if txn_id is not None:
                    c.rollback()
                self.__options.print_unless_quiet("Caught exception: {}".format(e))
                raise XenError(e)

            c.commit()

    def __find_next_open_controller_and_port(self) -> Tuple[int, int]:
        with pyxs.Client() as c:
            path = "/libxl/{}/device/vusb".format(self.__domain_id)
            for controller in XenDomain.__get_xs_list(c, path):
                c_path = "{}/{}/port".format(path, controller)
                for port in XenDomain.__get_xs_list(c, c_path):
                    d_path = "{}/{}".format(c_path, port)
                    if XenDomain.__get_xs_value(c, d_path) == "":
                        self.__options.print_verbose("Choosing Controller {0}, Slot {1}"
                                                     .format(controller, port))
                        return int(controller), int(port)

            raise XenError(Exception("No open device slot"))

    async def attach_device_to_xen(self, dev: Device) -> XenUsb:
        # Find an open controller and slot
        controller, port = self.__find_next_open_controller_and_port()

        # Add the entry to xenstore
        path = "/libxl/{}/device/vusb/{}/port/{}".format(self.__domain_id, controller, port)
        busnum = dev.busnum
        devnum = dev.devnum

        await self.__set_xenstore_and_send_command(path, dev.sys_name,
                                                   self.__get_qmp_add_usb(busnum, devnum, controller, port))

        return XenUsb(controller, port, busnum, devnum)

    async def detach_device_from_xen(self, device: XenUsb) -> bool:
        if device.hostaddr <= 0:
            # We don't have enough information to remove it.  Just leave things alone.
            self.__options.print_unless_quiet("WARN: Not enough information to automatically detach device at "
                                              "controller {}, port {}".format(device.controller, device.port))
            return False

        path = "/libxl/{}/device/vusb/{}/port/{}".format(self.__domain_id, device.controller, device.port)
        await self.__set_xenstore_and_send_command(path, "", self.__get_qmp_del_usb(device.hostbus,
                                                                                    device.hostaddr))

        return True

    async def find_device_mapping(self, sys_name: str) -> Optional[XenUsb]:
        with pyxs.Client() as c:
            path = "/libxl/{}/device/vusb".format(self.__domain_id)
            for controller in XenDomain.__get_xs_list(c, path):
                c_path = "{}/{}/port".format(path, controller)
                for port in XenDomain.__get_xs_list(c, c_path):
                    d_path = "{}/{}".format(c_path, port)
                    if XenDomain.__get_xs_value(c, d_path) == sys_name:
                        usb_host = await self.__qmp.get_usb_host(int(controller), int(port)) or (-1, -1)
                        self.__options.print_verbose("Controller {}, Port {}, HostBus {}, HostAddress {}"
                                                     .format(usb_host.controller,
                                                             usb_host.port,
                                                             usb_host.hostbus,
                                                             usb_host.hostaddr))
                        return usb_host
        return None

    async def get_attached_devices(self) -> Iterable[XenUsb]:
        return await self.__qmp.get_usb_devices()

    def __init__(self, opts: Options):
        self.__domain_id = XenDomain.__get_domain_id(opts.domain)
        self.__options = opts

    def __repr__(self):
        return "XenDomain({!r})".format(self.__options)

    def __enter__(self):
        self.__qmp = Qmp("/run/xen/qmp-libxl-{}".format(self.__domain_id), self.__options)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.__qmp is not None:
            self.__qmp.__exit__(exc_type, exc_val, exc_tb)
            self.__qmp = None


class XenError(Exception):
    @property
    def inner_exception(self):
        return self.__inner

    def __init__(self, inner: Exception):
        self.__inner = inner

    def __repr__(self):
        return "XenError({!r})".format(self.__inner)
