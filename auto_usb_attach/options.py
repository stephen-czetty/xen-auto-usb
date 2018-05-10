from typing import List, Optional
import argparse
from datetime import datetime
import os
import sys
import yaml


class Options:
    @property
    def wrapper_name(self) -> str:
        return self.__wrapper_name

    @property
    def is_verbose(self) -> bool:
        return self.__verbosity > 0

    @property
    def is_very_verbose(self) -> bool:
        return self.__verbosity > 1

    @property
    def is_debug(self) -> bool:
        return self.__verbosity > 2

    @property
    def is_quiet(self) -> bool:
        return self.__verbosity < 0

    @property
    def domain(self) -> str:
        return self.__domain

    @property
    def hubs(self) -> List[str]:
        return self.__hubs

    @property
    def specific_devices(self) -> List[str]:
        return self.__specific_devices

    @property
    def qmp_socket(self) -> Optional[str]:
        return self.__qmp_socket

    @property
    def no_wait(self) -> bool:
        return self.__no_wait

    @property
    def wait_on_shutdown(self) -> bool:
        return self.__wait_on_shutdown

    @property
    def usb_version(self) -> int:
        return self.__usb_version

    @property
    def log_file(self) -> str:
        return self.__log_file

    @property
    def no_daemon(self) -> bool:
        return self.__no_daemon

    def __print_with_timestamp(self, string: str) -> None:
        self.__log_output.write(f"[{datetime.now():%a %b %d %H:%M:%S %Y}] {string}\n")

    def print_debug(self, string: str) -> None:
        if self.is_debug:
            self.__print_with_timestamp(f"Debug: {string}")

    def print_very_verbose(self, string: str) -> None:
        if self.is_very_verbose:
            self.__print_with_timestamp(string)

    def print_verbose(self, string: str) -> None:
        if self.is_verbose:
            self.__print_with_timestamp(string)

    def print_unless_quiet(self, string: str) -> None:
        if not self.is_quiet:
            self.__print_with_timestamp(string)

    def __get_argument_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=os.path.basename(self.__wrapper_name))

        verbosity_group = parser.add_mutually_exclusive_group()
        verbosity_group.add_argument("-v", "--verbose", help="increase verbosity", action="count", default=0)
        verbosity_group.add_argument("-q", "--quiet", help="be very quiet", action="store_true")
        parser.add_argument("-c", "--config", help="config file", type=argparse.FileType(), default=None)
        parser.add_argument("-d", "--domain", help="domain name to monitor", type=str, action="store")
        parser.add_argument("-u", "--hub", help="usb hub to monitor (for example, \"usb3\", \"1-1\")\n"
                                                "can be specified multiple times", type=str, action="append")
        parser.add_argument("-s", "--qmp-socket", help="UNIX domain socket to connect to", type=str, dest="qmp_socket",
                            default=None)
        parser.add_argument("-n", "--no-wait", help="Do not wait for the domain, exit immediately if it's not running",
                            dest="no_wait", action="store_true")
        parser.add_argument("-x", "--specific-device", help="Specific device to watch for (<vendor-id>:<product-id>)",
                            type=str, action="append", dest="specific_device")
        parser.add_argument("-w", "--wait-on-shutdown", help="Wait for a new domain on domain shutdown. (Do not exit)",
                            dest="wait_on_shutdown", action="store_true")
        parser.add_argument("--usb-version", help="USB Controller version (defaults to 3)", type=int, default=None,
                            choices=range(1, 4))
        parser.add_argument("-l", "--log-file", help="Output log file", type=str, default=None, dest="log_file")
        parser.add_argument("--no-daemon", help="Do not run as a daemon (run in foreground", type=bool,
                            dest="no_daemon", action="store_true")

        return parser

    def __load_from_config_file(self, config_file) -> None:
        config = yaml.safe_load(config_file)
        self.__domain = config['domain'] if 'domain' in config else None
        self.__qmp_socket = config['qmp-socket'] if 'qmp-socket' in config else None
        self.__no_wait = not config['wait-for-domain'] if 'wait-for-domain' in config else False
        self.__wait_on_shutdown = config['wait-on-shutdown'] if 'wait-on-shutdown' in config else False
        self.__usb_version = config['usb-version'] if 'usb-version' in config else 3
        self.__hubs = config['hubs'] if 'hubs' in config else []
        self.__specific_devices = config['devices'] if 'devices' in config else []
        self.__log_file = config['log-file'] if 'log-file' in config else None
        self.__no_daemon = config['no-daemon'] if 'no-daemon' in config else False

    def __init__(self, args: List[str]):
        self.__wrapper_name = os.environ.get("WRAPPER") or args[0]
        parser = self.__get_argument_parser()
        parsed = parser.parse_args(args[1:])
        self.__verbosity = -1 if parsed.quiet else parsed.verbose

        if parsed.config is not None:
            self.__load_from_config_file(parsed.config)

        self.__domain = parsed.domain or self.__domain
        if parsed.hub is not None:
            self.__hubs.extend(parsed.hub)
        self.__qmp_socket = parsed.qmp_socket or self.__qmp_socket
        self.__no_wait = parsed.no_wait if parsed.no_wait else self.__no_wait
        self.__args = args
        if parsed.specific_device is not None:
            self.__specific_devices.extend(parsed.specific_device)
        self.__wait_on_shutdown = parsed.wait_on_shutdown if parsed.wait_on_shutdown else self.__wait_on_shutdown
        self.__usb_version = parsed.usb_version or self.__usb_version
        self.__log_file = parsed.log_file or self.__log_file
        self.__no_daemon = parsed.no_daemon or self.__no_daemon

        if self.__domain is None:
            parser.error("Must specify the domain to watch")

        if len(self.__hubs) == 0 and len(self.__specific_devices) == 0:
            parser.error("Must specify at least one --hub or --specific-device")

        self.__log_output = open(self.__log_file, "a") if self.__log_file else sys.stdout

        self.print_debug(f"Program name: {self.__wrapper_name}")
        self.print_unless_quiet("Settings:")
        self.print_unless_quiet("Verbosity: {}".format("Very Verbose" if self.is_very_verbose else
                                                       "Verbose" if self.is_verbose else
                                                       "Quiet" if self.is_quiet else "Normal"))
        self.print_unless_quiet(f"Domain: {self.domain}")
        self.print_unless_quiet(f"Hubs: {self.hubs}")
        self.print_unless_quiet(f"No Wait: {self.no_wait}")
        self.print_unless_quiet(f"Specific Devices: {self.specific_devices}")
        self.print_unless_quiet(f"Wait on Shutdown: {self.wait_on_shutdown}")
        self.print_unless_quiet(f"QMP socket: {self.qmp_socket}")
        self.print_unless_quiet(f"Log file: {self.log_file}")
        self.print_unless_quiet(f"No daemon: {self.no_daemon}")

    def __repr__(self):
        return f"Options({self.__args!r})"
