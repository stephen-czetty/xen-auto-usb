#!/usr/bin/env /usr/bin/python3.6

# TODO: Store state in xenstore, so we can recover from a crash.
# TODO: Gracefully handle situations where the VM is not running (wait for it to come up?)
# TODO: Gracefully handle VM shutdown
# TODO: Run as a daemon
# BONUS TODO: Support multiple VMs concurrently

# xenstore paths of interest:
# /local/domain/* -- List of running domains (0, 1, etc.)
# /local/domain/*/name -- Names of the domains
# /libxl/*/device/vusb/* -- Virtual USB controllers
# /libxl/*/device/vusb/*/port/* -- Mapped ports (look up in /sys/bus/usb/devices)
import sys
from typing import List, Tuple, Optional, Dict, Iterable, cast
import socket

import pyudev
import pyxs
import argparse
import re

# There is a bug in the latest version of pyxs.
# There is a pending PR for it: https://github.com/selectel/pyxs/pull/13
# In the meantime, this should fix it.
pyxs.client._re_7bit_ascii = re.compile(b"^[\x00\x20-\x7f]*$")

vm_name = "Windows"
sysfs_root = "/sys/bus/usb/devices"


class Options:
    @property
    def is_verbose(self) -> bool:
        return self.__verbosity > 0

    @property
    def is_very_verbose(self) -> bool:
        return self.__verbosity > 1

    @property
    def is_quiet(self) -> bool:
        return self.__verbosity < 0

    @property
    def domain(self) -> str:
        return self.__domain

    @property
    def hubs(self) -> List[str]:
        return self.__hubs

    def print_very_verbose(self, string: str):
        if self.is_very_verbose:
            print(string)

    def print_verbose(self, string: str):
        if self.is_verbose:
            print(string)

    def print_unless_quiet(self, string: str):
        if not self.is_quiet:
            print(string)

    @staticmethod
    def __get_argument_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()

        group = parser.add_mutually_exclusive_group()
        group.add_argument("-v", "--verbose", help="increase verbosity", action="count", default=0)
        group.add_argument("-q", "--quiet", help="be very quiet", action="store_true")
        parser.add_argument("-d", "--domain", help="domain name to monitor", type=str, action="store", required=True)
        parser.add_argument("-u", "--hub", help="usb hub to monitor (for example, \"usb3\", \"1-1\")", type=str,
                            action="append", required=True)

        return parser

    def __init__(self, args: List[str]):
        parser = self.__get_argument_parser()
        parsed = parser.parse_args(args)
        self.__verbosity = -1 if parsed.quiet else parsed.verbose
        self.__domain = parsed.domain
        self.__hubs = parsed.hub

        self.print_very_verbose("Command line arguments:")
        self.print_very_verbose("Verbosity: {0}".format("Very Verbose" if self.is_very_verbose else
                                                        "Verbose" if self.is_verbose else
                                                        "Quiet" if self.is_quiet else "Normal"))
        self.print_very_verbose("Domain: {0}".format(self.domain))
        self.print_very_verbose("Hubs: {0}".format(self.hubs))


class Device:
    @property
    def device_path(self):
        return self.__inner.device_path

    @property
    def busnum(self):
        return int(self.__inner.properties['BUSNUM'])

    @property
    def devnum(self):
        return int(self.__inner.properties['DEVNUM'])

    @property
    def sys_name(self):
        return self.__inner.sys_name

    @property
    def action(self):
        return self.__inner.action

    @property
    def children(self):
        return (Device(x) for x in self.__inner.children)

    def is_a_hub(self) -> bool:
        return "bDeviceClass" in self.__inner.attributes.available_attributes \
               and int(self.__inner.attributes.get("bDeviceClass"), 16) == 9

    def is_a_root_device(self) -> bool:
        return "bDeviceClass" in self.__inner.attributes.available_attributes

    def is_a_device_we_care_about(self, devices_to_monitor: List['Device']) -> bool:
        for monitored_device in devices_to_monitor:
            if self.device_path.startswith(monitored_device.device_path):
                return not self.is_a_hub() and self.is_a_root_device()

        return False

    def devices_of_interest(self) -> Iterable['Device']:
        for d in self.children:
            if d.is_a_device_we_care_about([self]):
                yield d

    def __init__(self, inner: pyudev.Device):
        self.__inner = inner


class DeviceMonitor:
    __context = None

    def __get_device(self, device_name: str) -> Device:
        inner = pyudev.Devices.from_path(self.__context, "{0}/{1}".format(sysfs_root, device_name))

        return Device(inner)

    def get_connected_devices(self) -> Dict[str, Tuple[int, int, int, int]]:
        device_map = {}
        for monitored_device in self.__root_devices:
            for device in monitored_device.devices_of_interest():
                self.__options.print_verbose("Found at startup: {0.device_path}".format(device))
                dev_map = self.__domain.find_device_mapping(device.sys_name)
                if dev_map is None:
                    dev_map = self.__domain.attach_device_to_xen(device)
                if dev_map is not None:
                    device_map[device.sys_name] = dev_map
        return device_map

    # This method never returns unless there's an exception.  Good?  Bad?
    def monitor_devices(self, known_devices: Dict[str, Tuple[int, int, int, int]]) \
            -> Dict[str, Tuple[int, int, int, int]]:
        device_map = known_devices.copy()
        monitor = pyudev.Monitor.from_netlink(self.__context)
        monitor.filter_by('usb')

        for device in cast(Iterable[Optional[pyudev.Device]], iter(monitor.poll, None)):
            if device is None:
                return device_map

            device = Device(device)
            self.__options.print_very_verbose('{0.action} on {0.device_path}'.format(device))
            if device.action == "add":
                if device.is_a_device_we_care_about(self.__root_devices):
                    if device.sys_name not in device_map:
                        self.__options.print_verbose("Device added: {0}".format(device))
                        dev_map = self.__domain.attach_device_to_xen(device)
                        if dev_map is not None:
                            device_map[device.sys_name] = dev_map
            elif device.action == "remove" and device.sys_name in device_map:
                self.__options.print_verbose("Removing device: {0}".format(device))
                if self.__domain.detach_device_from_xen(device_map[device.sys_name]):
                    del device_map[device.sys_name]

    def __init__(self, opts: Options, xen_domain: XenDomain):
        self.__context = pyudev.Context()
        self.__root_devices = [self.__get_device(x) for x in opts.hubs]
        self.__options = opts
        self.__domain = xen_domain

        for d in self.__root_devices:
            if not d.is_a_root_device():
                raise RuntimeError("Device {0} is not a root device node".format(d.sys_name))
            if not d.is_a_hub():
                raise RuntimeError("Device {0} is not a hub".format(d.sys_name))


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

    def __send_qmp_command(self, command: str, arguments: Dict[str, str]) -> bool:
        # noinspection PyUnresolvedReferences
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as qmp_socket:
            self.__options.print_very_verbose("Connecting to QMP")
            qmp_socket.connect("/run/xen/qmp-libxl-{0}".format(self.__domain_id))
            qmp_file = qmp_socket.makefile()
            self.__options.print_very_verbose(qmp_file.readline())
            qmp_socket.send(b"{\"execute\": \"qmp_capabilities\"}")
            self.__options.print_very_verbose(qmp_file.readline())
            argument_str = ", ".join("\"{0}\": \"{1}\"".format(k, v) for k, v in arguments.items())
            command_str = "{{\"execute\": \"{0}\", \"arguments\": {{{1}}}}}".format(command, argument_str)
            self.__options.print_very_verbose(command_str)
            qmp_socket.send(bytes(command_str, "ascii"))
            result = qmp_file.readline()
            self.__options.print_very_verbose(result)
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


def main(args: List[str]) -> None:
    options = Options(args)

    xen_domain = XenDomain(options)

    try:
        monitor = DeviceMonitor(options, xen_domain)
        device_map = monitor.get_connected_devices()
        monitor.monitor_devices(device_map)
    except KeyboardInterrupt:
        pass


main(sys.argv[1:])
