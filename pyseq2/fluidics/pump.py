from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated, AsyncGenerator, Callable, ClassVar, Literal, TypeVar, cast

from pyseq2.base.instruments import UsesSerial
from pyseq2.com.async_com import COM, CmdParse
from pyseq2.utils.log import init_log
from pyseq2.utils.utils import IS_FAKE, ok_re

logger = logging.getLogger(__name__)


Sps = Annotated[int, "steps/sec"]
Step = Annotated[int, "step"]


def status_byte(s: str) -> bool:
    match s:
        case "@":
            return False
        case "`":
            return True
        case x:
            raise Exception(f"Pump has some error {x}.")


T = TypeVar("T")
parser = ok_re(r"/0([`@])", status_byte)


def check_range(prefix: Literal["pull", "push"]) -> Callable[[Step, Sps, bool], str]:
    def inner(pos: Step, sps: Sps = 8000, reverse: bool = False) -> str:
        if not 60 <= sps <= 8000:
            raise ValueError("Invalid speed. Range is [60, 8000].")
        if not 0 <= pos <= 48000:
            raise ValueError("Invalid position. Range is [0, 48000].")

        match (prefix, reverse):
            case ("pull", False) | ("push", True):
                return f"V{sps}IA{pos}R"
            case ("push", False) | ("pull", True):
                return f"V{sps}OA{pos}R"
            case _:
                raise ValueError("Invalid command.")

    return inner


class PumpCmd:
    """
    https://www.jascoint.co.jp/products/contact-angle/pdf/ap48.pdf
    R = Execute
    O = Set valve to output
    I = Set valve to input
    V = Set speed
    A = Set volume
    Instructions can be combined and finished with R.
    """

    INIT = CmdParse("W4R", parser)
    STATUS = CmdParse("", parser)
    GET_POS = CmdParse("?", ok_re(r"/0[`@](\d+)", int))
    PULL = CmdParse(check_range("pull"), parser)
    PUSH = CmdParse(check_range("push"), parser)
    STOP = CmdParse("T", parser)
    VALVE_OUT = CmdParse("OR", parser)
    VALVE_IN = CmdParse("IR", parser)


class Pump(UsesSerial):
    STEPS = 48000
    BARREL_VOL = 250
    PULL_SPEED = 1000
    PUSH_SPEED: ClassVar[Sps] = 8000

    @classmethod
    async def ainit(cls, name: Literal["pumpa", "pumpb"], port_tx: str) -> Pump:
        self = cls(cast(Literal["A", "B"], name[-1].upper()))
        self.com = await COM.ainit(name, port_tx)
        await self.com.send(PumpCmd.INIT)
        await asyncio.sleep(1)
        return self

    def __init__(self, name: Literal["A", "B"]) -> None:
        self.com: COM
        self.name = name

    async def wait(self, retries: int = 10) -> None:
        for _ in range(retries):
            if await self.com.send(PumpCmd.STATUS):
                return
            else:
                await asyncio.sleep(0.25)
        else:
            raise TimeoutError(f"Pump {self.name} not ready after too long.")

    @init_log(logger, "Pump")
    async def initialize(self) -> None:
        if await self.pos != 0:
            logger.info(f"Moving pump {self.name} to home.")
            await self._pushpull("push", 0)

    @property
    async def pos(self) -> int:
        return await self.com.send(PumpCmd.GET_POS)

    @property
    async def status(self) -> bool:
        return await self.com.send(PumpCmd.STATUS)

    async def _valve_waste(self) -> None:
        await self.com.send(PumpCmd.VALVE_OUT)

    async def _valve_flowcell(self) -> None:
        await self.com.send(PumpCmd.VALVE_IN)

    async def reset(self) -> None:
        await self.com.send(PumpCmd.PUSH(0, 8000, False))

    async def _pushpull(
        self,
        cmd: Literal["push", "pull"],
        target: int,
        *,
        speed: int = 8000,
        retries: int = 10,
        reverse: bool = False,
    ) -> None:
        async with self.com.big_lock:
            pos = await self.pos
            match cmd:
                case "pull":
                    if pos >= target:
                        raise ValueError(
                            f"Current pump pos of {pos} greater than the requested pos of {target}. Try reversing."
                        )
                    await self.com.send(PumpCmd.PULL(target, speed, reverse))
                case "push":
                    if pos <= target:
                        raise ValueError(
                            f"Current pump pos of {pos} smaller than the requested pos of {target}. Try reversing."
                        )
                    await self.com.send(PumpCmd.PUSH(target, speed, reverse))
                case _:
                    raise ValueError("Invalid command.")

        if not IS_FAKE():
            # logger.debug("Pump {self.name}: Waiting for pumping to finish.")
            await asyncio.sleep(abs(target - pos) / speed + 0.5)
        await self.wait(retries=retries)

    @asynccontextmanager
    async def _pump(
        self,
        vol: Step,
        *,
        v_pull: Sps = 400,
        v_push: Sps = 6400,
        reverse: bool = False,
    ) -> AsyncGenerator[None]:
        try:
            logger.info(f"Pump {self.name}:{' Reverse' if reverse else ''} Pulling. ")
            await self._pushpull("pull", vol, speed=v_pull, reverse=reverse)
            logger.info(f"Pump {self.name}:{' Reverse' if reverse else ''} Pull completed.")
            yield
        finally:
            logger.info(f"Pump {self.name}:{' Reverse' if reverse else ''} Pushing.")
            await self._pushpull("push", 0, speed=v_push, reverse=reverse)
            await self._valve_waste()
            logger.info(f"Pump {self.name}:{' Reverse' if reverse else ''} Push completed.")

    async def pump(
        self,
        vol: Step,
        *,
        v_pull: Sps = 400,
        v_push: Sps = 6400,
        wait: Annotated[float, "s"] = 26,
        reverse: bool = False,
    ) -> None:
        """Pump fluids. A combination of pull and push ops.
        Pulls to the amount of `vol` and then pushes back to 0 regardless of syringe position.

        Args:
            vol (Step): Volume to pull to.
            v_pull (Sps, optional): Defaults to 400.
            v_push (Sps, optional): Defaults to 6400.
            wait (Annotated[float, "Seconds"], optional): Wait time between push and pull to equalize pressure.
                Defaults to 26.
            reverse (bool, optional): Same operation but pulls from waste and pushes to flowcell. Defaults to False.
        """
        if (pos := await self.pos) != 0:
            logger.warning(f"Pump {self.name} was not fully pulled out at start but at pos {pos}.")

        async with self._pump(vol, v_pull=v_pull, v_push=v_push, reverse=reverse):
            logger.info(f"Pump {self.name}: Waiting for {wait} s.")
            await asyncio.sleep(wait)  # From HiSeq log. Wait for pressure to equalize.
