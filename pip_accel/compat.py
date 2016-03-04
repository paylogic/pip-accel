# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: March 4, 2016
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
    'pathname2url',
    'urljoin',
    'urlparse',
)

WINDOWS = sys.platform.startswith('win')
""":data:`True` if running on Windows, :data:`False` otherwise."""

# Compatibility between Python 2 and 3.
try:
    # Python 2.
    basestring = basestring
    import ConfigParser as configparser
    from StringIO import StringIO
    from urllib import pathname2url
    from urlparse import urljoin, urlparse
    PY3 = False
except (ImportError, NameError):
    # Python 3.
    basestring = str
    import configparser
    from io import StringIO
    from urllib.parse import urljoin, urlparse
    from urllib.request import pathname2url
    PY3 = True
