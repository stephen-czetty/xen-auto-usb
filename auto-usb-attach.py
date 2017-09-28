#!/usr/bin/env /usr/bin/python3

# xenstore paths of interest:
# /local/domain/* -- List of running domains (0, 1, etc.)
# /local/domain/*/name -- Names of the domains
# /libxl/*/device/vusb/* -- Virtual USB controllers
# /libxl/*/device/vusb/*/port/* -- Mapped ports (look up in /sys/bus/usb/devices)


from pyudev import Context, Devices, Monitor


def find_devices_from_root(context, dev):
    real_devices = (x for x in dev.children if x.sys_name.endswith(":1.0"))
    real_devices = (x.parent for x in real_devices if x.driver != "hub")

    return iter(set(real_devices))

def attach_device_to_xen(dev, domain):
    args = ["/usr/sbin/xl",
            "usbdev-attach",
            domain,
            "hostbus={0}".format(dev.properties['BUSNUM']),
            "hostdev={0}".format(dev.properties['DEVNUM'])]
    print(" ".join(args))

context = Context()
devs = [Devices.from_path(context, '/sys/bus/usb/devices/usb3'),
        Devices.from_path(context, '/sys/bus/usb/devices/usb4')]

for dev in devs:
    for usbdev in find_devices_from_root(context, dev):
        print("Found at startup: {0.device_path}".format(usbdev))
        attach_device_to_xen(usbdev, "Windows")

monitor = Monitor.from_netlink(context)
monitor.filter_by('usb')

for device in iter(monitor.poll, None):
    print('{0.action} on {0.device_path}'.format(device))
    if device.action == "add":
        for dev in devs:
            if device.device_path.startswith(dev.device_path):
                if device.sys_name.endswith(":1.0"):
                    if device.driver != "hub":
                        attach_device_to_xen(device.parent, "Windows")

