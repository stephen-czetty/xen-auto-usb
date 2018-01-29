from typing import Dict


class PriorityDict:
    @property
    def data(self):
        return self.__data

    @property
    def priority(self):
        return self.__priority

    def __init__(self, priority: int, data: Dict[str, str]):
        self.__priority = priority
        self.__data = data

    def __repr__(self):
        return "PriorityDict({!r}, {!r})".format(self.__priority, self.__data)

    def __eq__(self, other):
        return self.priority == other.priority

    def __ne__(self, other):
        return self.priority != other.priority

    def __lt__(self, other):
        return self.priority < other.priority

    def __le__(self, other):
        return self.priority <= other.priority

    def __gt__(self, other):
        return self.priority > other.priority

    def __ge__(self, other):
        return self.priority >= other.priority

