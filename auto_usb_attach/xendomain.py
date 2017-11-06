from functools import partial
from typing import Tuple, Optional, Callable, Iterator
import pyxs
import re

from .device import Device
from .options import Options
from .qmp import Qmp

# There is a bug in the latest version of pyxs.
# There is a pending PR for it: https://github.com/selectel/pyxs/pull/13
# In the meantime, this should fix it.
pyxs.client._re_7bit_ascii = re.compile(b"^[\x00\x20-\x7f]*$")


# The C++ code to do this in xl can be found at:
# https://xenbits.xen.org/gitweb/?p=xen.git;a=blob_plain;f=tools/libxl/libxl_usb.c;hb=HEAD
#   (libxl__device_usbdev_del_hvm) -- We should be able to do the ad
# https://xenbits.xen.org/gitweb/?p=xen.git;a=blob_plain;f=tools/libxl/libxl_qmp.c;hb=HEAD
#   (libxl__qmp_initialize, qmp_send, qmp_send_initialize)
#
# This stuff basically:
# 1) connects to a socket: /run/xen/qmp-libxl-{domain_id},
# 2) Uses the QMP protocol (https://wiki.qemu.org/Documentation/QMP) to control the VM.
#    a) QMP is basically JSON.  It looks like we'll need to do:
#        i)  { "execute": "qmp_capabilities" }
#        ii) { "execute": "device_del", "arguments": { "id": "xenusb-{busnum}-{devnum}" } }"
#            (where busnum and devnum are the *old* locations)
# 3) Manually remove xenstore entry after this operation, if it is successful (actually, libxl removes it first,
#    and puts the entry back if it failed) (libxl__device_usbdev_remove_xenstore)
# 4) libxl rebinds the device to the driver, but since it has been removed, we won't need to do that.
class XenDomain:
    @staticmethod
    def __get_domain_id(name: str) -> int:
        with pyxs.Client() as c:
            for domain_id in XenDomain.__get_xs_list(c, "/local/domain"):
                path = "/local/domain/{0}/name".format(domain_id)
                if XenDomain.__get_xs_value(c, path) == name:
                    return int(domain_id)
            raise NameError("Could not find domain {0}".format(name))

    @staticmethod
    def __set_xs_value(xs_client: pyxs.Client, xs_path: str, xs_value: str) -> None:
        xs_client[bytes(xs_path, "ascii")] = bytes(xs_value, "ascii")

    @staticmethod
    def __get_xs_list(xs_client: pyxs.Client, xs_path: str) -> Iterator[str]:
        return (_.decode("ascii") for _ in xs_client.list(bytes(xs_path, "ascii")))

    @staticmethod
    def __get_xs_value(xs_client: pyxs.Client, xs_path: str) -> str:
        return xs_client[bytes(xs_path, "ascii")].decode("ascii")

    def __get_qmp_add_usb(self, busnum: int, devnum: int, controller: int, port: int) -> Callable[[], bool]:
        return partial(self.__qmp.attach_usb_device, busnum, devnum, controller, port)

    def __get_qmp_del_usb(self, busnum: int, devnum: int) -> Callable[[], bool]:
        return partial(self.__qmp.detach_usb_device, busnum, devnum)

    def __set_xenstore_and_send_command(self, xs_path: str, xs_value: str, qmp_command: Callable[[], bool]) -> bool:
        with pyxs.Client() as c:
            txn_id = c.transaction()
            try:
                XenDomain.__set_xs_value(c, xs_path, xs_value)

                if not qmp_command():
                    txn_id = None
                    c.rollback()
                    return False
            except pyxs.PyXSError as e:
                if txn_id is not None:
                    c.rollback()
                self.__options.print_unless_quiet(str(e))
                return False

            c.commit()

        return True

    def __find_next_open_controller_and_port(self) -> Tuple[int, int]:
        with pyxs.Client() as c:
            path = "/libxl/{0}/device/vusb".format(self.__domain_id)
            for controller in XenDomain.__get_xs_list(c, path):
                c_path = "{0}/{1}/port".format(path, controller)
                for port in XenDomain.__get_xs_list(c, c_path):
                    d_path = "{0}/{1}".format(c_path, port)
                    if XenDomain.__get_xs_value(c, d_path) == "":
                        self.__options.print_verbose("Choosing Controller {0}, Slot {1}"
                                                     .format(controller, port))
                        return int(controller), int(port)

    def attach_device_to_xen(self, dev: Device) -> Optional[Tuple[int, int, int, int]]:
        # Find an open controller and slot
        controller, port = self.__find_next_open_controller_and_port()

        # Add the entry to xenstore
        path = "/libxl/{0}/device/vusb/{1}/port/{2}".format(self.__domain_id, controller, port)
        busnum = dev.busnum
        devnum = dev.devnum

        if not self.__set_xenstore_and_send_command(path, dev.sys_name,
                                                    self.__get_qmp_add_usb(busnum, devnum, controller, port)):
            return None

        return controller, port, busnum, devnum

    def detach_device_from_xen(self, device_mapping: Tuple[int, int, int, int]) -> bool:
        if device_mapping[2] <= 0:
            # We don't have enough information to remove it.  Just leave things alone.
            return False

        path = "/libxl/{0}/device/vusb/{1}/port/{2}".format(self.__domain_id, device_mapping[0], device_mapping[1])
        return self.__set_xenstore_and_send_command(path, "", self.__get_qmp_del_usb(device_mapping[2],
                                                                                     device_mapping[3]))

    def find_device_mapping(self, sys_name: str) -> Optional[Tuple[int, int, int, int]]:
        with pyxs.Client() as c:
            path = "/libxl/{0}/device/vusb".format(self.__domain_id)
            for controller in XenDomain.__get_xs_list(c, path):
                c_path = "{0}/{1}/port".format(path, controller)
                for port in XenDomain.__get_xs_list(c, c_path):
                    d_path = "{0}/{1}".format(c_path, port)
                    if XenDomain.__get_xs_value(c, d_path) == sys_name:
                        (hostbus, hostaddr) = self.__qmp.get_usb_host_address(int(controller), int(port)) or -1, -1
                        self.__options.print_verbose("Controller {0}, Device {1}, HostBus {2}, HostAddress {3}"
                                                     .format(controller, port, hostbus, hostaddr))
                        return int(controller), int(port), hostbus, hostaddr
        return None

    def __init__(self, opts: Options):
        self.__domain_id = XenDomain.__get_domain_id(opts.domain)
        self.__options = opts
        self.__qmp = Qmp("/run/xen/qmp-libxl-{0}".format(self.__domain_id), opts)
