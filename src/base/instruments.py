from abc import ABCMeta, abstractmethod
from concurrent.futures import Future
from typing import Annotated, Any, ClassVar

from src.utils.async_com import COM


class UsesSerial(metaclass=ABCMeta):
    @abstractmethod
    def initialize(self) -> Future[Any]:
        ...


class Movable(metaclass=ABCMeta):
    STEPS_PER_UM: ClassVar[int | float]
    RANGE: ClassVar[tuple[int, int]]
    HOME: ClassVar[int]

    def __init__(self) -> None:
        assert self.STEPS_PER_UM and self.RANGE and self.HOME

    @property
    @abstractmethod
    def position(self) -> Future[int]:
        raise NotImplementedError

    def convert(self, p: Annotated[float, "mm"]) -> int:
        return int(p * 1000 * self.STEPS_PER_UM)


class FPGAControlled:
    fcom: COM

    def __init__(self, fpga_com: COM) -> None:
        self.fcom = fpga_com