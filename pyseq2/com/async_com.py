from __future__ import annotations

import asyncio
import re
import time
from asyncio import CancelledError, Future, StreamReader, StreamWriter
from dataclasses import dataclass
from logging import getLogger
from typing import Annotated, Any, Callable, Generic, NamedTuple, NoReturn, ParamSpec, TypeVar, overload

from serial_asyncio import open_serial_connection

from pyseq2.base.instruments_types import COLOR, FORMATTER, SEPARATOR, SerialInstruments
from pyseq2.fakes.fake_serial import FakeOptions, open_fake
from pyseq2.utils.utils import IS_FAKE, InvalidResponse

logger = getLogger(__name__)
# © is not in ASCII. Looking at you Schneider Electrics (x-stage).
ENCODING_KW = {"encoding": "ISO-8859-1", "errors": "strict"}

T = TypeVar("T", covariant=True)
P = ParamSpec("P")


class Channel(NamedTuple):
    reader: StreamReader
    writer: StreamWriter


@dataclass(frozen=True)
class CmdParse(Generic[P, T]):
    """A command with its parsing function.

    If the command is callable, this entire structure is callable and
    outputs the same structure but with an `str` command.

    Args:
        cmd: String command or a unary function that outputs a command.
        parser: A unary function that takes in raw output from the device and parse it into a useful format.
        n_lines: Number of lines in the expected response.

    Returns:
        A data structure in which a command and its parsing function are together.
    """

    cmd: str | Callable[P, str]
    parser: Callable[[str], T] | None
    delayed_parser: Callable[[str], T] | None = None
    n_lines: int = 1
    timeout: float | None = 5
    # If you're adding some new variables don't forget to add them to __call__.

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> CmdParse[P, T]:
        if isinstance(self.cmd, str):
            raise TypeError("This command does not take argument(s).")
        return CmdParse(
            self.cmd(*args, **kwargs),
            self.parser,
            delayed_parser=self.delayed_parser,
            n_lines=self.n_lines,
            timeout=self.timeout,
        )

    def __str__(self) -> str:
        return str(self.cmd)


class COM:
    """
    Necessary conditions:
    - Commands are executed in FIFO order.
    - Response from an instrument is in FIFO order.
        **This is usually true except for `move` commands in which the instrument is
          programmed to respond on completion**

    - All responses are accounted for.

    Specific to each COM channel.

    Args:
        name (SerialInstruments): Name of the instrument.
        port_tx (str): COM port.
        port_rx (Optional[str], optional): Receiving port if different from port_tx.
            Only the FPGA uses separate channels.
        min_spacing (int, optional): Minimum time between commands. Defaults to 0.05s.
        no_check (bool, optional): Do not check for return values. Defaults to False.
    """

    FIRST_LINES = re.compile(
        "|".join(
            [
                r"@LOG The FPGA is now online.  Enjoy!",
                r"\??PR MV",
                r"\??PR P",
                r">EX 1",
                r"1R\([A-Z]{2}\)",
                r"1Z.*",
                r"@LOG Trigger Camera",
                r"@TILTPOS[123] \-?\d+",
            ]
        )
    )

    @classmethod
    async def ainit(
        cls,
        name: SerialInstruments,
        port_tx: str,
        port_rx: str | None = None,
        *,
        min_spacing: Annotated[float, "s"] = 0.01,
        no_check: bool = False,
        test_params: FakeOptions | None = None,
    ):
        baudrate = 115200 if name in ("fpga", "arm9chem", "arm9pe") else 9600
        if test_params is None:
            test_params = FakeOptions()
        self = cls(name, test_params, min_spacing, no_check)

        Streams = tuple[StreamReader, StreamWriter]
        if not IS_FAKE():  # Real instrument
            if port_rx is not None:
                assert name == "fpga"
                # Name and test_params is for fakeserial. Ignored in the real thing.
                srx: Streams = await open_serial_connection(url=port_rx, baudrate=baudrate)
                stx: Streams = await open_serial_connection(url=port_tx, baudrate=baudrate)
                self._serial = Channel(reader=srx[0], writer=stx[1])
                logger.info(f"{self.name}Started listening to ports {port_tx} and {port_rx}.")
            else:
                assert name != "fpga"
                self._serial = Channel(*await open_serial_connection(url=port_tx, baudrate=baudrate))
                logger.info(f"{self.name}Started listening to port {port_tx}.")

        else:  # Fake instrument
            self._serial = Channel(*await open_fake(port_tx, name, baudrate, test_params))
            logger.warning(f"{self.name}Started listening to fake ports.")

        asyncio.create_task(self._read_forever())
        return self

    def __init__(
        self,
        name: SerialInstruments,
        test_params: FakeOptions,
        min_spacing: Annotated[float, "s"] = 0.01,
        no_check: bool = False,
    ) -> None:

        self.name = f"[{COLOR[name]}]{name:10s}[/{COLOR[name]}]"
        self.formatter = FORMATTER[name]
        self.sep = SEPARATOR.get(name, b"\n")
        self.no_check = no_check
        self.test_params = test_params

        self.min_spacing = min_spacing
        self.t_lastcmd = time.monotonic()
        self.big_lock = asyncio.Lock()

        self._lock = asyncio.Lock()
        self._serial: Channel

        self._waiting: list[tuple[Callable[[str], Any], Future[Any]]] = list()

    async def _read_forever(self) -> NoReturn:
        buffer, rbuffer = "", b""
        while True:
            try:
                resp = (
                    (raw := await self._serial.reader.readuntil(self.sep))
                    .strip(b" \x03\r\n\xff")
                    .decode(**ENCODING_KW)
                )

                log_line = f"{self.name}[cyan]Raw: {str(raw)[2:-1]:20s}"

                if not resp:
                    continue

                if self.no_check:
                    logger.debug(log_line)
                    continue

                if buffer:
                    buffer += "\n" + resp
                    rbuffer += raw
                else:
                    buffer, rbuffer = resp, raw

                del resp

                for i in range(len(self._waiting)):
                    parser, fut = self._waiting[i]
                    try:
                        parsed = parser(buffer)
                    except InvalidResponse:
                        ...
                    else:
                        logger.debug(f"{log_line}[green]Parsed: '{parsed}'")
                        fut.set_result(parsed)
                        del self._waiting[i]
                        buffer, rbuffer = "", b""
                        break
                else:
                    if not self.FIRST_LINES.search(buffer):
                        temp = rbuffer
                        buffer, rbuffer = "", b""
                        raise InvalidResponse(f"{temp}")

            except (CancelledError, RuntimeError) as e:
                raise e
            except BaseException as e:
                logger.critical(f"{self.name}{type(e).__name__}: {e}")

    @overload
    async def send(self, cmd: str) -> None: ...

    @overload
    async def send(self, cmd: CmdParse[Any, T]) -> T: ...

    async def send(self, cmd: str | CmdParse[Any, T]) -> None | T:
        """Sends a command to an instrument.
        If msg is string   => no responses expected.
        If msg is CmdParse => response expected and parsed by CmdParse.parser.
            Unexpected response triggers a warning and returns Future[None].

        If msg is a list of either above, map this function to all elements.

        wait_next_cmd: bool = False. Current command can return _after_ the next command.
            Solution is to block the execution of the next command until this command is returned.

        Returns:
            None for msg, Future of a CmdParse result.
        """

        if isinstance(cmd, str):
            await self._send(self.formatter(cmd).encode(**ENCODING_KW))
            return None

        if not isinstance(cmd.cmd, str):
            raise ValueError("This command needs argument(s), call it first.")

        fut: Future[T] = asyncio.Future()

        # Need lock as reversal can happen when two closely spaced commands enter.
        # While the former is waiting for min_spacing, the later could arrive just a
        # little later to pass the min_spacing check without waiting.
        async with self._lock:
            if cmd.delayed_parser is not None:
                self._waiting.append((cmd.delayed_parser, fut))

            if cmd.parser is not None:
                fut_ = asyncio.Future() if cmd.delayed_parser is not None else fut  # type: ignore
                self._waiting.append((cmd.parser, fut_))  # type: ignore  # Dump future

            await self._send(self.formatter(cmd.cmd).encode(**ENCODING_KW))

        return await (asyncio.wait_for(self.catchable_future(fut, cmd), cmd.timeout) if cmd.timeout else fut)

    async def catchable_future(self, fut: asyncio.Future[T], cmd: CmdParse[Any, T]) -> T:
        try:
            return await fut
        except (asyncio.CancelledError, RuntimeError) as e:
            for w in self._waiting:
                if w[1] is fut:
                    self._waiting.remove(w)
                    break
            logger.error(f"{self.name} timeout after {cmd.timeout} s from {cmd.cmd}.")
            raise e

    async def _send(self, msg: bytes) -> None:
        """This needs to be synchronous to maintain order of execution.
        asyncio.Queue is not thread-safe and using an asynchronous function to queue things does not guarantee order.
        Enforces minimum delay between commands.
        Args:
            msg (bytes): Raw bytes to be sent. Usually encoded in ISO-8859-1.
        """
        if self.min_spacing:
            await asyncio.sleep(max(0, self.min_spacing - (time.monotonic() - self.t_lastcmd)))
        self._serial.writer.write(msg)
        self.t_lastcmd = time.monotonic()
        logger.debug(f"{self.name}[green]Tx:  {str(msg)[2:-1]}")

    async def wait(self) -> None:
        while self._waiting:
            await asyncio.sleep(0.1)
