from typing import Dict, Tuple, Optional
import pyxs
import re
import socket
import json

from .device import Device
from .options import Options

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
    def __set_xs_value(xs_client, xs_path, xs_value):
        xs_client[bytes(xs_path, "ascii")] = bytes(xs_value, "ascii")

    @staticmethod
    def __get_xs_list(xs_client, xs_path):
        return (_.decode("ascii") for _ in xs_client.list(bytes(xs_path, "ascii")))

    @staticmethod
    def __get_xs_value(xs_client, xs_path):
        return xs_client[bytes(xs_path, "ascii")].decode("ascii")

    def __connect_to_qmp(self, sock: socket.socket) -> Dict:
        self.__options.print_very_verbose("Connecting to QMP")
        sock.connect("/run/xen/qmp-libxl-{0}".format(self.__domain_id))
        greeting = sock.makefile().readline()
        self.__options.print_very_verbose(greeting)
        return json.loads(greeting)

    def __send_on_socket(self, sock: socket.socket, data: str) -> Dict:
        self.__options.print_very_verbose(data)
        sock.send(data.encode())
        result = sock.makefile().readline()
        self.__options.print_very_verbose(result)
        return json.loads(result)

    def __send_qmp_command(self, command: str, arguments: Dict[str, str]) -> bool:
        # noinspection PyUnresolvedReferences
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as qmp_socket:
            self.__connect_to_qmp(qmp_socket)

            result = self.__send_on_socket(qmp_socket, json.dumps({"execute": "qmp_capabilities"}))
            if "error" in result:
                return False

            result = self.__send_on_socket(qmp_socket, json.dumps({"execute": command, "arguments": arguments}))

            return "error" not in result

    def __set_xenstore_and_send_qmp_command(self, xs_path: str, xs_value: str, qmp_command: str,
                                            qmp_arguments: Dict[str, str]) -> bool:
        with pyxs.Client() as c:
            txn_id = c.transaction()
            try:
                XenDomain.__set_xs_value(c, xs_path, xs_value)

                if not self.__send_qmp_command(qmp_command, qmp_arguments):
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

        if not self.__set_xenstore_and_send_qmp_command(path, dev.sys_name, "device_add",
                                                        {"id": "xenusb-{0}-{1}".format(busnum, devnum),
                                                         "driver": "usb-host",
                                                         "bus": "xenusb-{0}.0".format(controller),
                                                         "port": "{0}".format(port),
                                                         "hostbus": "{0}".format(busnum),
                                                         "hostaddr": "{0}".format(devnum)}):
            return None

        return controller, port, busnum, devnum

    def detach_device_from_xen(self, device_mapping: Tuple[int, int, int, int]) -> bool:
        if device_mapping[2] <= 0:
            # We don't have enough information to remove it.  Just leave things alone.
            # TODO: This is technically a bug, but will require some xenstore trickery to get right.
            return False

        path = "/libxl/{0}/device/vusb/{1}/port/{2}".format(self.__domain_id, device_mapping[0], device_mapping[1])
        return self.__set_xenstore_and_send_qmp_command(path, "", "device_del",
                                                        {"id": "xenusb-{0}-{1}".format(device_mapping[2],
                                                                                       device_mapping[3])})

    def find_device_mapping(self, sys_name: str) -> Optional[Tuple[int, int, int, int]]:
        with pyxs.Client() as c:
            path = "/libxl/{0}/device/vusb".format(self.__domain_id)
            for controller in XenDomain.__get_xs_list(c, path):
                c_path = "{0}/{1}/port".format(path, controller)
                for device in XenDomain.__get_xs_list(c, c_path):
                    d_path = "{0}/{1}".format(c_path, device)
                    if XenDomain.__get_xs_value(c, d_path) == sys_name:
                        self.__options.print_verbose("Controller {0}, Device {1}"
                                                     .format(controller, device))
                        return controller, device, -1, -1
        return None

    def __init__(self, opts: Options):
        self.__domain_id = XenDomain.__get_domain_id(opts.domain)
        self.__options = opts
