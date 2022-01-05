from __future__ import annotations

from abc import ABCMeta, abstractmethod
from concurrent.futures import Future
from typing import Annotated, Any, ClassVar, NoReturn, final

from pyseq2.com.async_com import COM


class UsesSerial(metaclass=ABCMeta):
    com: COM

    @property
    def send(self):
        return self.com.send

    @abstractmethod
    def initialize(self) -> Future[Any]:
        ...

    @property
    def _executor(self) -> NoReturn:
        raise AttributeError  # Prevents executor outside COM.


class Movable(metaclass=ABCMeta):
    STEPS_PER_UM: ClassVar[int | float]
    RANGE: ClassVar[tuple[int, int]]
    HOME: ClassVar[int]

    @abstractmethod
    def move(self, p: int) -> Future[bool]:
        """
        Args:
            p (int): Target position

        Returns:
            Future[bool]: Future that resolves when move is completed.
        """

    @property
    @abstractmethod
    def pos(self) -> Future[int]:
        ...

    @pos.setter
    def pos(self, p: int) -> None:
        """Move that always block."""
        self.move(p).result()

    def convert(self, p: Annotated[float, "mm"]) -> int:
        return int(p * 1000 * self.STEPS_PER_UM)


class FPGAControlled:
    com: COM

    @final
    def __init__(self, fpga_com: COM) -> None:
        self.com = fpga_com

    @property
    def _executor(self) -> NoReturn:
        raise AttributeError
