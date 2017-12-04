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

    async def fire(self, *args, **kwargs):
        for handler in self.__handlers:
            await handler(*args, **kwargs)

    def __await__(self):
        for async_handler in self.__handlers:
            async_handler().__await__()

    def __len__(self):
        return len(self.__handlers)

    def __repr__(self):
        return "Event()"
