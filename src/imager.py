from dataclasses import dataclass
from logging import getLogger

from .imaging.camera.dcam import Cameras, FourImages, Mode
from .imaging.fpga import FPGA
from .imaging.fpga.optics import Optics
from .imaging.laser import Laser, Lasers
from .imaging.xstage import XStage
from .imaging.ystage import YStage
from .utils.ports import Ports

logger = getLogger("Imager")


@dataclass
class Channel:
    laser: Laser
    optics: Optics


class Imager:
    fpga: FPGA
    UM_PER_PX = 0.375

    def __init__(self, ports: Ports) -> None:
        self.fpga = FPGA(*ports.fpga)
        self.tdi = self.fpga.tdi
        self.optics = self.fpga.optics

        self.x = XStage(ports.x)
        self.y = YStage(ports.y)
        self.z = self.fpga.z

        self.lasers = Lasers(Laser("laser_g", ports.laser_g), Laser("laser_r", ports.laser_r))
        self.cams = Cameras()

    def initialize(self) -> None:
        self.x.initialize()
        self.y.initialize()
        self.lasers.initialize()

    # TODO add more ready checks.
    def take_image(self, n_bundles: int) -> FourImages:
        logger.info(f"Taking image with {n_bundles} bundles.")
        while not self.y.is_in_position.result():
            logger.warning("Started taking an image while y-stage is not in position. Waiting.")

        pos = self.y.position
        self.y._mode = "IMAGING"
        pos = pos.result()
        assert pos is not None
        n_px_y = n_bundles * self.cams.BUNDLE_HEIGHT
        end_y_pos = pos - (delta := self.calc_delta_pos(n_px_y)) - 100000
        fut = self.tdi.prepare_for_imaging(n_px_y, pos)
        self.cams.mode = Mode.TDI
        fut.result()
        with self.optics.open_shutter():
            imgs = self.cams.capture(
                n_bundles, start_capture=lambda: self.y.move(end_y_pos, slowly=True)
            ).result()
        self.fpga.tdi.n_pulses
        logger.info(f"Done taking an image.")
        return imgs

    @staticmethod
    def calc_delta_pos(n_px_y: int) -> int:
        return int(n_px_y * Imager.UM_PER_PX * YStage.STEPS_PER_UM)