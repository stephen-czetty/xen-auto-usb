from typing import List, Iterable
import pyudev


class Device:
    @property
    def device_path(self):
        return self.__inner.device_path

    @property
    def busnum(self):
        return int(self.__inner.properties['BUSNUM'])

    @property
    def devnum(self):
        return int(self.__inner.properties['DEVNUM'])

    @property
    def sys_name(self):
        return self.__inner.sys_name

    @property
    def action(self):
        return self.__inner.action

    @property
    def children(self):
        return (Device(x) for x in self.__inner.children)

    def is_a_hub(self) -> bool:
        return "bDeviceClass" in self.__inner.attributes.available_attributes \
               and int(self.__inner.attributes.get("bDeviceClass"), 16) == 9

    def is_a_root_device(self) -> bool:
        return "bDeviceClass" in self.__inner.attributes.available_attributes

    def is_a_device_we_care_about(self, devices_to_monitor: List['Device']) -> bool:
        for monitored_device in devices_to_monitor:
            if self.device_path.startswith(monitored_device.device_path):
                return not self.is_a_hub() and self.is_a_root_device()

        return False

    def devices_of_interest(self) -> Iterable['Device']:
        for d in self.children:
            if d.is_a_device_we_care_about([self]):
                yield d

    def __init__(self, inner: pyudev.Device):
        self.__inner = inner

    def __repr__(self):
        return self.__inner.__repr__()
