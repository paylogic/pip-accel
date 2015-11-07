# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: November 7, 2015
# URL: https://github.com/paylogic/pip-accel

"""Operating system detection and Python version compatibility."""

# Standard library modules.
import sys

# Inform static code analysis tools about our intention to expose the
# following variables. This avoids 'imported but unused' warnings.
__all__ = (
    'WINDOWS',
    'StringIO',
    'configparser',
    'urlparse',
)

WINDOWS = sys.platform.startswith('win')
""":data:`True` if running on Windows, :data:`False` otherwise."""

# Compatibility between Python 2 and 3.
try:
    # Python 2.
    basestring = basestring
    from StringIO import StringIO
    from urlparse import urlparse
    import ConfigParser as configparser
except (ImportError, NameError):
    # Python 3.
    basestring = str
    from io import StringIO
    from urllib.parse import urlparse
    import configparser
