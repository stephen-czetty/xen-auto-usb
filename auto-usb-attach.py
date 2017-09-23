#!/usr/bin/env /usr/bin/python3

from pyudev import Context, Devices, Monitor


def find_devices_from_root(context, dev):
    real_devices = (x for x in dev.children if x.sys_name.endswith("1.0"))
    real_devices = (x.parent for x in real_devices if x.driver != "hub")

    return iter(set(real_devices))

def attach_device_to_xen(dev, domain):
    print("/usr/sbin/xl usbdev-attach {0} hostbus={1} hostdev={2}"
        .format(domain, dev.properties['BUSNUM'], dev.properties['DEVNUM']))

context = Context()
dev = Devices.from_path(context, '/sys/bus/usb/devices/usb3')

for usbdev in find_devices_from_root(context, dev):
    print("Found at startup: {0.device_path}".format(usbdev))
    attach_device_to_xen(usbdev, "Windows")

monitor = Monitor.from_netlink(context)
monitor.filter_by('usb')

for event in iter(monitor.poll()):
    for usbdev in find_devices_from_root(event):
        print('{0.action} on {0.device_path}'.format(device))
        attach_device_to_xen(usbdev, "Windows")
