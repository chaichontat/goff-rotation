from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Annotated, ClassVar

from pyseq2.com.async_com import COM


class UsesSerial(metaclass=ABCMeta):
    com: COM

    @abstractmethod
    async def initialize(self) -> None: ...


class Movable(metaclass=ABCMeta):
    STEPS_PER_UM: ClassVar[float]
    RANGE: ClassVar[tuple[int, int]]
    HOME: ClassVar[int]

    @abstractmethod
    async def move(self, pos: int) -> None:
        """
        Args:
            pos (int): Target position
        """

    @property
    @abstractmethod
    async def pos(self) -> int: ...

    def convert(self, p: Annotated[float, "mm"]) -> int:
        return int(p * 1000 * self.STEPS_PER_UM)


class FPGAControlled:
    com: COM

    # All FPGA modules use the same port. Need local locks for each class.
    def __init__(self, fpga_com: COM) -> None:
        self.com = fpga_com
