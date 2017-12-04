import json
import asyncio
from typing import Dict, Optional, cast, Iterable, Any
from collections import AsyncIterable

from .options import Options
from .xenusb import XenUsb


class QmpSocket:
    async def __connect_to_qmp(self) -> Dict[str, Any]:
        if not self.__connected:
            self.__options.print_very_verbose("Connecting to QMP")
            self.__reader, self.__writer = await asyncio.open_unix_connection(self.__path)
            self.__connect_info = await self.receive_line()

            if "error" in self.__connect_info:
                raise QmpError(self.__connect_info)
            self.__connected = True
            await self.send(json.dumps({"execute": "qmp_capabilities"}))

        return self.__connect_info

    async def send(self, data: str) -> Dict[str, Any]:
        await self.__connect_to_qmp()
        self.__options.print_very_verbose(data)
        self.__writer.write(bytes(data, "utf-8"))
        return await self.receive_line()

    async def receive_line(self) -> Dict[str, Any]:
        data = await self.__reader.readline()
        data = str(data, "utf-8")
        self.__options.print_very_verbose(data)
        return json.loads(data)

    def close(self):
        self.__keep_open = False
        self.__exit__()

    def __init__(self, options: Options, path: str):
        self.__options = options
        self.__path = options.qmp_socket or path
        self.__keep_open = options.qmp_socket is not None
        self.__connected = False
        self.__reader = None
        self.__writer = None
        self.__connect_info = {}

    def __repr__(self):
        return "QmpSocket({!r}, {!r})".format(self.__options, self.__path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        if (not self.__keep_open or exc_type is not None) and self.__connected:
            self.__writer.close()
            self.__writer = None
            self.__reader = None
            self.__connected = False


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
    def __get_qmp_socket(self) -> QmpSocket:
        self.__qmp_socket = self.__qmp_socket or \
                            QmpSocket(self.__options, self.__path)
        return self.__qmp_socket

    @staticmethod
    async def __send_qmp_command(sock: QmpSocket, command: str, arguments: Dict[str, str]) -> Dict[str, Any]:
        return await sock.send(json.dumps({"execute": command, "arguments": arguments}))

    async def __qom_list(self, sock: QmpSocket, path: str) -> Iterable[Dict[str, str]]:
        result = await self.__send_qmp_command(sock, "qom-list", {"path": path})
        if "error" in result:
            raise QmpError(result["error"])

        return cast(Iterable[Dict[str, str]], result["return"])

    async def __qom_get(self, sock: QmpSocket, path: str, property_name: str) -> Any:
        result = await self.__send_qmp_command(sock, "qom-get", {"path": path, "property": property_name})
        if "error" in result:
            raise QmpError(result["error"])

        return result["return"]

    async def __get_usb_controller_ids(self, sock: QmpSocket) -> AsyncIterable:
        controllers = await self.__qom_list(sock, "peripheral")
        if controllers is None:
            return

        controller_types = {"child<piix3-usb-uhci>": 1,
                            "child<usb-ehci>": 2,
                            "child<nec-usb-xhci>": 3}
        for dev in (d for d in controllers if cast(str, d["type"]) in controller_types):
            yield int(cast(str, dev["name"]).split("-")[1])

    async def __get_usb_devices(self, sock: QmpSocket, controller: int) -> AsyncIterable:
        controller_devices = await self.__qom_list(sock, "xenusb-{}.0".format(controller))
        if controller_devices is None:
            return

        for dev in (d for d in controller_devices if cast(str, d["type"]) == "link<usb-host>"):
            dev_path = await self.__qom_get(sock, "xenusb-{}.0".format(controller), dev["name"])
            if dev_path is None:
                continue

            port = await self.__qom_get(sock, dev_path, "port")
            if port is None:
                continue

            hostbus = await self.__qom_get(sock, dev_path, "hostbus")
            hostaddr = await self.__qom_get(sock, dev_path, "hostaddr")

            yield XenUsb(controller, int(port), int(hostbus), int(hostaddr))

    async def attach_usb_device(self, busnum: int, devnum: int, controller: int, port: int) -> None:
        with self.__get_qmp_socket() as sock:
            result = await self.__send_qmp_command(sock, "device_add",
                                                   {"id": "xenusb-{}-{}".format(busnum, devnum),
                                                    "driver": "usb-host",
                                                    "bus": "xenusb-{}.0".format(controller),
                                                    "port": str(port),
                                                    "hostbus": str(busnum),
                                                    "hostaddr": str(devnum)}
                                                   )
            if "error" in result:
                raise QmpError(result["error"])

    async def detach_usb_device(self, busnum: int, devnum: int) -> None:
        with self.__get_qmp_socket() as sock:
            result = await self.__send_qmp_command(sock, "device_del", {"id": "xenusb-{}-{}".format(busnum, devnum)})

            if "error" in result:
                raise QmpError(result["error"])

    async def get_usb_host(self, controller: int, port: int) -> Optional[XenUsb]:
        with self.__get_qmp_socket() as sock:
            controller_devices = await self.__qom_list(sock, "xenusb-{}.0".format(controller))
            if controller_devices is None:
                return None

            async for u in self.__get_usb_devices(sock, controller):
                if u.port == port:
                    return u
            # return anext((u async for u in self.__get_usb_devices(sock, controller) if u.port == port), None)
            return None

    async def get_usb_devices(self) -> AsyncIterable:
        with self.__get_qmp_socket() as sock:
            async for controller_id in self.__get_usb_controller_ids(sock):
                async for usb_dev in self.__get_usb_devices(sock, controller_id):
                    yield usb_dev

    def __init__(self, path: str, options: Options):
        super().__init__()
        self.__options = options
        self.__path = self.__options.qmp_socket or path
        self.__qmp_socket = None

    def __repr__(self):
        return "Qmp({!r}, {!r})".format(self.__path, self.__options)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.__qmp_socket is not None:
            self.__qmp_socket.close()


class QmpError(Exception):
    @property
    def error_class(self):
        return self.__error_class

    @property
    def message(self):
        return self.__message

    def __repr__(self):
        return "QmpError({!r})".format({"class": self.__error_class, "desc": self.__message})

    def __str__(self):
        return "{}: {}".format(self.__error_class, self.__message)

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

# For adding a chardev at runtime:
# {"execute": "chardev-add", "arguments": {"id": "test", "backend": {"type": "socket", "data": { "addr": {"data": {"path": "/var/run/xen/qmp-test"}, "type": "unix"}}, "server": true, "wait": false}}}
# I don't (yet) see a way to tell qmp to put this chardev into "mode=control" as done on the commandline.
