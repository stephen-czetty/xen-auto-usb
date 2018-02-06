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

    screen /usr/local/bin/usb-monitor -d foo -u usb1 -u usb2

### Usage ###

    usage: usb-monitor [-h] [-v | -q] -d DOMAIN [-u HUB] [-s QMP_SOCKET]
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
      -w, --wait-on-shutdown
                            Wait for a new domain on domain shutdown. (Do not exit)

    required arguments:
      -d DOMAIN, --domain DOMAIN
                            domain name to monitor

### Requirements ###

* python >= 3.6
* pyxs >= 0.4.1
* pyudev >= 0.21.0
* psutil >= 5.0.0

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
        "socket,id=usb-attach,path=/run/xen/qmp-usb-foo,server,nowait",
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
* Correctly recovers from a domain reboot (and shutdown with -w)

### Installation ###

There is a C wrapper intended to be compiled and run setuid.  Until I
write an installation script (still TODO), there are several steps
required to get everything up and running:

1. Build the wrapper: `gcc -o usb-monitor wrapper.c`
2. Create a folder in `/usr/local/` (I used `/usr/local/usb-monitor`)
3. Copy the contents of this project (including the compiled binary) to
   this folder: `sudo cp -r * /usr/local/usb-monitor`
4. Make sure everything is owned by root, and permissions look as you'd
   like.
    - You might want to set a specific group so only certain users can
      use the utility.
5. Add the setuid bit to the `usb-monitor` binary:
   `chmod u+s /usr/local/usb-monitor/usb-monitor`
6. Symlink the binary into `/usr/local/bin`: `ln -s
   /usr/local/usb-monitor/usb-monitor /usr/local/bin`

### Contribution guidelines ###

* Try to stick with the style
  * Making things more pythonic is acceptable, since I'm still pretty
    new to python in general.
* Submit a pull request, and we'll talk.

### Still TODO ###

* Expand setup.py to do a full installation
  * Including a build of the wrapper, setting up
    setuid bit, symlinks, etc.
* Load configuration from a file
* Run as a daemon
  * Create a way to contact and control the daemon
* Create usb controller if an available one doesn't exist
* Qmp.__get_usb_devices could probably cache its data
* Add unit tests!
* DeviceMonitor.__is_a_device_we_care_about() does not belong there; it
  should probably move to MainThread
* (Bonus) Figure out how to create a qmp control socket at runtime
* (Bonus) Figure out how to not run as root
* (Bonus) Support multiple VMs concurrently

### Copyright and License ###

This work is Copyright (c) 2017, 2018 by Stephen M. Czetty, and is released
under the GPLv3 license (see LICENSE)

