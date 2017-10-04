#!/usr/bin/env /usr/bin/python3.6

# xenstore paths of interest:
# /local/domain/* -- List of running domains (0, 1, etc.)
# /local/domain/*/name -- Names of the domains
# /libxl/*/device/vusb/* -- Virtual USB controllers
# /libxl/*/device/vusb/*/port/* -- Mapped ports (look up in /sys/bus/usb/devices)
from typing import List, Tuple, Optional, Dict, Iterable, cast

import pyudev
import pyxs

xl_path = "/usr/sbin/xl"
vm_name = "Windows"
sysfs_root = "/sys/bus/usb/devices"


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


def attach_device_to_xen(dev: pyudev.Device, domain: str) -> None:
    args = [xl_path,
            "usbdev-attach",
            domain,
            "hostbus={0}".format(dev.properties['BUSNUM']),
            "hostdev={0}".format(dev.properties['DEVNUM'])]
    print(" ".join(args))


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
    return None


def get_device(ctx: pyudev.Context, name: str) -> pyudev.Device:
    return pyudev.Devices.from_path(ctx, "{0}/{1}".format(sysfs_root, name))


def get_connected_devices(devices_to_monitor: List[pyudev.Device], domain_id: int) -> Dict[str, Tuple[int, int]]:
    device_map = {}
    for monitored_device in devices_to_monitor:
        for device in find_devices_from_root(monitored_device):
            print("Found at startup: {0.device_path}".format(device))
            dev_map = find_device_mapping(domain_id, device.sys_name)
            if dev_map is None:
                attach_device_to_xen(device, vm_name)
                dev_map = find_device_mapping(domain_id, device.sys_name)
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
        if device.action == "add":
            if is_a_device_we_care_about(devices_to_monitor, device):
                if device.parent.sys_name not in device_map:
                    print("Device added: {0}".format(device.parent))
                    attach_device_to_xen(device.parent, vm_name)
                    dev_map = find_device_mapping(domain_id, device.parent.sys_name)
                    device_map[device.parent.sys_name] = dev_map


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
