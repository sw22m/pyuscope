#!/usr/bin/env python3
"""
Running the full suite:
-GRBL controller attached (no microscope)
-E3ISPM20000KPA camera attached
-v4levice as /dev/video0 that supports 640x480 video
    Ex: my X1 carbon has this as built in web camera
"""

import unittest
import os
import shutil
import uscope.imagej_util as imagej_util
from PIL import Image, ImageDraw


class TestCommon(unittest.TestCase):

    def setUp(self):
        """Call before every test case."""
        print("")
        print("")
        print("")
        print("Start " + self._testMethodName)
        self.verbose = os.getenv("VERBOSE", "N") == "Y"
        self.verbose = int(os.getenv("TEST_VERBOSE", "0"))
        self.planner_dir = "/tmp/pyuscope/planner"
        if os.path.exists("/tmp/pyuscope"):
            shutil.rmtree("/tmp/pyuscope")
        os.mkdir("/tmp/pyuscope")

    def tearDown(self):
        """Call after every test case."""

    def test_init_ij(self):
        ij = imagej_util.ij()

    def test_classes(self):
        # Demonstrate access to classes
        ij = imagej_util.ij()
        print(ij.IJ)
        print(ij.ResultsTable)
        print(ij.RoiManager)
        print(ij.WindowManager)

    def test_get_ops(self):
        print(imagej_util.get_ops())

    def test_threshold_manual(self):
        image = Image.new('RGBA', (500, 500), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 100, 100, 100), outline='orange', fill='orange', width=1)

        result: dict = imagej_util.threshold_image_manual(image, 50, 255)
        result["image_mask"]
        assert result["lower_threshold"] == 50
        assert result["upper_threshold"] == 255

    def test_threshold_auto(self):
        image = Image.new('RGBA', (500, 500), "white")
        result = imagej_util.threshold_image_auto(image, "Huang")
        result["image_mask"]
        assert result["lower_threshold"] >= 0 and result["lower_threshold"] <= 255
        assert result["lower_threshold"] >= 0 and result["upper_threshold"] <= 255

    def test_measure_area(self):
        image = Image.new('RGBA', (500, 500), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 100, 100, 100), outline='orange', fill='orange', width=1)
        roi = [12, 99, 486, 336]

        auto_threshold = imagej_util.threshold_image_auto(image, "Default")
        result = imagej_util.measure_areas(auto_threshold['image_mask'],
                               min_particle=50,
                               pixel_distance=297,
                               known_distance=50,
                               roi=roi)
        print(result)
        result["csv"]
        result["image_result"]
        # result['image_result'].show()

    def test_get_roi(self):
        r = imagej_util.get_roi([1,2,3,4])
        assert r
        r = imagej_util.get_roi([1, 2, 3])
        assert r is None


if __name__ == "__main__":
    unittest.main()
