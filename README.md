# auto-usb-attach #

Python script for attaching usb devices to a xen domain

### What's the point? ###

The USB emulation in xen (4.8) leaves some to be desired.  libxl doesn't provide a facility
to hot plug a device when it's been physically plugged into a hub, and it also doesn't keep
enough information aronud to remove it from the VM after it's been unplugged.

This script attempts to fix that shortcoming.

---
| | **NOTE** I'm currently running this in a screen window:<br>`screen sudo ./auto-usb-attach.py -d foo -u usb1` |
---

### Usage ###

    usage: auto-usb-attach.py [-h] [-v | -q] -d DOMAIN -u HUB
    
    optional arguments:
      -h, --help            show this help message and exit
      -v, --verbose         increase verbosity
      -q, --quiet           be very quiet
      -d DOMAIN, --domain DOMAIN
                            domain name to monitor
      -u HUB, --hub HUB     usb hub to monitor (for example, "usb3", "1-1")


### Requirements ###

* python 3.6
* pyxs >= 0.4.1
* pyudev >= 0.21.0

### Contribution guidelines ###

* TBD.  Submit a pull request, and we'll talk.

### Still TODO ###

* Run as a daemon
* Store state in xenstore, so we can recover from a crash.
* Gracefully handle situations where the VM is not running (wait for it to come up?)
* Gracefully handle VM shutdown
* (Bonus) Figure out how to not run as root
* (Bonus) Support multiple VMs concurrently
