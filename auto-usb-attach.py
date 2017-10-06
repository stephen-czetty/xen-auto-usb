#!/usr/bin/env /usr/bin/python3.6

# TODO: Store state somewhere in /run, so the script can recover after a crash.
# xenstore paths of interest:
# /local/domain/* -- List of running domains (0, 1, etc.)
# /local/domain/*/name -- Names of the domains
# /libxl/*/device/vusb/* -- Virtual USB controllers
# /libxl/*/device/vusb/*/port/* -- Mapped ports (look up in /sys/bus/usb/devices)
from typing import List, Tuple, Optional, Dict, Iterable, cast
import socket

import pyudev
import pyxs

xl_path = "/usr/sbin/xl"
vm_name = "Windows"
sysfs_root = "/sys/bus/usb/devices"


# TODO: This can be simplified by checking bDeviceClass != 9 for the root, instead of checking ":1.0"
def is_a_device_we_care_about(devices_to_monitor: List[pyudev.Device], device: pyudev.Device) -> bool:
    for monitored_device in devices_to_monitor:
        if device.device_path.startswith(monitored_device.device_path):
            if device.sys_name.endswith(":1.0") and device.driver != "hub":
                return True
    return False


def find_devices_from_root(root_device: pyudev.Device) -> Iterable[pyudev.Device]:
    for d in root_device.children:
        if is_a_device_we_care_about([root_device], d):
            yield d.parent


# TODO: Communicate directly with qemu, but set up xenstore so xl will work from the commandline, too.
# (see notes below, but in reverse.  See libxl__device_usbdev_add_hvm)  -- This is actually a bit more
# complicated, since we need to select a controller and port to use, but not too bad.
def attach_device_to_xen(dev: pyudev.Device, domain: str) -> bool:
    args = [xl_path,
            "usbdev-attach",
            domain,
            "hostbus={0}".format(int(dev.properties['BUSNUM'])),
            "hostaddr={0}".format(int(dev.properties['DEVNUM']))]
    print(" ".join(args))
    return True


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
def detach_device_from_xen(dev: pyudev.Device, domain_id: int, device_mapping: Tuple[int, int, int, int]) -> bool:
    if len(device_mapping) > 2:
        # Remove the mapping from qemu
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as qmp_socket:
            qmp_socket.connect("/run/xen/qmp-libxl-{0}".format(domain_id))
            qmp_filereader = qmp_socket.makefile()
            print(qmp_filereader.readline())
            qmp_socket.send(b"{\"execute\": \"qmp_capabilities\"}")
            print(qmp_filereader.readline())
            qmp_socket.send(bytes("{{\"execute\": \"device_del\", \"arguments\": {{\"id\": \"xenusb-{0}-{1}\"}}}}"
                .format(device_mapping[2], device_mapping[3]), "ascii"))
            result = qmp_filereader.readline()
            print(result)
            if "error" in result:
                return False

    # TODO: What exceptions might be thrown here?
    with pyxs.Client() as c:
        # Remove xl's xenstore entry for the device.
        path = "/libxl/{0}/device/vusb/{1}/port/{2}".format(domain_id, device_mapping[0], device_mapping[1])
        c[bytes(path, "utf-8")] = ""

    return True  # TODO


def find_domain_id(name: str) -> int:
    with pyxs.Client() as c:
        for domain_id in c.list(b"/local/domain"):
            path = "/local/domain/{0}/name".format(domain_id.decode("utf-8"))
            if c[bytes(path, "utf-8")].decode("utf-8") == name:
                return int(domain_id.decode("utf-8"))
        return -1


def find_device_mapping(domain_id: int, sys_name: str) -> Optional[Tuple[int, int]]:
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
                    return controller, device
    return (-1, -1) # None


def get_device(ctx: pyudev.Context, name: str) -> pyudev.Device:
    return pyudev.Devices.from_path(ctx, "{0}/{1}".format(sysfs_root, name))


def get_connected_devices(devices_to_monitor: List[pyudev.Device], domain_id: int) -> Dict[str, Tuple[int, int]]:
    device_map = {}
    for monitored_device in devices_to_monitor:
        for device in find_devices_from_root(monitored_device):
            print("Found at startup: {0.device_path}".format(device))
            dev_map = find_device_mapping(domain_id, device.sys_name)
            if dev_map is None:
                if attach_device_to_xen(device, vm_name):
                    dev_map = find_device_mapping(domain_id, device.sys_name)
            if dev_map is not None:
                device_map[device.sys_name] = dev_map
    return device_map


# This method never returns unless there's an exception.  Good?  Bad?
def monitor_devices(ctx: pyudev.Context, devices_to_monitor: List[pyudev.Device],
                    known_devices: Dict[str, Tuple[int, int]], domain_id: int) -> Dict[str, Tuple[int, int]]:
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
                if device.parent.sys_name not in device_map:
                    print("Device added: {0}".format(device.parent))
                    if attach_device_to_xen(device.parent, vm_name):
                        dev_map = find_device_mapping(domain_id, device.parent.sys_name)
                        device_map[device.parent.sys_name] = dev_map +\
                            (int(device.parent.properties['BUSNUM']), int(device.parent.properties['DEVNUM']))
        elif device.action == "remove" and device.sys_name in device_map:
            print("Removing device: {0}".format(device))
            if detach_device_from_xen(device, domain_id, device_map[device.sys_name]):
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
