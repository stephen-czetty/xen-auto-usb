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
    def qmp_socket(self) -> Optional[str]:
        return self.__qmp_socket

    def print_debug(self, string: str):
        if self.is_debug:
            print(string)

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
        required_group.add_argument("-u", "--hub", help="usb hub to monitor (for example, \"usb3\", \"1-1\")\n"
                                                        "can be specified multiple times", type=str,
                                    action="append", required=True)
        parser.add_argument("--qmp-socket", help="UNIX domain socket to connect to", type=str, dest="qmp_socket",
                            default=None)

        return parser

    def __init__(self, args: List[str]):
        parser = self.__get_argument_parser()
        parsed = parser.parse_args(args)
        self.__verbosity = -1 if parsed.quiet else parsed.verbose
        self.__domain = parsed.domain
        self.__hubs = parsed.hub
        self.__qmp_socket = parsed.qmp_socket
        self.__args = args

        self.print_very_verbose("Command line arguments:")
        self.print_very_verbose("Verbosity: {}".format("Very Verbose" if self.is_very_verbose else
                                                       "Verbose" if self.is_verbose else
                                                       "Quiet" if self.is_quiet else "Normal"))
        self.print_very_verbose("Domain: {}".format(self.domain))
        self.print_very_verbose("Hubs: {}".format(self.hubs))

    def __repr__(self):
        return "Options({!r})".format(self.__args)
