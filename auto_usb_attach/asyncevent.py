from typing import Callable


class AsyncEvent:
    def __init__(self):
        self.__handlers = set()

    def __iadd__(self, handler: Callable) -> "AsyncEvent":
        self.__handlers.add(handler)
        return self

    def __isub__(self, handler: Callable) -> "AsyncEvent":
        self.__handlers.remove(handler)
        return self

    async def fire(self, *args, **kwargs) -> None:
        for handler in self.__handlers:
            await handler(*args, **kwargs)

    def __len__(self):
        return len(self.__handlers)

    def __repr__(self):
        return "AsyncEvent()"
