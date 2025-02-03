from __future__ import annotations

import asyncio
import pickle  # noqa: S403
import time
from contextlib import contextmanager
from ctypes import c_char_p, c_int32, c_uint32, c_void_p, pointer, sizeof
from enum import IntEnum
from logging import getLogger
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    Generic,
    Hashable,
    Literal,
    Mapping,
    MutableMapping,
    TypeVar,
    cast,
    get_args,
    overload,
)

import numpy as np
import numpy.typing as npt

from . import API, EXECUTOR
from .dcam_api import DCAMException
from .dcam_props import DCAMDict
from pyseq2.imaging.camera.dcam_api import DCAM_CAPTURE_MODE
from pyseq2.imaging.camera.dcam_types import Props
from pyseq2.utils.utils import IS_FAKE

logger = getLogger(__name__)


class Status(IntEnum):
    """dcamapi.h line 231"""

    ERROR = 0
    BUSY = 1
    READY = 2
    STABLE = 3
    UNSTABLE = 4


class SensorMode(IntEnum):
    AREA = 1
    LINE = 3
    TDI = 4
    PARTIAL_AREA = 6


ID = Literal[0, 1]
Cam = Literal[0, 1, 2]
UInt16Array = npt.NDArray[np.uint16]
FourImages = tuple[UInt16Array, UInt16Array, UInt16Array, UInt16Array]
ModeDict = Mapping[Props, float]


async def nothing() -> None:
    return None


class Mode:
    """DCAM properties preset"""

    FOCUS_SWEEP: ModeDict = {"sensor_mode": 6, "exposure_time": 0.001, "partial_area_vsize": 64}
    TDI: ModeDict = {"sensor_mode": 4, "sensor_mode_line_bundle_height": 128}


class _Camera:
    IMG_WIDTH = 4096
    BUNDLE_HEIGHT = 128

    @classmethod
    async def ainit(cls, id_: ID) -> _Camera:
        handle = c_void_p(0)
        await asyncio.get_running_loop().run_in_executor(
            EXECUTOR, lambda: API.dcam_open(pointer(handle), c_int32(id_), None)
        )
        properties = await asyncio.get_running_loop().run_in_executor(
            EXECUTOR, lambda: cls.init_properties(handle)
        )
        return cls(id_, handle, properties)

    def __init__(self, id_: ID, handle: c_void_p | None = None, properties: DCAMDict | None = None) -> None:
        assert id_ in get_args(ID)
        self.id_ = id_

        if handle is None:
            handle = c_void_p(0)
            API.dcam_open(pointer(handle), c_int32(id_), None)

        self.handle = handle
        if properties is None:
            properties = self.init_properties(handle)

        self.properties = properties
        self.capture_mode = DCAM_CAPTURE_MODE.SNAP
        logger.info(f"Connected to cam {id_}")

    @staticmethod
    def init_properties(handle: c_void_p) -> DCAMDict:
        if IS_FAKE():
            return DCAMDict(
                handle,
                pickle.loads((Path(__file__).parent / "saved_props.pk").read_bytes()),  # noqa: S301
            )
        else:
            return DCAMDict.from_dcam(handle)

    def initialize(self) -> None: ...

    @property
    def capture_mode(self) -> DCAM_CAPTURE_MODE:
        return self._capture_mode

    @capture_mode.setter
    def capture_mode(self, m: DCAM_CAPTURE_MODE) -> None:
        API.dcam_precapture(self.handle, m)
        self._capture_mode = m

    @contextmanager
    def capture(self) -> Generator[None]:
        API.dcam_capture(self.handle)
        logger.info(f"Cam {self.id_}: Started capturing.")
        try:
            yield
        finally:
            API.dcam_idle(self.handle)
            logger.info(f"Cam {self.id_}: Done capturing.")

    @property
    def status(self) -> Status:
        s = c_int32(-1)
        API.dcam_getstatus(self.handle, pointer(s))
        try:
            return Status(s.value)
        except ValueError:
            raise DCAMException(f"Invalid status. Got {s.value}.")

    @contextmanager
    def attach(self, n_bundles: int, dim: tuple[int, int]) -> Generator[UInt16Array]:
        """Generates a numpy array and "attach" it to the camera.
        Aka. Tells the camera to write captured bundles here.

        Args:
            n_bundles (int): Number of bundles
            height (tuple[int, int]): Dim of each bundle.

        Yields:
            Generator[UInt16Array, None, None]: Output array (n_bundles × height, dim[1])
        """
        arr: npt.NDArray[np.uint16] = np.zeros((n_bundles * dim[0], dim[1]), dtype=np.uint16)
        addr, ptr_arr = arr.ctypes.data, (c_void_p * n_bundles)()
        for i in range(n_bundles):
            # sizeof(uint16) * width * height
            ptr_arr[i] = 2 * dim[1] * dim[0] * i + addr

        try:
            API.dcam_attachbuffer(self.handle, ptr_arr, c_uint32(sizeof(ptr_arr)))
            yield arr
        finally:
            API.dcam_releasebuffer(self.handle)

    @property
    def n_frames_taken(self) -> int:
        """Return number of frames (int) that have been taken."""
        b_index, f_count = c_int32(-1), c_int32(-1)
        API.dcam_gettransferinfo(self.handle, pointer(b_index), pointer(f_count))
        return f_count.value


T = TypeVar("T", bound=Hashable)
R = TypeVar("R")


class TwoProps(Generic[T, R]):
    """Unified properties of two cameras"""

    def __init__(self, prop1: MutableMapping[T, R], prop2: MutableMapping[T, R]) -> None:
        self._props = (prop1, prop2)

    def __getitem__(self, name: T) -> R:
        a, b = self._props
        if (out := a[name]) != b[name]:
            raise Exception("Value not equal between two props. Check each individually.")
        return out

    def __setitem__(self, name: T, value: R) -> None:
        for p in self._props:
            p[name] = value

    def update(self, to_change: Mapping[T, R]):
        for k, v in to_change.items():
            self[k] = v


class Cameras:
    """Object representing two cameras.
    To access a single camera, index this object.
    `Cam = 0, 1` refers to cameras 0, 1. Whereas 2 refers to both.

    Experiments indicated that dcamapi.dll is not thread-safe."""

    IMG_WIDTH = 4096
    BUNDLE_HEIGHT = 128

    properties: TwoProps[str, float]

    @classmethod
    async def ainit(cls) -> Cameras:
        t0 = time.monotonic()
        logger.info("Initializing DCAM API.")
        fut = asyncio.get_running_loop().run_in_executor(
            EXECUTOR, lambda: API.dcam_init(c_void_p(0), pointer(c_int32(0)), c_char_p(0))
        )
        while not fut.done():
            t = time.monotonic() - t0
            if int(t) % 2 == 0:
                logger.info(f"Still alive. dcam_init takes about 10s. Taken {t:.2f} s.")
            if t > 60:
                raise TimeoutError("DCAM API initialization timeout.")
            await asyncio.sleep(1)

        return cls((await _Camera.ainit(0), await _Camera.ainit(1)))

    def __init__(self, _cams: tuple[_Camera, _Camera] | None = None) -> None:
        if _cams is None:
            logger.info("Initializing DCAM API.")
            API.dcam_init(c_void_p(0), pointer(c_int32(0)), c_char_p(0))
            _cams = (_Camera(0), _Camera(1))

        self._cams = _cams

        self.properties = TwoProps(*[c.properties for c in self._cams])
        self.set_mode(Mode.TDI)

    def __getitem__(self, id_: ID) -> _Camera:
        return self._cams[id_]

    def initialize(self) -> None:
        [x.initialize() for x in self]

    def n_frames_taken(self, cam: Cam) -> int:
        return min(c.n_frames_taken for c in self) if cam == 2 else self[cam].n_frames_taken

    @overload
    @contextmanager
    def _attach(
        self, n_bundles: int, dim: tuple[int, int], cam: Literal[0, 1] = ...
    ) -> Generator[UInt16Array]: ...

    @overload
    @contextmanager
    def _attach(
        self, n_bundles: int, dim: tuple[int, int], cam: Literal[2] = ...
    ) -> Generator[tuple[UInt16Array, UInt16Array]]: ...

    @contextmanager
    def _attach(
        self, n_bundles: int, dim: tuple[int, int], cam: Cam = 2
    ) -> Generator[UInt16Array] | Generator[tuple[UInt16Array, UInt16Array]]:
        if cam == 2:
            with self[0].attach(n_bundles, dim) as buf1, self[1].attach(n_bundles, dim) as buf2:
                logger.debug(f"Allocated memory for {n_bundles} bundles.")
                yield (buf1, buf2)
        else:
            with self[cam].attach(n_bundles, dim) as buf1:
                logger.debug(f"Allocated memory for {n_bundles} bundles for cam {cam}.")
                yield buf1

    @property
    def mode(self) -> ModeDict:
        return self._mode

    def set_mode(self, m: ModeDict) -> None:
        self.properties.update(m)
        self._mode = m

    async def capture(
        self,
        n_bundles: int,
        dim: tuple[int, int] = (128, 4096),
        start_attach: Callable[[], Any] = lambda: None,
        fut_capture: Awaitable[Any] | None = None,
        mode: ModeDict = Mode.TDI,
        cam: Literal[0, 1, 2] = 2,
        event_queue: tuple[asyncio.Queue[T], Callable[[int], T]] | None = None,
    ) -> UInt16Array:

        if cam == 2 and dim != (128, 4096):
            raise ValueError("Dim needs to be (128, 4096) when using both cameras.")

        async def in_ctx():
            curr = 0
            fut = asyncio.create_task(cast(Coroutine[Any, Any, Any], fut_capture)) if fut_capture else None
            t0 = time.monotonic()
            while (n := self.n_frames_taken(cam)) < n_bundles:
                await asyncio.sleep(0.05)
                if n == 0 and time.monotonic() - t0 > 5:
                    raise Exception(f"Did not capture a single bundle before {5=}s.")
                # Send every other bundle.
                if event_queue is not None and n > curr + 2:
                    event_queue[0].put_nowait(event_queue[1](n + 2))
                    curr = n
            if event_queue is not None:
                await asyncio.sleep(0.05)
                event_queue[0].put_nowait(event_queue[1](n_bundles))
            if fut:
                await fut

        self.set_mode(mode)
        with self._attach(n_bundles=n_bundles, dim=dim, cam=cam) as bufs:
            start_attach()
            if cam == 2:
                with self[0].capture(), self[1].capture():
                    await in_ctx()
            else:
                with self[cam].capture():
                    await in_ctx()
            logger.info(f"Retrieved all {n_bundles} bundles.")

        if cam == 2:
            bufs = cast(tuple[UInt16Array, UInt16Array], bufs)
            return np.hstack(bufs).reshape(-1, 4, 2048).transpose(1, 0, 2)

        bufs = cast(UInt16Array, bufs)
        return bufs.reshape(-1, 2, 2048).transpose(1, 0, 2) if dim[1] == 4096 else bufs
