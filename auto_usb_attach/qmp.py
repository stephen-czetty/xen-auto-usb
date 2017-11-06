import json
import socket
from typing import Dict, Optional

from .options import Options


class Qmp:
    def __connect_to_qmp(self, sock: socket.socket) -> Dict[str, ...]:
        self.__options.print_very_verbose("Connecting to QMP")
        sock.connect(self.__path)
        greeting = sock.makefile().readline()
        self.__options.print_very_verbose(greeting)
        return json.loads(greeting)

    def __send_on_socket(self, sock: socket.socket, data: str) -> Dict[str, ...]:
        self.__options.print_very_verbose(data)
        sock.send(data.encode())
        result = sock.makefile().readline()
        self.__options.print_very_verbose(result)
        return json.loads(result)

    def __open_socket_and_connect(self) -> Optional[socket]:
        # noinspection PyUnresolvedReferences
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.__connect_to_qmp(sock)
        result = self.__send_on_socket(sock, json.dumps({"execute": "qmp_capabilities"}))

        return None if "error" in result else sock

    def __send_qmp_command(self, qmp_socket: socket, command: str, arguments: Dict[str, str]) -> Dict[str, ...]:
            return self.__send_on_socket(qmp_socket, json.dumps({"execute": command, "arguments": arguments}))

    def attach_usb_device(self, busnum: int, devnum: int, controller: int, port: int) -> bool:
        with self.__open_socket_and_connect() as qmp_socket:
            if qmp_socket is None:
                return False

            result = self.__send_qmp_command(qmp_socket, "device_add",
                                             {"id": "xenusb-{0}-{1}".format(busnum, devnum),
                                              "driver": "usb-host",
                                              "bus": "xenusb-{0}.0".format(controller),
                                              "port": "{0}".format(port),
                                              "hostbus": "{0}".format(busnum),
                                              "hostaddr": "{0}".format(devnum)}
                                             )
            return "error" not in result

    def detach_usb_device(self, busnum: int, devnum: int) -> bool:
        with self.__open_socket_and_connect() as qmp_socket:
            if qmp_socket is None:
                return False

            result = self.__send_qmp_command(qmp_socket, "device_del", {"id": "xenusb-{0}-{1}".format(busnum, devnum)})
            return "error" not in result

    def __init__(self, path: str, options: Options):
        self.__options = options
        self.__path = path


# QMP commands to look at that might get us the missing information for devices already attached at startup.
# {"execute": "qom-list", "arguments":{"path": "peripheral"}}
# {"return": [..., {"name": "xenusb-4-5", "type": "child<usb-host>"}, {"name": "xenusb-0", "type": "child<nec-usb-xhci>"}, {"name": "xenusb-3-6", "type": "child<usb-host>"}, {"name": "xenusb-3-4", "type": "child<usb-host>"},...]}
# {"execute": "qom-list", "arguments":{"path": "xenusb-0"}}
# {"return": [..., {"name": "xenusb-0.0", "type": "child<usb-bus>"},...]
# {"execute": "qom-list", "arguments": {"path": "xenusb-0.0"}}
# {"return": [{"name": "realized", "type": "bool"}, {"name": "child[15]", "type": "link<usb-host>"}, {"name": "type", "type": "string"}, {"name": "hotplug-handler", "type": "link<hotplug-handler>"}, {"name": "child[14]", "type": "link<usb-host>"}]}
# {"execute": "qom-get", "arguments": {"path": "xenusb-0.0", "property": "child[15]"}}
# {"return": "/machine/peripheral/xenusb-4-3"}
# {"execute": "qom-list", "arguments": {"path": "/machine/peripheral/xenusb-4-3"}}
# {"return": [{"name": "isobufs", "type": "uint32"}, {"name": "hostaddr", "type": "uint32"}, {"name": "hotpluggable", "type": "bool"}, {"name": "msos-desc", "type": "bool"}, {"name": "productid", "type": "uint32"}, {"name": "serial", "type": "str"}, {"name": "bootindex", "type": "int32"}, {"name": "isobsize", "type": "uint32"}, {"name": "parent_bus", "type": "link<bus>"}, {"name": "hotplugged", "type": "bool"}, {"name": "port", "type": "str"}, {"name": "vendorid", "type": "uint32"}, {"name": "pipeline", "type": "bool"}, {"name": "attached", "type": "bool"}, {"name": "hostport", "type": "str"}, {"name": "type", "type": "string"}, {"name": "full-path", "type": "bool"}, {"name": "loglevel", "type": "uint32"}, {"name": "realized", "type": "bool"}, {"name": "hostbus", "type": "uint32"}]}
# {"execute": "qom-get", "arguments":{"path": "xenusb-4-3", "property": "port"}}
# {"return": "2"}
# {"execute": "qom-get", "arguments": {"path": "xenusb-4-3", "property": "hostbus"}}
# {"return": 4}
