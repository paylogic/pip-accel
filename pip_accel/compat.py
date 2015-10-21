try:
    # Python 2.x.
    from StringIO import StringIO
    from urlparse import urlparse
    import ConfigParser as configparser
except ImportError:
    # Python 3.x.
    from io import StringIO
    from urllib.parse import urlparse
    import configparser

import os
import sys

is_win = sys.platform.startswith('win')

if is_win:
    HOME = os.environ.get('APPDATA')
    if not HOME:
        HOME = os.path.expanduser('~\\Application Data')
else:
    import pwd
    # Look up the home directory of the effective user id so we can generate
    # pathnames relative to the home directory.
    HOME = pwd.getpwuid(os.getuid()).pw_dir

def is_root():
    """
    Detect if running as user root. Cross-platform wrapper for os.getuid(0).

    :returns: True when running as user root, else otherwise.
    """
    if is_win:
        return False
    else:
        return os.getuid() == 0

