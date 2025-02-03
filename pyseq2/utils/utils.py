from __future__ import annotations

import os
import re
from typing import Any, Callable, Container, Literal, ParamSpec, Sequence, TypeVar, cast, overload

FlowCell = Literal["A", "B"]
IS_FAKE = lambda: os.name != "nt" or os.environ.get("FAKE_HISEQ", "0") == "1"

T, P = TypeVar("T"), ParamSpec("P")


# https://python-3-patterns-idioms-test.readthedocs.io/en/latest/Metaprogramming.html#intercepting-class-creation
class Singleton(type):
    instance = None

    def __call__(cls, *args: Any, **kwargs: Any) -> Singleton:
        if not cls.instance:
            cls.instance = super().__call__(*args, **kwargs)
        return cls.instance


class InvalidResponse(Exception): ...


class ParamChangeTimeout(Exception): ...


def ok_if_match(expected: Container[str] | str, exception_on_fail: bool = True) -> Callable[[str], bool]:
    def wrapped(resp: str) -> bool:
        if resp == expected:
            return True
        if not isinstance(expected, str) and isinstance(expected, Sequence) and resp in expected:
            return True
        if exception_on_fail:
            raise InvalidResponse(f"Got {resp}, expected {expected}.")
        return False

    return wrapped


def ok_re(target: str, f: Callable[..., T] = bool) -> Callable[[str], T]:
    """f is your responsibility."""
    r = re.compile(target)

    def inner(resp: str) -> T:
        match = r.search(resp)
        if match is None:
            raise InvalidResponse(f"Got {resp}, expected to match {target}.")
        if r.groups < 2:
            return f(match.group(r.groups))
        return f(*(match.group(i) for i in range(1, r.groups + 1)))

    return inner


def chkrng(f: Callable[P, T], min_: float, max_: float, argnum: int = 0) -> Callable[P, T]:
    """Check the (x := first argument) of a function if min_ <= x <= max."""

    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        x = cast(float, args[argnum])
        if not (min_ <= x <= max_):
            raise ValueError(f"Invalid value for {f.__name__}: Got {x}. Expected [{min_}, {max_}].")
        return f(*args, **kwargs)

    return wrapper


# async def until(
#     cond: Callable[[], Awaitable[bool]],
#     attempts: int = 120,
#     gap: float = 1,
# ) -> None:
#     for _ in range(attempts):
#         if await cond():
#             return
#         await asyncio.sleep(gap)
#     else:
#         raise ParamChangeTimeout(f"Timeout after {attempts} attempts.")


@overload
def λ_int(λ: Callable[[Any, Any], T]) -> Callable[[int, int], T]: ...


@overload
def λ_int(λ: Callable[[Any], T]) -> Callable[[int], T]: ...


def λ_int(λ: Callable[[Any], T] | Callable[[Any, Any], T]) -> Callable[[int], T] | Callable[[int, int], T]:
    def inner(*args: int) -> T:
        return λ(*args)

    return inner


IntFloat = float


@overload
def λ_float(λ: Callable[[Any, Any], T]) -> Callable[[IntFloat, IntFloat], T]: ...


@overload
def λ_float(λ: Callable[[Any], T]) -> Callable[[IntFloat], T]: ...


def λ_float(
    λ: Callable[[Any], T] | Callable[[Any, Any], T],
) -> Callable[[IntFloat], T] | Callable[[IntFloat, IntFloat], T]:
    def inner(*args: IntFloat) -> T:
        return λ(*args)

    return inner


def λ_str(λ: Callable[[Any], T]) -> Callable[[str], T]:
    def inner(*args: str) -> T:
        return λ(*args)

    return inner
