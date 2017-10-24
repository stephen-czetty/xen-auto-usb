from typing import List
import argparse


class Options:
    @property
    def is_verbose(self) -> bool:
        return self.__verbosity > 0

    @property
    def is_very_verbose(self) -> bool:
        return self.__verbosity > 1

    @property
    def is_quiet(self) -> bool:
        return self.__verbosity < 0

    @property
    def domain(self) -> str:
        return self.__domain

    @property
    def hubs(self) -> List[str]:
        return self.__hubs

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

        group = parser.add_mutually_exclusive_group()
        group.add_argument("-v", "--verbose", help="increase verbosity", action="count", default=0)
        group.add_argument("-q", "--quiet", help="be very quiet", action="store_true")
        parser.add_argument("-d", "--domain", help="domain name to monitor", type=str, action="store", required=True)
        parser.add_argument("-u", "--hub", help="usb hub to monitor (for example, \"usb3\", \"1-1\")", type=str,
                            action="append", required=True)

        return parser

    def __init__(self, args: List[str]):
        parser = self.__get_argument_parser()
        parsed = parser.parse_args(args)
        self.__verbosity = -1 if parsed.quiet else parsed.verbose
        self.__domain = parsed.domain
        self.__hubs = parsed.hub

        self.print_very_verbose("Command line arguments:")
        self.print_very_verbose("Verbosity: {0}".format("Very Verbose" if self.is_very_verbose else
                                                        "Verbose" if self.is_verbose else
                                                        "Quiet" if self.is_quiet else "Normal"))
        self.print_very_verbose("Domain: {0}".format(self.domain))
        self.print_very_verbose("Hubs: {0}".format(self.hubs))
