from typing import Callable


class Event:
    def __init__(self):
        self.__handlers = set()

    def __iadd__(self, handler: Callable) -> "Event":
        self.__handlers.add(handler)
        return self

    def __isub__(self, handler: Callable) -> "Event":
        self.__handlers.remove(handler)
        return self

    def __call__(self, *args, **kwargs):
        for handler in self.__handlers:
            handler(*args, **kwargs)

    def __len__(self):
        return len(self.__handlers)
