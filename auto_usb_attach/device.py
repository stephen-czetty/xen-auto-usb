from typing import Iterable
import pyudev


class Device:
    @property
    def device_path(self) -> str:
        return self.__inner.device_path

    @property
    def busnum(self) -> int:
        return int(self.__inner.attributes.get('busnum'))

    @property
    def devnum(self) -> int:
        return int(self.__inner.attributes.get('devnum'))

    @property
    def vendor_id(self) -> str:
        return str(self.__inner.attributes.get('idVendor'), "ascii")

    @property
    def product_id(self) -> str:
        return str(self.__inner.attributes.get('idProduct'), "ascii")

    @property
    def sys_name(self) -> str:
        return self.__inner.sys_name

    @property
    def action(self) -> str:
        return self.__inner.action

    @property
    def children(self) -> Iterable["Device"]:
        return (Device(x) for x in self.__inner.children)

    def is_a_hub(self) -> bool:
        return "bDeviceClass" in self.__inner.attributes.available_attributes \
               and int(self.__inner.attributes.get("bDeviceClass"), 16) == 9

    def is_a_root_device(self) -> bool:
        return "bDeviceClass" in self.__inner.attributes.available_attributes

    def __init__(self, inner: pyudev.Device):
        self.__inner = inner

    def __repr__(self):
        return "Device(pyudev.{!r})".format(self.__inner)
