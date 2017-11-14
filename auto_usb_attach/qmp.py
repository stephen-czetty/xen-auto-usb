import json
import socket
from typing import Dict, Optional, cast, Iterable, Any

from .options import Options
from .xenusb import XenUsb


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
class Qmp:
    def __connect_to_qmp(self, sock: socket.socket) -> Dict[str, Any]:
        self.__options.print_very_verbose("Connecting to QMP")
        sock.connect(self.__path)
        greeting = sock.makefile().readline()
        self.__options.print_very_verbose(greeting)
        return json.loads(greeting)

    def __send_on_socket(self, sock: socket.socket, data: str) -> Dict[str, Any]:
        self.__options.print_very_verbose(data)
        sock.send(data.encode())
        result = sock.makefile().readline()
        self.__options.print_very_verbose(result)
        return json.loads(result)

    def __get_qmp_socket(self) -> socket.socket:
        # noinspection PyUnresolvedReferences
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.__connect_to_qmp(sock)
        result = self.__send_on_socket(sock, json.dumps({"execute": "qmp_capabilities"}))

        if "error" in result:
            raise QmpError(result["error"])

        return sock

    def __send_qmp_command(self, qmp_socket: socket.socket, command: str, arguments: Dict[str, str]) -> Dict[str, Any]:
            return self.__send_on_socket(qmp_socket, json.dumps({"execute": command, "arguments": arguments}))

    def __qom_list(self, qmp_socket: socket.socket, path: str) -> Iterable[Dict[str, str]]:
        result = self.__send_qmp_command(qmp_socket, "qom-list", {"path": path})
        if "error" in result:
            raise QmpError(result["error"])

        return cast(Iterable[Dict[str, str]], result["return"])

    def __qom_get(self, qmp_socket: socket.socket, path: str, property_name: str) -> Any:
        result = self.__send_qmp_command(qmp_socket, "qom-get", {"path": path,
                                                                 "property": property_name})
        if "error" in result:
            raise QmpError(result["error"])

        return result["return"]

    def __get_usb_controller_ids(self, qmp_socket: socket.socket) -> Iterable[int]:
        controllers = self.__qom_list(qmp_socket, "peripheral")
        if controllers is None:
            return

        controller_types = {"child<piix3-usb-uhci>": 1,
                            "child<usb-ehci>": 2,
                            "child<nec-usb-xhci>": 3}
        for dev in (d for d in controllers if cast(str, d["type"]) in controller_types):
            yield int(cast(str, dev["name"]).split("-")[1])

    def __get_usb_devices(self, qmp_socket: socket.socket, controller: int) -> Iterable[XenUsb]:
        controller_devices = self.__qom_list(qmp_socket, "xenusb-{0}.0".format(controller))
        if controller_devices is None:
            return

        for dev in (d for d in controller_devices if cast(str, d["type"]) == "link<usb-host>"):
            dev_path = self.__qom_get(qmp_socket, "xenusb-{0}.0".format(controller), dev["name"])
            if dev_path is None:
                continue

            port = self.__qom_get(qmp_socket, dev_path, "port")
            if port is None:
                continue

            hostbus = self.__qom_get(qmp_socket, dev_path, "hostbus")
            hostaddr = self.__qom_get(qmp_socket, dev_path, "hostaddr")

            yield XenUsb(controller, int(port), int(hostbus), int(hostaddr))

    def attach_usb_device(self, busnum: int, devnum: int, controller: int, port: int) -> None:
        with self.__get_qmp_socket() as qmp_socket:
            result = self.__send_qmp_command(qmp_socket, "device_add",
                                             {"id": "xenusb-{0}-{1}".format(busnum, devnum),
                                              "driver": "usb-host",
                                              "bus": "xenusb-{0}.0".format(controller),
                                              "port": "{0}".format(port),
                                              "hostbus": "{0}".format(busnum),
                                              "hostaddr": "{0}".format(devnum)}
                                             )
            if "error" in result:
                raise QmpError(result["error"])

    def detach_usb_device(self, busnum: int, devnum: int) -> None:
        with self.__get_qmp_socket() as qmp_socket:
            result = self.__send_qmp_command(qmp_socket, "device_del", {"id": "xenusb-{0}-{1}".format(busnum, devnum)})

            if "error" in result:
                raise QmpError(result["error"])

    def get_usb_host(self, controller: int, port: int) -> Optional[XenUsb]:
        with self.__get_qmp_socket() as qmp_socket:
            controller_devices = self.__qom_list(qmp_socket, "xenusb-{0}.0".format(controller))
            if controller_devices is None:
                return None

            return next((u for u in self.__get_usb_devices(qmp_socket, controller) if u.port == port), None)

    def get_usb_devices(self) -> Iterable[str]:
        with self.__get_qmp_socket() as qmp_socket:
            for controller_id in self.__get_usb_controller_ids(qmp_socket):
                for dev_path in self.__get_usb_devices(qmp_socket, controller_id):
                    yield dev_path

    def __init__(self, path: str, options: Options):
        self.__options = options
        self.__path = path


class QmpError(Exception):
    @property
    def error_class(self):
        return self.__error_class

    @property
    def message(self):
        return self.__message

    def __repr__(self):
        return "{0}: {1}".format(self.__error_class, self.__message)

    def __init__(self, error: Dict[str, str]):
        self.__error_class = error["class"]
        self.__message = error["desc"]


# QMP commands to look at that might get us the missing information for devices already attached at startup.
# {"execute": "qom-list", "arguments":{"path": "peripheral"}}
# {"return": [{"name": "xenusb-4-5", "type": "child<usb-host>"}, {"name": "xenusb-0", "type": "child<nec-usb-xhci>"}, ...]}
# {"execute": "qom-list", "arguments":{"path": "xenusb-0"}}
# {"return": [{"name": "xenusb-0.0", "type": "child<usb-bus>"},...]
# {"execute": "qom-list", "arguments": {"path": "xenusb-0.0"}}
# {"return": [{"name": "child[15]", "type": "link<usb-host>"}, {"name": "child[14]", "type": "link<usb-host>"}, ...]}
# {"execute": "qom-get", "arguments": {"path": "xenusb-0.0", "property": "child[15]"}}
# {"return": "/machine/peripheral/xenusb-4-3"}
# {"execute": "qom-list", "arguments": {"path": "/machine/peripheral/xenusb-4-3"}}
# {"return": [{"name": "hostaddr", "type": "uint32"}, {"name": "parent_bus", "type": "link<bus>"}, {"name": "port", "type": "str"}, {"name": "hostbus", "type": "uint32"}, ...]}
# {"execute": "qom-get", "arguments":{"path": "xenusb-4-3", "property": "port"}}
# {"return": "2"}
# {"execute": "qom-get", "arguments": {"path": "xenusb-4-3", "property": "hostbus"}}
# {"return": 4}
# {"execute": "qom-get", "arguments":{"path": "xenusb-3-4", "property": "parent_bus"}}
# {"return": "/machine/peripheral/xenusb-0/xenusb-0.0"}

