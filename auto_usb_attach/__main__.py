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
from typing import List

from .options import Options
from .xendomain import XenDomain
from .devicemonitor import DeviceMonitor


def main(args: List[str]) -> None:
    opts = Options(args)

    xen_domain = XenDomain(opts)

    try:
        monitor = DeviceMonitor(opts, xen_domain)
        device_map = monitor.get_connected_devices()
        monitor.monitor_devices(device_map)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
