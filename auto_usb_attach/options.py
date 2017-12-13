from typing import List, Optional
import argparse


class Options:
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

    def print_debug(self, string: str):
        if self.is_debug:
            print("Debug: {}".format(string))

    def print_very_verbose(self, string: str):
        if self.is_very_verbose:
            print(string)

    def print_verbose(self, string: str):
        if self.is_verbose:
            print(string)

    def print_unless_quiet(self, string: str):
        if not self.is_quiet:
            print(string)

    @staticmethod
    def __get_argument_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()

        verbosity_group = parser.add_mutually_exclusive_group()
        verbosity_group.add_argument("-v", "--verbose", help="increase verbosity", action="count", default=0)
        verbosity_group.add_argument("-q", "--quiet", help="be very quiet", action="store_true")
        required_group = parser.add_argument_group("required arguments")
        required_group.add_argument("-d", "--domain", help="domain name to monitor", type=str, action="store",
                                    required=True)
        parser.add_argument("-u", "--hub", help="usb hub to monitor (for example, \"usb3\", \"1-1\")\n"
                                                "can be specified multiple times", type=str, action="append")
        parser.add_argument("-s", "--qmp-socket", help="UNIX domain socket to connect to", type=str, dest="qmp_socket",
                            default=None)
        parser.add_argument("-n", "--no-wait", help="Do not wait for the domain, exit immediately if it's not running",
                            dest="no_wait", action="store_true")
        parser.add_argument("-x", "--specific-device", help="Specific device to watch for (<vendor-id>:<product-id>)",
                            type=str, action="append")

        return parser

    def __init__(self, args: List[str]):
        parser = self.__get_argument_parser()
        parsed = parser.parse_args(args)

        if parsed.hub is None and parsed.specific_device is None:
            parser.error("Must specify at least one --hub or --specific-device")

        self.__verbosity = -1 if parsed.quiet else parsed.verbose
        self.__domain = parsed.domain
        self.__hubs = parsed.hub or []
        self.__qmp_socket = parsed.qmp_socket
        self.__no_wait = parsed.no_wait
        self.__args = args
        self.__specific_devices = parsed.specific_device or []

        self.print_very_verbose("Command line arguments:")
        self.print_very_verbose("Verbosity: {}".format("Very Verbose" if self.is_very_verbose else
                                                       "Verbose" if self.is_verbose else
                                                       "Quiet" if self.is_quiet else "Normal"))
        self.print_very_verbose("Domain: {}".format(self.domain))
        self.print_very_verbose("Hubs: {}".format(self.hubs))
        self.print_very_verbose("No Wait: {}".format(self.no_wait))
        self.print_very_verbose("Specific Devices: {}".format(self.specific_devices))

    def __repr__(self):
        return "Options({!r})".format(self.__args)
