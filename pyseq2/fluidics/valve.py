from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Literal

from pyseq2.base.instruments import Movable, UsesSerial
from pyseq2.base.instruments_types import ValveName
from pyseq2.com.async_com import COM, CmdParse
from pyseq2.config import CONFIG
from pyseq2.utils.log import init_log
from pyseq2.utils.utils import IS_FAKE, ok_re, λ_int

logger = logging.getLogger(__name__)

# fmt: off
class ValveCmd:
    ID          = CmdParse("ID", ok_re(r"ID = (.+)", lambda x: x))
    CLEAR_ID    = "*ID*"
    SET_POS     = λ_int(lambda x: f"GO{x}")
    GET_POS     = CmdParse("CP", ok_re(r"Position is  = (\d+)", int))
    GET_N_PORTS = CmdParse("NP", ok_re(r"NP = (\d+)", int))
# fmt: on


class ValveError(Exception): ...


class _Valve(Movable, UsesSerial):
    @classmethod
    async def ainit(cls, name: ValveName, port_tx: str) -> _Valve:
        n_ports = 24 if CONFIG.machine == "HiSeq2500" and name[-1] == "2" else 10
        self = cls(name, n_ports, await COM.ainit(name, port_tx))

        async with self.com.big_lock:
            if await self.com.send(ValveCmd.ID) != "not used":
                await self.com.send(ValveCmd.CLEAR_ID)
                if await self.com.send(ValveCmd.ID) != "not used":
                    raise ValveError(f"{name}: Already cleared ID but ID is still here.")
            if not IS_FAKE() and (n := await self.com.send(ValveCmd.GET_N_PORTS)) != self.n_ports:
                raise ValveError(
                    f"{name}: Number of ports is not {self.n_ports} as expected but {n}. Incorrect machine setting?"
                )

        return self

    def __init__(self, name: ValveName, n_ports: Literal[10, 24], com: COM) -> None:
        self.com = com
        self.n_ports = n_ports
        self.name = name
        self.t_lastcmd = 0.0

    async def initialize(self) -> None: ...

    @property
    async def pos(self) -> int:
        return await self.com.send(ValveCmd.GET_POS)

    async def move(self, pos: int) -> None:
        # If pos is the same as current position, will get `GO${p} = Bad command` as return.
        async with self.com.big_lock:  # Possible for valve to change after awaiting self.pos.
            if time.time() - self.t_lastcmd < 10.0:
                logger.warning(
                    "Time between valve moves is less than 10 seconds. Illumina does not like this."
                )
            if await self.pos == pos:
                return
            await self.com.send(ValveCmd.SET_POS(pos))
            self.t_lastcmd = time.time()
            if not IS_FAKE() and await self.pos != pos:
                raise Exception(f"Port {self.name} did not move to {pos}.")


class Valves(Movable):
    @classmethod
    async def ainit(cls, name: Literal["A", "B"], port1: str, port2: str) -> Valves:
        self = cls(name)
        match name:
            case "A":
                self.v = (await _Valve.ainit("valve_a1", port1), await _Valve.ainit("valve_a2", port2))
            case "B":
                self.v = (await _Valve.ainit("valve_b1", port1), await _Valve.ainit("valve_b2", port2))
        return self

    def __init__(self, name: Literal["A", "B"]) -> None:
        self.v: tuple[_Valve, _Valve]
        self.name = name
        self.lock = asyncio.Lock()
        self.fc_inlet: Literal[2, 8] = 8

    def __getitem__(self, i: Literal[0, 1]) -> _Valve:
        return self.v[i]

    @init_log(logger, "Valve")
    async def initialize(self) -> None:
        async with self.lock:
            # Valve initialization is intentionally empty.
            await asyncio.gather(self.v[0].initialize(), self.v[1].initialize())
            if CONFIG.machine == "HiSeq2500":
                await self.set_fc_inlet(8)

    @property
    async def pos(self) -> int:
        p1, p2 = await asyncio.gather(self[0].pos, self[1].pos)
        if CONFIG.machine == "HiSeq2000":
            if p1 == 9:
                return 0
            if p1 == 10:
                return p2 + 9
            return p1

        elif CONFIG.machine == "HiSeq2500":
            match p1:
                case 2 | 3 if self.name == "A":
                    return p2
                case 4 | 5 if self.name == "B":
                    return p2
                case _:
                    return 0  # In blocked position.

        else:
            raise AssertionError

    async def _move(self, p: int) -> None:
        async with self.lock:
            if CONFIG.machine == "HiSeq2000":
                match p:
                    case 0:
                        await self[0].move(9)
                    case x if 1 <= x <= 8:
                        await self[0].move(p)
                    case x if 10 <= x <= 19:
                        await asyncio.gather(self[0].move(10), self[1].move(p - 9))
                    case _:
                        raise ValueError("Invalid port number. Range is [1, 18], excluding 9.")

            elif CONFIG.machine == "HiSeq2500":
                match p:
                    case 0:
                        await self[0].move(6)  # Blocked position.
                    case x if 1 <= x <= 24:
                        await asyncio.gather(self.set_fc_inlet(self.fc_inlet), self[1].move(p))
                    case _:
                        raise ValueError("Invalid port number. Range is [1, 24].")
            else:
                raise AssertionError

        if not IS_FAKE() and (p_ := await self.pos) != p:
            raise ValveError(f"Valve did not move to {p}, stuck at {p_}.")

    async def move(self, pos: int) -> None:
        raise NotImplementedError("Use the async context manager move_port instead.")

    @asynccontextmanager
    async def move_port(self, pos: int) -> AsyncGenerator[None]:
        try:
            await self._move(pos)
            yield
        finally:
            await self._move(0)  # "Safe" position.

    async def set_fc_inlet(self, n: Literal[2, 8]) -> None:
        if CONFIG.machine != "HiSeq2500":
            raise NotImplementedError("This option is only valid for the HiSeq 2500.")
        if n == self.fc_inlet:
            return

        match self.name:
            case "A":
                await self[0].move(2 if n == 2 else 3)
            case "B":
                await self[0].move(4 if n == 2 else 5)
            case _:
                raise AssertionError

        self.fc_inlet = n
