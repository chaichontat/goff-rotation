import re
from typing import Protocol


class Fakes(Protocol):
    def __call__(self, s: str) -> str: ...


class FakeX:
    def __call__(self, s: str) -> str:
        match s.split(" "):
            case ["PR", x]:
                return f"PR {x}\n12000"
            case ["MA", _]:
                return "MA 0,1\n?!"
            case _:
                ...

        match s:
            case x if x == "\x03":
                return "Copyright© 2010 Schneider Electric Motion USA"
            case "HM 1":
                return "1  HM 1"
            case "H":
                return "5  H"
            case "P=30000":
                return "7  P=30000"
            case "E":
                return "12  E"
            case "PG":
                return "14  PG"
            case "EX 1":
                return ">EX 1\n>"
            case x:
                return f">{x}"


class FakeY:
    def __call__(self, s: str) -> str:
        s = s[1:]
        if (r := s.split("("))[0] == "R":
            return f"1R({r[1]}\n*+0"

        match s:
            case "Z":
                return "1Z\n*ViX250IH-Servo Drive\n*REV 2.4 Jul 07 2005 10:08:34\n*Copyright 2003 Parker-Hannifin"
            case x if x.startswith("D") and x[1:].isnumeric():
                return f"1{x}"
            case x if x.startswith("V") and x[1:].isnumeric():
                return f"1{x}"
            case x if x.startswith("GAINS"):
                return "1GAINS(5,10,7,1.5,0)"
            case "GOTO(CHKMV)":
                return "1GOTO(CHKMV)\nMove Done"
            case x:
                return "1" + x


class FakeLaser:
    def __call__(self, s: str) -> str:
        match s:
            case "ON" | "OFF":
                return ""
            case "POWER?":
                return "0000mW"
            case "STAT?":
                return "ENABLED"
            case "VERSION?":
                return "SMD-G-1.1.2"
            case _:
                ...

        match s.split("="):
            case ["POWER", _]:
                return ""
            case _:
                return "what?"


class FakeFPGA:
    def __call__(self, s: str) -> str:
        match s.split():
            case ["TDIYEWR", _] as e:
                return "TDIYEWR"
            case ["TDIYPOS", _] as e:
                return "TDIYPOS"
            case ["TDIYARM3", _, _, _] as e:
                return "TDIYARM3"

            case ["ZSTEP" as e, _] | ["ZDACW" as e, _] | ["ZTRG" as e, _] | ["SWYZ_POS" as e, _]:
                return e
            case ["ZYT" as e, _, _]:
                return e
            case ["ZMV", _]:
                return "@LOG Trigger Camera\nZMV"

            case ["T1MOVETO" as e, _] | ["T2MOVETO" as e, _] | ["T3MOVETO" as e, _]:
                return f"{e} 0"
            case ["T1VL" as e, _] | ["T2VL" as e, _] | ["T3VL" as e, _]:
                return e
            case ["T1CUR" as e, _] | ["T2CUR" as e, _] | ["T3CUR" as e, _]:
                return e

            case ["SWLSRSHUT", _]:
                return "SWLSRSHUT"
            case ["EX1MV" as y, _] | ["EX2MV" as y, _]:
                return y

            case _:
                ...

        match s:
            case "RESET":
                return "@LOG The FPGA is now online.  Enjoy!\nRESET"
            case "EM2I" | "EM2O" as e:
                return e
            case "EX1HM" | "EX2HM" as e:
                return e
            case "TDIYERD" as e:
                return f"{e} 1"
            case "TDIPULSES" as e:
                return f"{e} 1"
            case "ZDACR" | "ZADCR" as e:
                return e + " 0"

            case "T1RD" | "T2RD" | "T3RD" as e:
                return f"{e} 0"
            case "T1HM" | "T2HM" | "T3HM" as e:
                return f"@TILTPOS{e[1]} -1\nT{e[1]}HM" + e
            case "T1CR" | "T2CR" | "T3CR" as e:
                return e
            case "EM2I" | "EM2O" as e:
                return e
            case "EX1HM" | "EX2HM" as e:
                return e
            case _:
                return "what?"


class FakePump:
    def __init__(self) -> None:
        self.pos = 0
        self.re = re.compile(r"\/1V(\d+)(I|O)A(\d+)R")

    def __call__(self, s: str) -> str:
        if s == "/1?":
            return f"/0`{self.pos}"  # Position
        if match := self.re.match(s):
            self.pos = int(match.group(3))
            print(self.pos)
        return "/0`"


class FakeValve:
    def __call__(self, s: str) -> str:
        match s:
            case "*ID*":
                return ""
            case "ID":
                return "ID = not used"
            case x if x.startswith("GO"):
                return ""
            case "CP":
                return "Position is  = 1"
            case "NP":
                return "NP = 10"
            case _:
                return "what?"


class FakeARM9:
    def __call__(self, s: str) -> str:
        match s:
            case "?IDN":
                return "Illumina,Bruno Fluidics Controller,0,v2.0:A1"
            case "INIT":
                return "A1"
            case "?RETEMP:3":
                return "0.0C:0.0C:0.0:A1"
            case "?asyphon:0":
                return "0:A1"
            case _:
                ...

        match s.split(":"):
            case ["?FCTEMP", _]:
                return "0.0C:A1"
            case _:
                return "A1"
