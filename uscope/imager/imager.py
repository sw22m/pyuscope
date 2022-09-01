from PIL import Image
'''
R:127
G:103
B:129
'''

# driver does not play well with other and effectively results in a system restart
# provide some basic protection
"""
def camera_in_use():
    '''
    C:\Program Files\AmScope\AmScope\x86\scope.exe
    '''
    for p in psutil.get_process_list():
        try:
            if p.exe.find('scope.exe') >= 0:
                print 'Found process %s' % p.exe
                return True
        except:
            pass
    return False
"""


class Imager:
    def __init__(self, verbose=False):
        self.verbose = verbose

    def wh(self):
        """Return width, height in pixels"""
        raise Exception('Required %s' % type(self))

    # Must implement at least one of the following

    def get(self):
        '''
        Return a dict of PIL image objects
        For simple imagers any key will do, but suggest "0"
        {"0": PIL}
        '''
        raise Exception('Required')

    def take(self):
        '''Take and store to internal storage'''
        raise Exception('Required')

    def remote(self):
        """Return true if the image is taken remotely and not handled here. Call take() instead of get"""
        return False


class MockImager(Imager):
    def __init__(self, verbose=False, width=640, height=480):
        Imager.__init__(self, verbose=verbose)
        self.width = width
        self.height = height

    def wh(self):
        return self.width, self.height

    def get(self):
        # Small test image
        return {"0": Image.new("RGB", (self.width, self.height), 'white')}


"""
class ImageProcessor:
    def __init__(self):
        # In many configurations we are scaling output
        self.scaling = False
        self._scalar = None

		self.hdring = False
		self.

    def scalar(self):
        if not self.scaling:
            return 1.0
        else:
            return self._scalar
"""