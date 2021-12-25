import asyncio

from fastapi import Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse


class Moves(BaseModel):
    pos: float
    in_position: bool


class Status(BaseModel):
    x: float
    y: float
    z_tilt: tuple[int, int, int]
    z_obj: int
    laser_r: int
    laser_g: int
    shutter: bool


async def poll(request: Request):
    async def gen():
        while True:
            x = 0
            y = 1
            while True:
                yield Status(x=x, y=y, z_tilt=(1, 1, 1), z_obj=1, laser_r=y, laser_g=1, shutter=False).json()
                await asyncio.sleep(1)
                x += 0.3
                y += 1
                if x > 25:
                    x = 0
                if y > 75:
                    y = 0

    return EventSourceResponse(gen())


async def logGenerator(request: Request):
    i = 0
    while True:
        yield i
        await asyncio.sleep(1)
        i += 1
    # for line in tail("-f", LOGFILE, _iter=True):
    #     if await request.is_disconnected():
    #         print("client disconnected!!!")
    #         break
    #     yield line
    #     time.sleep(0.5)


async def logs(request: Request):
    event_generator = logGenerator(request)
    return EventSourceResponse(event_generator)
