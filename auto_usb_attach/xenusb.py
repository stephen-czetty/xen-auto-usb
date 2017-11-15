class XenUsb:
    @property
    def controller(self) -> int:
        return self.__controller

    @property
    def port(self) -> int:
        return self.__port

    @property
    def hostbus(self) -> int:
        return self.__hostbus

    @property
    def hostaddr(self) -> int:
        return self.__hostaddr

    def __init__(self, controller, port, hostbus, hostaddr):
        self.__controller = controller
        self.__port = port
        self.__hostbus = hostbus
        self.__hostaddr = hostaddr

    def __eq__(self, other: "XenUsb") -> bool:
        return self.hostbus == other.hostbus and self.hostaddr == other.hostaddr

    def __repr__(self):
        return "XenUsb({!r}, {!r}, {!r}, {!r})".format(self.__controller, self.__port, self.__hostbus, self.__hostaddr)
