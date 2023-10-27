from uscope.app.argus.scripting import ArgusScriptingPlugin
import os
from PyQt5.QtWidgets import QMessageBox


class Plugin(ArgusScriptingPlugin):
    def input_config(self):
        return {
            "Mode": {
                "widget": "QComboBox",
                "values": ["Setup: lower left", "Setup: upper right", "Run"],
                "default": "Setup: lower left"
            },
            "Output directory": {
                "widget": "QLineEdit",
                "type": str,
                "default": "image_grid"
            },
            "X sites": {
                "widget": "QLineEdit",
                "type": int,
                "default": "1"
            },
            "Y sites": {
                "widget": "QLineEdit",
                "type": int,
                "default": "1"
            },
            "Lower left": {
                "widget": "QLineEdit",
                "type": str,
                "default": ""
            },
            "Upper right": {
                "widget": "QLineEdit",
                "type": str,
                "default": ""
            },
            "Autofocus": {
                "widget": "QComboBox",
                "values": ["Yes", "No"],
                "default": "No"
            },
        }

    def mode_run(self,
                 output_directory,
                 x_sites,
                 y_sites,
                 lower_left,
                 upper_right,
                 autofocus=False):

        self.log(f"Saving to {output_directory}")
        if os.path.exists(output_directory):
            # if not self.message_box_yes_cancel("Start?", "Output directory already exists. Are you sure you want to continue"):
            #     return
            self.log("WARNING: output directory already exists")
        else:
            os.mkdir(output_directory)
        x_pitch = 0
        y_pitch = 0
        if x_sites > 1:
            x_pitch = (upper_right["x"] - lower_left["x"]) / (x_sites - 1)
        if y_sites > 1:
            y_pitch = (upper_right["y"] - lower_left["y"]) / (y_sites - 1)

        # Good approximation of the sample height
        # If we really care we might want to use Planner XY3P
        z_pos = (lower_left["z"] + upper_right["z"]) / 2

        # Make behavior mirror planner:
        # row / col upper left, but motion XY origin lower right
        for row in range(y_sites):
            for col in range(x_sites):
                pos = {
                    "x": lower_left["x"] + col * x_pitch,
                    "y": lower_left["y"] + (y_sites - row - 1) * y_pitch,
                    "z": z_pos,
                }
                self.move_absolute(pos)
                if autofocus:
                    self.autofocus()
                filename = os.path.join(output_directory,
                                        "c%03u_r%03u.jpg" % (col, row))
                image = self.image()
                image.save(filename)
                self.log(f"Saved {filename}")
        self.log("Return to lower left")
        self.move_absolute(lower_left)
        self.log("Done")

    def run_test(self):
        self.log("Hello, world!")
        vals = self.get_input()
        mode = vals["Mode"]
        if mode == "Setup: lower left":
            self.set_input_default("Lower left",
                                   self.position_format(self.pos()))
        elif mode == "Setup: upper right":
            self.set_input_default("Upper right",
                                   self.position_format(self.pos()))
        elif mode == "Run":
            if not vals["Output directory"]:
                self.log("Output directory required")
                return
            self.mode_run(
                output_directory=vals["Output directory"],
                x_sites=vals["X sites"],
                y_sites=vals["Y sites"],
                lower_left=self.position_parse(vals["Lower left"]),
                upper_right=self.position_parse(vals["Upper right"]),
                autofocus=vals["Autofocus"] == "Yes",
            )
        else:
            assert 0, f"bad mode {mode}"