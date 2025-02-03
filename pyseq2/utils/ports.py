# %%
import asyncio
import logging
from pprint import pprint
from typing import TypeVar, cast

import serial.tools.list_ports

from pyseq2.base.instruments_types import SerialPorts
from pyseq2.utils.utils import IS_FAKE

T = TypeVar("T")
logger = logging.getLogger(__name__)

serial_names: dict[SerialPorts, str] = dict(
    x="IL000001A",
    y="IL000002A",
    laser_g="IL000006A",
    laser_r="IL000007A",
    arm9chem="ARM9CHEMA",
    arm9pe="PCIOA",
    pumpa="KLOEHNAA",
    pumpb="KLOEHNBA",
    valve_a1="VICIA1A",
    valve_a2="VICIA2A",
    valve_b1="VICIB1A",
    valve_b2="VICIB2A",
    fpgacmd="IL000004A",
    fpgaresp="IL000005A",
)  # type: ignore # Dict is invariant.


FAKE_PORTS: dict[SerialPorts, str] = {name: "COMX" for name in serial_names}


async def get_ports(show_all: bool = False) -> dict[SerialPorts, str]:
    """
    See https://pyserial.readthedocs.io/en/latest/tools.html for more details.

    Returns:
        Ports: Dataclass of relevant components and their COM ports.
    """
    if IS_FAKE():
        logger.warning("Using fake ports.")

    ports = (
        cast(
            dict[str, str],
            {
                dev.serial_number: dev.name  # {serial_number: ports}
                for dev in await asyncio.get_running_loop().run_in_executor(
                    None, serial.tools.list_ports.comports
                )
                if dev.serial_number is not None
            },
        )
        if not IS_FAKE()
        else {id_: "COMX" for id_ in serial_names.values()}
    )

    try:
        res = {name: ports[id_] for name, id_ in serial_names.items()}
        if show_all:
            pprint(f"{ports}")
        return cast(dict[SerialPorts, str], res)
    except KeyError as e:
        missing = [k for k, v in serial_names.items() if v == e.args[0]]
        raise RuntimeError(
            f"Cannot find {missing[0]}. If you are running a fake HiSeq, set the environment variable FAKE_HISEQ=1.",
            e.args[0],
        )
