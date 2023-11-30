"""

# ImageJ Dataset and ImagePlus

https://imagej.net/ij/ij/developer/api/ij/ij/ImagePlus.html
https://imagej.net/ij/developer/api/ij/ij/process/ImageProcessor.html

Note: Images are opened as ImageJ2 Dataset (Java object) instead of legacy ImagePlus format
Legacy or ImageJ2 will depend on ImageJ functionality needed

n_array = numpy.array(pil_img)
img = ij().IJ.openImage(n_array) # Legacy return an ImagePlus object
img = ij().io().open(n_array)  # ImageJ2 returns  Dataset object


# Convenience function to get list of available Ops
# For pyimagej usage, see - https://py.imagej.net/en/latest/10-Using-ImageJ-Ops.html
Example: print(get_ops)


# Threshold an Image

Method 1: Manually Threshold an Image

    image = Image.open('../path/to/img.png')
    result: dict = threshold_image_manual(image, min_threshold=30, max_threshold=255)

Method 2: Auto Threshold an Image

    THRESHOLD_MODES = ["Manual", "Default", "Huang", "Intermodes", "IsoData", "IJ_IsoData",
       "Li", "MaxEntropy", "Mean", "MinError", "Minimum", "Moments",
       "Otsu", "Percentile", "RenyiEntropy", "Shanbhag", "Triangle", "Yen"]

    image = Image.open('../path/to/img.png')
    result: dict = threshold_image_auto(image, mode='Huang')

    Example `result` output {
        'result': <PIL.Image.Image image mode=L size=800x750 at 0x7F31684F8A90>,
        'lower_threshold': 30.0,
        'upper_threshold': 255.0
    }


"""
from PIL import Image
import numpy
import imagej
import scyjava
import tempfile
import csv


_ij = None
def ij():
    global _ij
    if not _ij:
        # Initialize ImageJ
        # _ij = imagej.init(mode=imagej.Mode.INTERACTIVE)
        _ij = imagej.init(mode=imagej.Mode.HEADLESS)
    return _ij

ij()  # Trigger the initialization on import


def get_ops() -> list:
    """
    :return: A String list of ImageJ Op names
    """
    return [op for op in ij().op().ops()]


def grayscale_image(image: Image):
    # Average across all three channels
    # Default grayscale method in ImageJ
    n_array = numpy.array(image)
    gray = numpy.average(n_array, axis=-1)
    return Image.fromarray(gray)


def threshold_image_manual(image: Image, min_threshold: float, max_threshold: float) -> dict:
    """
    Thresholds an image given lower and upper threshold levels
    :param image: PIL image to be threshold
    :param min_threshold: the lower threshold level
    :param max_threshold: the upper threshold level
    :return: Example {'image_mask': <PIL Image>, 'lower_threshold': 13.0, 'upper_threshold': 240.0}
    """
    n_array = numpy.array(image)
    n_array = numpy.average(n_array, axis=-1)  # grayscale

    def check_threshold(p):
        # Why does this condition works but not inverse?
        # i.e. p > min_threshold and p < max_threshold
        # This does not need to be an inner function but
        # can be extended to other threshold conditions
        return p < min_threshold or p > max_threshold

    image_threshold = Image.fromarray(n_array)
    image_threshold = image_threshold.convert('L')
    image_threshold = image_threshold.point(lambda p: 0 if check_threshold(p) else 255)

    return {
        'image_mask': image_threshold,
        'lower_threshold': min_threshold,
        'upper_threshold': max_threshold
    }

    # Below code uses ImageJ. Commented out as the above
    # performs the equivalent but faster than using ImageJ

    # image_plus = ij().py.to_imageplus(n_array)
    # ip = image_plus.getProcessor()
    # # Set threshold, get the updated mask and return as PIL Image
    # ip.setThreshold(float(min_threshold), float(max_threshold))
    # mask = ip.createMask().createImage()
    # ImagePlus = scyjava.jimport('ij.ImagePlus')
    # mask = ImagePlus("mask", mask)
    # img_arr = ij().py.from_java(mask)
    # image_threshold = Image.fromarray(img_arr.to_numpy())
    # # To mono
    # image_threshold = image_threshold.convert('1')
    # return {
    #     'result': image_threshold,
    #     'lower_threshold': ip.getMinThreshold(),
    #     'upper_threshold': min(255, ip.getMaxThreshold())
    # }


def threshold_image_auto(image: Image, mode) -> dict:
    """
    Thresholds an image given an ImageJ auto threshold mode
    :param image: PIL image to be threshold
    :param mode: Auto threshold mode
    :return: Example {'image_mask': <PIL Image>, 'lower_threshold': 13.0, 'upper_threshold': 240.0}
    """
    n_array = numpy.array(image)
    n_array = numpy.average(n_array, axis=-1)  # grayscale
    image_plus = ij().py.to_imageplus(n_array)
    # Set auto threshold, get the updated mask and return as PIL Image
    ip = image_plus.getProcessor()
    auto_args = f"{mode} dark"
    ip.setAutoThreshold(auto_args)
    mask = ip.createMask().createImage()
    ImagePlus = scyjava.jimport("ij.ImagePlus")
    mask = ImagePlus("mask", mask)

    img_arr = ij().py.from_java(mask)
    image_threshold = Image.fromarray(img_arr.to_numpy())
    return {
        "image_mask": image_threshold,
        "lower_threshold": max(0, int(ip.getMinThreshold())),
        "upper_threshold": min(255, int(ip.getMaxThreshold()))  # sometimes returns `inf`
    }


def get_roi(roi):
    """
    Parse the given roi. If no valid roi detected, return None
    Examples

    rectangle: [x, y, w, h] where x,y is the top left point, and w,h are the
        width and height of rectangle to be measured. If not specified, the whole
        image will be measured
    """
    Rectangle = scyjava.jimport("java.awt.Rectangle")
    Roi = scyjava.jimport("ij.gui.Roi")
    try:
        x, y, w, h = [int(p) for p in roi]
        rectangle = Rectangle(x, y, w, h)
        return Roi(rectangle)
    except:
        pass

    return None

def measure_areas(mask: Image,
                  min_particle: float = 50,
                  max_particle: float = float("inf"),
                  roi = None,
                  pixel_distance: float = 1,
                  known_distance: float = 1,
                  unit: str = "unit"):
    """
    Detects particles inside an optional area of interest such as a rect or other shape
    :param mask: An image mask. See `threshold_image_auto` and `threshold_image_manual` to
    create a mask
    :param min_particle: The minimum particle area to be detected
    :param max_particle: The maximum particle area to be detected
    :param roi: Region of interest. See `get_roi` for valid formats
    :param pixel_distance: A specified pixel distance to calibrate scale
    :param known_distance: The known real world distance for the given pixel distance
    :param unit: String unit e.g. mm, cm, pixel
    :return: Example {'image_result': <PIL Image>, 'csv': [ <csv data> ]}

    TODO: extend to handle other roi shapes such as ellipse
    """
    n_array = numpy.array(mask)
    image_plus = ij().py.to_imageplus(n_array)
    # ij().IJ.run(image_plus, "Convert to Mask", "")  # Note: Revisit this Make binary command
    if roi:
        res = get_roi(roi)
        if res:
            image_plus.setRoi(res)

    # https://imagej.net/ij/ij/developer/api/ij/ij/plugin/filter/ParticleAnalyzer.html
    results_table = ij().ResultsTable()
    ParticleAnalyzer = scyjava.jimport("ij.plugin.filter.ParticleAnalyzer")
    String = scyjava.jimport("java.lang.String")
    ParticleAnalyzer.setFontColor(String('blue'))
    ParticleAnalyzer.setLineWidth(3)
    ParticleAnalyzer.setFontSize(18)
    options = [
        ParticleAnalyzer.DISPLAY_SUMMARY,
        ParticleAnalyzer.SHOW_OUTLINES,
        ParticleAnalyzer.SHOW_RESULTS,
        # ParticleAnalyzer.SHOW_OVERLAY_OUTLINES,
        ParticleAnalyzer.SHOW_OVERLAY_MASKS,
    ]
    # Calibrate the image scale
    ij().IJ.run(image_plus, "Set Scale...", f"distance={pixel_distance} known={known_distance} unit={unit}")
    pa = ParticleAnalyzer(sum(options), 0, results_table, min_particle, max_particle)
    pa.analyze(image_plus)

    csv_data = []
    results_table.showRowNumbers(False)
    # Save csv as a temporary file and read from there
    with tempfile.NamedTemporaryFile() as tmp:
        results_table.saveAs(tmp.name)
        csv_file = open(tmp.name, 'r')
        for n, row in enumerate(csv.reader(csv_file, delimiter='\t')):
            if n == 0:
                csv_data.append(row)
                continue
            csv_data.append([float(v) for v in row])

    output_image = pa.getOutputImage()
    if output_image:
        img_arr = ij().py.from_java(output_image)
        output_image = Image.fromarray(img_arr.to_numpy())
        # Below not strictly necessary but helps to overlay
        # the results onto the mask
        output_image = output_image.convert("RGBA")
        datas = output_image.getdata()
        new_data = []
        for item in datas:
            # Change white areas to transparent
            if item[0] == 255 and item[1] == 255 and item[2] == 255:
                new_data.append((0, 0, 0, 0))
            else:
                new_data.append((0, 0, 255, 255))
        output_image.putdata(new_data)

    return {
        "image_result": output_image,
        "csv": csv_data,
    }

