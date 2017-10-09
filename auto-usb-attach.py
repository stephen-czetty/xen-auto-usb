#!/usr/bin/env /usr/bin/python3.6

# TODO: Store state in xenstore, so we can recover from a crash.
# xenstore paths of interest:
# /local/domain/* -- List of running domains (0, 1, etc.)
# /local/domain/*/name -- Names of the domains
# /libxl/*/device/vusb/* -- Virtual USB controllers
# /libxl/*/device/vusb/*/port/* -- Mapped ports (look up in /sys/bus/usb/devices)
from typing import List, Tuple, Optional, Dict, Iterable, cast
import socket

import pyudev
# IMPORTANT NOTE: There is a bug in the latest version of pyxs.
# There is a pending PR for it: https://github.com/selectel/pyxs/pull/13
# In the meantime, I've just made the appropriate change in my local
# installation.
import pyxs

xl_path = "/usr/sbin/xl"
vm_name = "Windows"
sysfs_root = "/sys/bus/usb/devices"


def is_a_device_we_care_about(devices_to_monitor: List[pyudev.Device], device: pyudev.Device) -> bool:
    for monitored_device in devices_to_monitor:
        if device.device_path.startswith(monitored_device.device_path):
            return "bDeviceClass" in device.attributes.available_attributes \
                   and int(device.attributes.get("bDeviceClass"), 16) != 9

    return False


def find_devices_from_root(root_device: pyudev.Device) -> Iterable[pyudev.Device]:
    for d in root_device.children:
        if is_a_device_we_care_about([root_device], d):
            yield d


def send_qmp_command(domain_id: int, command: str, arguments: Dict[str, str]) -> bool:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as qmp_socket:
        qmp_socket.connect("/run/xen/qmp-libxl-{0}".format(domain_id))
        qmp_file = qmp_socket.makefile()
        print(qmp_file.readline())
        qmp_socket.send(b"{\"execute\": \"qmp_capabilities\"}")
        print(qmp_file.readline())
        argument_str = ", ".join("\"{0}\": \"{1}\"".format(k, v) for k, v in arguments.items())
        command_str = "{{\"execute\": \"{0}\", \"arguments\": {{{1}}}}}".format(command, argument_str)
        print(command_str)
        qmp_socket.send(bytes(command_str, "ascii"))
        result = qmp_file.readline()
        print(result)
        return "error" not in result


def find_next_open_controller_and_port(domain_id: int) -> Tuple[int, int]:
    with pyxs.Client() as c:
        path = "/libxl/{0}/device/vusb".format(domain_id)
        for controller in c.list(bytes(path, "utf-8")):
            controller = controller.decode("utf-8")
            c_path = "{0}/{1}/port".format(path, controller)
            for port in c.list(bytes(c_path, "utf-8")):
                port = port.decode("utf-8")
                d_path = "{0}/{1}".format(c_path, port)
                if c[bytes(d_path, "utf-8")].decode("utf-8") == "":
                    print("Choosing Controller {0}, Slot {1}"
                          .format(controller, port))
                    return int(controller), int(port)


def attach_device_to_xen(dev: pyudev.Device, domain_id: int) -> Optional[Tuple[int, int, int, int]]:
    busnum = int(dev.properties['BUSNUM'])
    devnum = int(dev.properties['DEVNUM'])
    args = [xl_path,
            "usbdev-attach",
            str(domain_id),
            "hostbus={0}".format(busnum),
            "hostaddr={0}".format(devnum)]
    print(" ".join(args))

    # Find an open controller and slot
    controller, port = find_next_open_controller_and_port(domain_id)

    # Add the entry to xenstore
    with pyxs.Client() as c:
        try:
            txn_id = c.transaction()
            path = "/libxl/{0}/device/vusb/{1}/port/{2}".format(domain_id, controller, port)
            c[bytes(path, "utf-8")] = bytes(dev.sys_name, "ascii")

        # Attach the device to qemu
            if not send_qmp_command(domain_id, "device_add",
                                    {"id": "xenusb-{0}-{1}".format(busnum, devnum),
                                     "driver": "usb-host",
                                     "bus": "xenusb-{0}.0".format(controller),
                                     "port": "{0}".format(port),
                                     "hostbus": "{0}".format(busnum),
                                     "hostaddr": "{0}".format(devnum)}):
                # Reset the xenstore data
                c.rollback()
                txn_id = None
        except pyxs.PyXSError as e:
            if txn_id is not None:
                c.rollback()
            print(e)
            return None

        c.commit()

    return controller, port, busnum, devnum


# This method is going to take some work.  xl's tooling doesn't actually do the right thing (as of 4.8), so we'll
# want to communicate with qemu directly.  The C++ code to do this in xl can be found at:
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
def detach_device_from_xen(domain_id: int, device_mapping: Tuple[int, int, int, int]) -> bool:
    if device_mapping[2] <= 0:
        # We don't have enough information to remove it.  Just leave things alone.
        # TODO: This is technically a bug, but will require some xenstore trickery to get right.
        return False

    # Remove the mapping from qemu
    if not send_qmp_command(domain_id, "device_del",
                            {"id": "xenusb-{0}-{1}".format(device_mapping[2], device_mapping[3])}):
        return False

    try:
        with pyxs.Client() as c:
            # Clear xl's xenstore entry for the device.
            path = "/libxl/{0}/device/vusb/{1}/port/{2}".format(domain_id, device_mapping[0], device_mapping[1])
            c[bytes(path, "utf-8")] = b""
    except pyxs.PyXSError as e:
        print(e)
        return False

    return True


def find_domain_id(name: str) -> int:
    with pyxs.Client() as c:
        for domain_id in c.list(b"/local/domain"):
            path = "/local/domain/{0}/name".format(domain_id.decode("utf-8"))
            if c[bytes(path, "utf-8")].decode("utf-8") == name:
                return int(domain_id.decode("utf-8"))
        return -1


def find_device_mapping(domain_id: int, sys_name: str) -> Optional[Tuple[int, int, int, int]]:
    with pyxs.Client() as c:
        path = "/libxl/{0}/device/vusb".format(domain_id)
        for controller in c.list(bytes(path, "utf-8")):
            controller = controller.decode("utf-8")
            c_path = "{0}/{1}/port".format(path, controller)
            for device in c.list(bytes(c_path, "utf-8")):
                device = device.decode("utf-8")
                d_path = "{0}/{1}".format(c_path, device)
                if c[bytes(d_path, "utf-8")].decode("utf-8") == sys_name:
                    print("Controller {0}, Device {1}"
                          .format(controller, device))
                    return controller, device, -1, -1
    return None


def get_device(ctx: pyudev.Context, name: str) -> pyudev.Device:
    return pyudev.Devices.from_path(ctx, "{0}/{1}".format(sysfs_root, name))


def get_connected_devices(devices_to_monitor: List[pyudev.Device], domain_id: int)\
            -> Dict[str, Tuple[int, int, int, int]]:
    device_map = {}
    for monitored_device in devices_to_monitor:
        for device in find_devices_from_root(monitored_device):
            print("Found at startup: {0.device_path}".format(device))
            dev_map = find_device_mapping(domain_id, device.sys_name)
            if dev_map is None:
                dev_map = attach_device_to_xen(device, domain_id)
            if dev_map is not None:
                device_map[device.sys_name] = dev_map
    return device_map


# This method never returns unless there's an exception.  Good?  Bad?
def monitor_devices(ctx: pyudev.Context, devices_to_monitor: List[pyudev.Device],
                    known_devices: Dict[str, Tuple[int, int, int, int]], domain_id: int)\
            -> Dict[str, Tuple[int, int, int, int]]:
    device_map = known_devices.copy()
    monitor = pyudev.Monitor.from_netlink(ctx)
    monitor.filter_by('usb')

    for device in cast(Iterable[Optional[pyudev.Device]], iter(monitor.poll, None)):
        if device is None:
            return device_map

        print('{0.action} on {0.device_path}'.format(device))
        print(device_map)
        if device.action == "add":
            if is_a_device_we_care_about(devices_to_monitor, device):
                if device.sys_name not in device_map:
                    print("Device added: {0}".format(device))
                    dev_map = attach_device_to_xen(device, domain_id)
                    if dev_map is not None:
                        device_map[device.sys_name] = dev_map
        elif device.action == "remove" and device.sys_name in device_map:
            print("Removing device: {0}".format(device))
            if detach_device_from_xen(domain_id, device_map[device.sys_name]):
                del device_map[device.sys_name]


def main() -> None:
    domain_id = find_domain_id(vm_name)
    if domain_id < 0:
        raise NameError("Could not find domain {0}".format(vm_name))

    context = pyudev.Context()
    monitored_devices = [get_device(context, "usb3"), get_device(context, "usb4")]

    try:
        device_map = get_connected_devices(monitored_devices, domain_id)
        monitor_devices(context, monitored_devices, device_map, domain_id)
    except KeyboardInterrupt:
        pass


main()
