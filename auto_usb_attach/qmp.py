import json
import socket
from typing import Dict, Optional, Tuple, cast, Iterable, Any

from .options import Options


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

    def __open_socket_and_connect(self) -> Optional[socket.socket]:
        # noinspection PyUnresolvedReferences
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.__connect_to_qmp(sock)
        result = self.__send_on_socket(sock, json.dumps({"execute": "qmp_capabilities"}))

        return None if "error" in result else sock

    def __send_qmp_command(self, qmp_socket: socket, command: str, arguments: Dict[str, str]) -> Dict[str, Any]:
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

    def get_usb_host_address(self, controller: int, port: int) -> Optional[Tuple[int, int]]:
        with self.__open_socket_and_connect() as qmp_socket:
            if qmp_socket is None:
                return None

            result = self.__send_qmp_command(qmp_socket, "qom-list", {"path": "xenusb-{0}.0".format(controller)})
            if "error" in result:
                return None

            for dev in (d for d in cast(Iterable, result["return"]) if cast(str, d["type"]) == "link<usb-host>"):
                dev_result = self.__send_qmp_command(qmp_socket, "qom-get", {"path": "xenusb-{0}.0".format(controller),
                                                                             "property": dev["name"]})
                if "error" in dev_result:
                    continue

                port_result = self.__send_qmp_command(qmp_socket, "qom-get", {"path": dev_result["return"],
                                                                              "property": "port"})
                if "error" in port_result:
                    continue
                if int(port_result["return"]) != port:
                    continue

                path = dev_result["return"]
                dev_result = self.__send_qmp_command(qmp_socket, "qom-get", {"path": path,
                                                                             "property": "hostbus"})
                if "error" in dev_result:
                    return None
                hostbus = int(dev_result["return"])

                dev_result = self.__send_qmp_command(qmp_socket, "qom-get", {"path": path,
                                                                             "property": "hostaddr"})
                if "error" in dev_result:
                    return None
                hostaddr = int(dev_result["return"])

                return hostbus, hostaddr

            return None

    def __init__(self, path: str, options: Options):
        self.__options = options
        self.__path = path


# QMP commands to look at that might get us the missing information for devices already attached at startup.
# {"execute": "qom-list", "arguments":{"path": "peripheral"}}
# {"return": [{"name": "xenusb-4-5", "type": "child<usb-host>"}, {"name": "xenusb-0", "type": "child<nec-usb-xhci>"}, {"name": "xenusb-3-6", "type": "child<usb-host>"}, {"name": "xenusb-3-4", "type": "child<usb-host>"},...]}
# {"execute": "qom-list", "arguments":{"path": "xenusb-0"}}
# {"return": [..., {"name": "xenusb-0.0", "type": "child<usb-bus>"},...]
# {"execute": "qom-list", "arguments": {"path": "xenusb-0.0"}}
# {"return": [..., {"name": "child[15]", "type": "link<usb-host>"}, {"name": "child[14]", "type": "link<usb-host>"}]}
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

