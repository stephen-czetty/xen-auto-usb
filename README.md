# auto-usb-attach #

Python script for attaching usb devices to a xen domain

### What's the point? ###

The USB emulation in xen (4.8) leaves some to be desired.  libxl doesn't provide a facility
to hot plug a device when it's been physically plugged into a hub, and it also doesn't keep
enough information aronud to remove it from the VM after it's been unplugged.

This script attempts to fix that shortcoming.


**NOTE** I'm currently running this in a screen window:

    screen sudo ./auto-usb-attach.py -d foo -u usb1

### Usage ###

    usage: auto-usb-attach.py [-h] [-v | -q] -d DOMAIN -u HUB
    
    optional arguments:
      -h, --help            show this help message and exit
      -v, --verbose         increase verbosity
      -q, --quiet           be very quiet
      -d DOMAIN, --domain DOMAIN
                            domain name to monitor
      -u HUB, --hub HUB     usb hub to monitor (for example, "usb3", "1-1") can be
                            specified multiple times


### Requirements ###

* python 3.6
* pyxs >= 0.4.1
* pyudev >= 0.21.0

### VM Setup ###

Currently, this script does not automatically create usb controllers
on the VM, so at least one must be created either in the vm
configuration:

     usbctrl = [ 'version=3,ports=15' ]

or, via xl:

    xl usbctrl-attach <domain> version=3 ports=15

It is recommended that you don't pre-configure usb devices that are
attached to the hubs to be monitored.  They will be automatically
configured at startup.  At this time, the script will not have enough
information to correctly detach pre-configured devices should they
be removed.

### Contribution guidelines ###

* TBD.  Submit a pull request, and we'll talk.

### Still TODO ###

* Convert to an observer pattern
* Stay connected to QMP
* Run as a daemon
  * Create a way to contact and control the daemon
* Store state in xenstore, so we can recover from a crash.
* Gracefully handle situations where the VM is not running (wait for it to come up?)
* Gracefully handle VM shutdown/reboot (QMP should send an event if we're connected)
* Create usb controller if an available one doesn't exist
* (Bonus) Figure out how to not run as root
* (Bonus) Support multiple VMs concurrently
