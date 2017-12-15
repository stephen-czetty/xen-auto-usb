# auto-usb-attach #

Python script for attaching usb devices to a HVM xen domain

### What's the point? ###

The USB emulation in xen (up to at least 4.9) leaves some to be
desired.  libxl doesn't provide a facility to hot plug a device
when it's been physically plugged into a hub, and it also doesn't
keep enough information around to remove it from the VM after it's
been unplugged.

This script attempts to fix that shortcoming.


**NOTE** I'm currently running this in a screen window:

    screen sudo ./auto-usb-attach.py -d foo -u usb1 -u usb2

### Usage ###

    usage: auto-usb-attach.py [-h] [-v | -q] -d DOMAIN [-u HUB] [-s QMP_SOCKET]
                              [-n] [-x SPECIFIC_DEVICE]

    optional arguments:
      -h, --help            show this help message and exit
      -v, --verbose         increase verbosity
      -q, --quiet           be very quiet
      -u HUB, --hub HUB     usb hub to monitor (for example, "usb3", "1-1") can be
                            specified multiple times
      -s QMP_SOCKET, --qmp-socket QMP_SOCKET
                            UNIX domain socket to connect to
      -n, --no-wait         Do not wait for the domain, exit immediately if it's
                            not running
      -x SPECIFIC_DEVICE, --specific-device SPECIFIC_DEVICE
                            Specific device to watch for (<vendor-id>:<product-
                            id>)

    required arguments:
      -d DOMAIN, --domain DOMAIN
                            domain name to monitor

### Requirements ###

* python >= 3.6
* pyxs >= 0.4.1
* pyudev >= 0.21.0

### VM Setup ###

#### USB Controller ####

Currently, this script does not automatically create usb controllers
on the VM, so at least one must be created either in the vm
configuration:

     usbctrl = [ 'version=3,ports=15' ]

or via xl:

    xl usbctrl-attach <domain> version=3 ports=15

It is recommended that you don't pre-configure usb devices that are
attached to the hubs to be monitored.  They will be automatically
configured at startup.  If there are devices attached at startup,
this script will attempt to gather the correct info it needs to
handle a detach event, but there may be circumstances where that
will fail.

#### QMP Socket (Optional) ####

If you wish the script to keep an open connection to the devicemodel,
you will need to set up an additional UNIX socket at VM startup.
This can be accomplished by adding the following to your VM
configuration:

    device_model_args = [
        "-chardev",
        "socket,id=usb-attach,path=/run/xen/qmp-usb-Windows,server,nowait",
        "-mon",
        "chardev=usb-attach,mode=control"
    ]

You can then tell the script about this socket with the `--qmp-socket`
switch.

At the moment, this isn't very useful, except maybe for a small
performance gain.  However, in the future, using this will allow
for better control over the monitor, as we can get domain events
and react appropriately to them.

### Features ###

* Monitors udev for device additions and removals on the specified usb
  buses
* Monitors for specific devices (<vendor>:<product>)
* Automatically adds or removes those devices to or from the xen domain
* Automatically removes any "stale" devices on startup (devices
  that were attached, but subsequently removed before startup.)

### Contribution guidelines ###

* TBD.  Submit a pull request, and we'll talk.

### Still TODO ###

* Get rid of the globals in __main__
* Load configuration from a file
* Run as a daemon
  * Create a way to contact and control the daemon
* Gracefully handle VM shutdown/reboot (QMP should send an event if we're connected)
* Create usb controller if an available one doesn't exist
* Qmp.__get_usb_devices could probably cache its data
* (Bonus) Figure out how to create a qmp control socket at runtime
* (Bonus) Figure out how to not run as root
* (Bonus) Support multiple VMs concurrently

### Copyright and License ###

This work is Copyright (c) 2017 by Stephen M. Czetty, and is released
under the GPLv3 license (see LICENSE)

