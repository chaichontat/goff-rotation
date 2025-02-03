from logging import getLogger
from typing import Optional, overload

Y_UPPER = -180000
A_LEFT = 7331
B_LEFT = 33070
X_STEP_MM = 409.6
Y_STEP_MM = 1e5

logger = getLogger(__name__)


@overload
def raw_to_mm(flowcell: bool, *, x: int, y: None = None) -> float: ...


@overload
def raw_to_mm(flowcell: bool, *, y: int, x: None = None) -> float: ...


@overload
def raw_to_mm(flowcell: bool, *, x: int, y: int) -> tuple[float, float]: ...


@overload
def raw_to_mm(flowcell: bool, *, x: None = None, y: None = None) -> None: ...


def raw_to_mm(
    flowcell: bool, x: Optional[int] = None, y: Optional[int] = None
) -> None | tuple[float, float] | float:
    x_offset = B_LEFT if flowcell else A_LEFT

    if x is not None and y is not None:
        return ((x - x_offset) / X_STEP_MM, (y - Y_UPPER) / Y_STEP_MM)
    if x is not None:
        return (x - x_offset) / X_STEP_MM
    if y is not None:
        return (y - Y_UPPER) / Y_STEP_MM
    return None


@overload
def mm_to_raw(flowcell: bool, *, x: float, y: None = None) -> int: ...


@overload
def mm_to_raw(flowcell: bool, *, y: float, x: None = None) -> int: ...


@overload
def mm_to_raw(flowcell: bool, *, x: float, y: float) -> tuple[int, int]: ...


@overload
def mm_to_raw(flowcell: bool, *, x: None = None, y: None = None) -> None: ...


def mm_to_raw(
    flowcell: bool, *, x: Optional[float] = None, y: Optional[float] = None
) -> None | int | tuple[int, int]:
    x_offset = B_LEFT if flowcell else A_LEFT

    # if x is not None and not (-5 <= x <= 30):
    #     logger.warning(f"x={x} is out of range.")
    # if y is not None and not (-5 <= y <= 80):
    #     logger.warning(f"y={y} is out of range.")

    if x is not None and y is not None:
        return (int(x * X_STEP_MM + x_offset), int(y * Y_STEP_MM + Y_UPPER))
    if x is not None:
        return int(x * X_STEP_MM + x_offset)
    if y is not None:
        return int(y * Y_STEP_MM + Y_UPPER)
    return None
