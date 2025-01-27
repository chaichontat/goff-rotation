from __future__ import annotations

import asyncio
import math
import os
from abc import ABCMeta, abstractmethod
from logging import getLogger
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar, cast

import numpy as np
from pydantic import BaseModel, Field, validator

from pyseq2.experiment.reagent import Reagent
from pyseq2.flowcell import Celsius, FlowCells, Seconds, μL
from pyseq2.imager import Imager, UInt16Array, mW
from pyseq2.utils import coords

__all__ = ["Pump", "Prime", "Temp", "Hold", "Autofocus", "TakeImage", "Goto"]
logger = getLogger(__name__)

T = TypeVar("T")

mm = Annotated[float, "mm"]


class AbstractCommand(metaclass=ABCMeta):
    op: str

    @abstractmethod
    async def run(self, fcs: FlowCells, i: bool, imager: Imager) -> Any: ...

    @classmethod
    @abstractmethod
    def default(cls: type[T]) -> T: ...


async def pump_prime(fcs: FlowCells, i: bool, cmd: Pump | Prime):
    if not isinstance(r := cmd.reagent, Reagent):
        raise ValueError(
            "Individual command needs an actual Reagent, not its name. To fix: cmd.reagent = reagents[name]."
        )

    fc = fcs[cast(Literal[0, 1], i)]
    match cmd.op:
        case "prime":
            await fc.flow(r.port, cmd.volume, v_pull=r.v_prime, v_push=r.v_push, wait=r.wait)
        case "pump":
            await fc.flow(r.port, cmd.volume, v_pull=r.v_pull, v_push=r.v_push, wait=r.wait)
        case _:
            raise ValueError("Invalid command.")


class Pump(BaseModel, AbstractCommand):
    reagent: str | Reagent
    volume: μL = 250
    inlet: Literal[2, 8] = 8
    op: Literal["pump"] = "pump"

    async def run(self, fcs: FlowCells, i: bool, imager: Imager) -> None:
        await pump_prime(fcs, i, self)

    @classmethod
    def default(cls) -> Pump:
        return Pump(reagent="water")

    def __str__(self) -> str:
        if isinstance(self.reagent, Reagent):
            return f"Pump `{self.reagent.name}`"
        return f"Pump `{self.reagent}`"


class Prime(BaseModel, AbstractCommand):
    reagent: str | Reagent
    volume: μL = 250
    inlet: Literal[2, 8] = 8
    op: Literal["prime"] = "prime"

    async def run(self, fcs: FlowCells, i: bool, imager: Imager) -> None:
        await pump_prime(fcs, i, self)

    @classmethod
    def default(cls) -> Prime:
        return Prime(reagent="water")

    def __str__(self) -> str:
        if isinstance(self.reagent, Reagent):
            return f"Prime `{self.reagent.name}`"
        return f"Prime `{self.reagent}`"


class Temp(BaseModel, AbstractCommand):
    temp: Celsius
    wait: bool = False
    tol: Celsius = 3.0
    timeout: Seconds = 60.0
    op: Literal["temp"] = "temp"

    async def run(self, fcs: FlowCells, i: bool, imager: Imager) -> None:
        fc = fcs[cast(Literal[0, 1], i)]
        await fc.set_temp(self.temp)
        if self.wait:
            while abs(await fc.temp - self.temp) > self.tol:
                await asyncio.sleep(0.5)

    @classmethod
    def default(cls) -> Temp:
        return Temp(temp=25)

    def __str__(self) -> str:
        return f"Wait temp to {self.temp}"


class Hold(BaseModel, AbstractCommand):
    time: Seconds
    op: Literal["hold"] = "hold"

    async def run(self, fcs: FlowCells, i: bool, imager: Imager) -> None:
        await asyncio.sleep(self.time)

    @classmethod
    def default(cls) -> Hold:
        return Hold(time=1)

    def __str__(self) -> str:
        return f"Hold {self.time} s"


class Autofocus(BaseModel, AbstractCommand):
    channel: Literal[0, 1, 2, 3]
    laser_onoff: bool
    laser: mW
    od: float
    op: Literal["autofocus"] = "autofocus"

    async def run(
        self, fcs: FlowCells, i: bool, imager: Imager
    ) -> tuple[int, np.ndarray[Literal[259], np.dtype[np.float64]], UInt16Array]:
        return await imager.autofocus(self.channel)

    @classmethod
    def default(cls) -> Autofocus:
        return Autofocus(channel=0, laser_onoff=True, laser=5, od=0.0)

    def __str__(self) -> str:
        return f"Autofocus channel {self.channel}"


class TakeImage(BaseModel, AbstractCommand):
    name: str
    path: str
    xy0: tuple[mm, mm]
    xy1: tuple[mm, mm]
    overlap: float
    channels: tuple[bool, bool, bool, bool]
    z_tilt: int | tuple[int, int, int]
    z_obj: int
    laser_onoff: tuple[bool, bool]
    lasers: tuple[mW, mW]
    od: tuple[float, float]
    save: bool
    z_spacing: int = 232
    z_from: int = 0
    z_to: int = 0
    op: Literal["takeimage"] = "takeimage"

    @classmethod
    def default(cls) -> TakeImage:
        return TakeImage(
            name="",
            path=os.getcwd(),
            xy0=(0.0, 0.0),
            xy1=(1.0, 0.3),
            overlap=0.1,
            channels=(True, True, True, True),
            z_tilt=19850,
            z_obj=20000,
            laser_onoff=(True, True),
            lasers=(5, 5),
            od=(0.0, 0.0),
            save=False,
            z_spacing=232,
            z_from=0,
            z_to=0,
        )

    @validator("overlap")
    def val_overlap(cls, v: float) -> float:
        assert 0.0 <= v < 1.0, "Overlap must be between 0 and 1."
        return v

    def calc_pos(self, i: bool) -> tuple[int, int, list[int], list[int]]:
        # mm
        xs = self.xy0[0], self.xy1[0]  # Left edges
        ys = self.xy0[1], self.xy1[1]  # Bottom edges

        n_bundles = math.ceil((max(ys) - min(ys)) / 0.048)

        x_step = 0.768 * (1 - self.overlap)
        x_start, x_end = min(xs), max(xs) + 0.768
        x_n = math.ceil((x_end - x_start) / x_step) if self.xy0[0] != self.xy1[0] else 1

        # raw
        y_start = coords.mm_to_raw(i, y=max(ys))
        xs = [coords.mm_to_raw(i, x=x_start + n * x_step) for n in range(x_n)]
        zs = [self.z_obj + n * self.z_spacing for n in range(self.z_from, self.z_to + 1)]

        return n_bundles, y_start, xs, zs

    async def run(
        self, fcs: FlowCells, i: bool, imager: Imager, q: asyncio.Queue[tuple[int, int, int]] | None = None
    ) -> UInt16Array:
        logger.info("Started taking images.")

        save_tasks: list[asyncio.Task[None]] = []
        n_bundles, y_start, xs, zs = self.calc_pos(i)

        if not (n_bundles and len(xs) and len(zs)):
            raise ValueError("Invalid number of bundles, x, or z.")

        channels = tuple(i for i, c in enumerate(self.channels) if c)

        path = Path(self.path) / self.name
        paths = [path.parent / f"{path.stem}_{i}.tif" for i in range(len(xs))]
        # Test if we can write to the directory
        print(paths)
        if self.save:
            path.parent.mkdir(parents=True, exist_ok=True)
            [p.touch() for p in paths]

        big_img = np.empty((len(zs), len(channels), 128 * n_bundles, 2048), dtype=np.uint16)
        for ix, (p, x) in enumerate(zip(paths, xs)):
            for iz, z in enumerate(zs):
                logger.info(f"Imaging [{iz+1}/{len(zs)}z {ix+1}/{len(xs)}x] at {x=} y={y_start} {z=}.")
                await imager.move(x=x, y=y_start, z_obj=z, z_tilt=self.z_tilt)
                img, _ = await imager.take(
                    n_bundles,
                    channels=channels,
                    event_queue=None if q is None else (q, lambda i: (i, iz, ix)),
                )
                big_img[iz] = img
            if self.save:
                save_tasks.append(
                    asyncio.create_task(imager.save(p, big_img.copy()))
                )  # TODO state per each stack.

        if q is not None:
            q.put_nowait((n_bundles, len(zs), len(xs)))  # Make it look pleasing at the end.
        if self.save:
            logger.info("Saving to file.")
            await asyncio.gather(*save_tasks)
        logger.info("Done capture/preview.")
        # await asyncio.sleep(0.1)  # For logs to sync up.
        bin_size = (1 << (n_bundles // 16).bit_length()) >> 1 if n_bundles > 16 else 2
        return (
            big_img[0]
            .reshape((len(channels), (128 * n_bundles) // bin_size, bin_size, 2048 // bin_size, bin_size))
            .max(4)
            .max(2)
        )  # Max pooling

    def __str__(self) -> str:
        return f"Take image `{self.name}`"


class Goto(BaseModel, AbstractCommand):
    step: int
    n: int
    op: Literal["goto"] = "goto"

    async def run(self, fcs: FlowCells, i: bool, imager: Imager) -> None:
        raise NotImplementedError("Goto cannot run.")

    @classmethod
    def default(cls) -> Goto:
        return Goto(step=1, n=1)

    @validator("step")
    def val_step(cls, v: int) -> int:
        assert v > 0, "Step must be greater than 0."
        return v

    @validator("n")
    def val_n(cls, v: int) -> int:
        assert v > 0, "n must be greater than 0."
        return v


Cmd = Annotated[Pump | Prime | Temp | Hold | Autofocus | TakeImage | Goto, Field(discriminator="op")]
