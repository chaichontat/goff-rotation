from abc import ABCMeta, abstractmethod
from concurrent.futures import Future
from typing import Annotated, Any, ClassVar

from src.utils.com import COM


class UsesSerial(metaclass=ABCMeta):
    @abstractmethod
    def initialize(self) -> Future[Any]:
        ...


class Movable(metaclass=ABCMeta):
    STEPS_PER_UM: ClassVar[int | float]
    RANGE: ClassVar[tuple[int, int]]
    HOME: ClassVar[int]

    @property
    @abstractmethod
    def position(self) -> Future[int]:
        raise NotImplementedError

    # Mypy bug. https://github.com/python/mypy/issues/10872
    def convert(self, p: Annotated[float, "mm"]) -> int:  # type: ignore[name-defined]
        return int(p * 1000 * self.STEPS_PER_UM)


class FPGAControlled:
    fcom: COM

    def __init__(self, fpga_com: COM) -> None:
        self.fcom = fpga_com
