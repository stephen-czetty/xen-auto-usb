import json
import socket
from typing import Dict

from .options import Options


class Qmp:
    def __connect_to_qmp(self, sock: socket.socket) -> Dict:
        self.__options.print_very_verbose("Connecting to QMP")
        sock.connect(self.__path)
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

    def attach_usb_device(self, busnum: int, devnum: int, controller: int, port: int):
        return self.__send_qmp_command("device_add",
                                       {"id": "xenusb-{0}-{1}".format(busnum, devnum),
                                        "driver": "usb-host",
                                        "bus": "xenusb-{0}.0".format(controller),
                                        "port": "{0}".format(port),
                                        "hostbus": "{0}".format(busnum),
                                        "hostaddr": "{0}".format(devnum)}
                                       )

    def detach_usb_device(self, controller: int, port: int):
        return self.__send_qmp_command("device_del", {"id": "xenusb-{0}-{1}".format(controller, port)})

    def __init__(self, path: str, options: Options):
        self.__options = options
        self.__path = path
