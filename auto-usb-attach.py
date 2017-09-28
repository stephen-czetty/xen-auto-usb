#!/usr/bin/env /usr/bin/python3

# xenstore paths of interest:
# /local/domain/* -- List of running domains (0, 1, etc.)
# /local/domain/*/name -- Names of the domains
# /libxl/*/device/vusb/* -- Virtual USB controllers
# /libxl/*/device/vusb/*/port/* -- Mapped ports (look up in /sys/bus/usb/devices)


from pyudev import Context, Devices, Monitor
from pyxs import Client


xl_path = "/usr/sbin/xl"
vm_name = "Windows"
sysfs_root = "/sys/bus/usb/devices"

def find_devices_from_root(context, dev):
    real_devices = (x for x in dev.children if x.sys_name.endswith(":1.0"))
    real_devices = (x.parent for x in real_devices if x.driver != "hub")

    return iter(set(real_devices))

def attach_device_to_xen(dev, domain):
    args = [xl_path,
            "usbdev-attach",
            domain,
            "hostbus={0}".format(dev.properties['BUSNUM']),
            "hostdev={0}".format(dev.properties['DEVNUM'])]
    print(" ".join(args))

def find_domain_id(name):
    with Client() as c:
        for id in c.list(b"/local/domain"):
            path = "/local/domain/{0}/name".format(id.decode("utf-8"))
            if (c[bytes(path, "utf-8")].decode("utf-8") == name):
                return int(id.decode("utf-8"))
        return -1

def find_device_mapping(domain_id, sys_name):
    with Client() as c:
        path = "/libxl/{0}/device/vusb".format(domain_id)
        for controller in c.list(bytes(path, "utf-8")):
            controller = controller.decode("utf-8")
            c_path = "{0}/{1}/port".format(path, controller)
            for device in c.list(bytes(c_path, "utf-8")):
                device = device.decode("utf-8")
                d_path = "{0}/{1}".format(c_path, device)
                if (c[bytes(d_path, "utf-8")].decode("utf-8") == sys_name):
                    print("Controller {0}, Device {1}"
                            .format(controller, device))
                    return [controller, device]
    return None

def get_device(context, name):
    return Devices.from_path(context, "{0}/{1}".format(sysfs_root, name))

domain_id = find_domain_id(vm_name)
if (domain_id < 0):
    raise NameError("Could not find domain {0}".format(vm_name))

context = Context()
devs = [get_device(context, "usb3"), get_device(context, "usb4")]

for dev in devs:
    for usbdev in find_devices_from_root(context, dev):
        print("Found at startup: {0.device_path}".format(usbdev))
        if (find_device_mapping(domain_id, usbdev.sys_name) == None):
            attach_device_to_xen(usbdev, vm_name)
            find_device_mapping(domain_id, usbdev.sys_name)

monitor = Monitor.from_netlink(context)
monitor.filter_by('usb')

try:
    for device in iter(monitor.poll, None):
        print('{0.action} on {0.device_path}'.format(device))
        if device.action == "add":
            for dev in devs:
                if device.device_path.startswith(dev.device_path):
                    if device.sys_name.endswith(":1.0"):
                        if device.driver != "hub":
                            attach_device_to_xen(device.parent, vm_name)
                            find_device_mapping(domain_id, device.parent.sys_name)
except KeyboardInterrupt:
    pass

