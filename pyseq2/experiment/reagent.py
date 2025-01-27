# %%
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from pydantic import BaseModel, validator

from pyseq2.config import CONFIG
from pyseq2.flowcell import Seconds, μLpermin

__all__ = ["Reagent", "ReagentGroup"]


class Reagent(BaseModel):
    name: str
    port: int
    v_pull: μLpermin = 100
    v_prime: μLpermin = 250
    v_push: μLpermin = 2000
    wait: Seconds = 26

    @validator("v_pull", "v_prime", "v_push")
    def v_check(cls, v: μLpermin) -> μLpermin:
        assert 2.5 * CONFIG.barrelsPerLane <= v <= 2000 * CONFIG.barrelsPerLane
        return v

    @validator("wait")
    def sec_check(cls, s: Seconds) -> Seconds:
        assert s >= 0
        return s

    @validator("port")
    def port_check(cls, port: int) -> int:
        assert port in CONFIG.ports
        return port

    @classmethod
    def default(cls) -> Reagent:
        return Reagent(name="water", port=1)


class ReagentGroup(BaseModel):
    name: str

    @classmethod
    def default(cls) -> ReagentGroup:
        return ReagentGroup(name="")


class CompiledReagents(BaseModel):
    lone: dict[str, Reagent]
    groups: dict[str, list[Reagent]]


Reagents = list[Reagent | ReagentGroup]


def compile_reagents(reagents: Reagents) -> CompiledReagents:
    reagents = deepcopy(reagents)
    lone: dict[str, Reagent] = {}
    groups: defaultdict[str, list[Reagent]] = defaultdict(list)
    curr_group = ""
    i = 1
    for r in reagents:
        if isinstance(r, ReagentGroup):
            if i == 0:
                raise ValueError(f"Group {curr_group} has no member.")
            curr_group = r.name
            i = 0
        else:
            if curr_group:
                groups[curr_group].append(r)
            else:
                lone[r.name] = r
            i += 1

    if i == 0:  # Prevent group from being the last one.
        raise ValueError(f"Group {curr_group} has no member.")

    return CompiledReagents(lone=lone, groups=dict(groups))
