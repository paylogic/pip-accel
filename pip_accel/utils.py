# Utility functions for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 15, 2014
# URL: https://github.com/paylogic/pip-accel

"""
:py:mod:`pip_accel.utils` - Utility functions
=============================================

The :py:mod:`pip_accel.utils` module defines several miscellaneous/utility
functions that are used throughout :py:mod:`pip_accel` but don't really belong
with any single module.
"""

# Standard library modules.
import errno
import os
import pipes
import platform
import pwd
import re
import sys

# Look up the home directory of the effective user id so we can generate
# pathnames relative to the home directory.
HOME = pwd.getpwuid(os.getuid()).pw_dir

def compact(text, **kw):
    """
    Compact whitespace in a string and format any keyword arguments into the
    resulting string.

    :param text: The text to compact (a string).
    :param kw: Any keyword arguments to apply using :py:func:`str.format()`.
    :returns: The compacted, formatted string.
    """
    return ' '.join(text.split()).format(**kw)

def expand_user(pathname):
    """
    Variant of :py:func:`os.path.expanduser()` that doesn't use ``$HOME`` but
    instead uses the home directory of the effective user id. This is basically
    a workaround for ``sudo -s`` not resetting ``$HOME``.

    :param pathname: A pathname that may start with ``~/``, indicating the path
                     should be interpreted as being relative to the home
                     directory of the current (effective) user.
    """
    return re.sub('^~(?=/)', HOME, pathname)

def get_python_version():
    """
    Get a string identifying the currently running Python version.

    This function generates a string that uniquely identifies the currently
    running Python implementation and version. The Python implementation is
    discovered using :py:func:`platform.python_implementation()` and the major
    and minor version numbers are extracted from :py:data:`sys.version_info`.

    :returns: A string containing the name of the Python implementation
              and the major and minor version numbers.

    Example:

    >>> from pip_accel.utils import get_python_version
    >>> get_python_version()
    'CPython-2.7'
    """
    return '%s-%i.%i' % (platform.python_implementation(),
                         sys.version_info[0],
                         sys.version_info[1])

def makedirs(path, mode=0o777):
    """
    Create a directory if it doesn't already exist (keeping concurrency in mind).

    :param path: The pathname of the directory to create (a string).
    :param mode: The mode to apply to newly created directories (an integer,
                 defaults to the octal number ``0777``).
    :returns: ``True`` when the directory was created, ``False`` if it already
              existed.
    :raises: Any exceptions raised by :py:func:`os.makedirs()` except for
             :py:data:`errno.EEXIST` (this error is swallowed and ``False`` is
             returned instead).
    """
    try:
        os.makedirs(path, mode)
        return True
    except OSError as e:
        if e.errno != errno.EEXIST:
            # We don't want to swallow errors other than EEXIST,
            # because we could be obscuring a real problem.
            raise
        return False

def run(command, **params):
    """
    Format command string with quoted parameters and execute external command.

    :param command: The shell command line to run (a string).
    :param params: Zero or more keyword arguments to be formatted into the
                   command line as quoted arguments.
    :returns: ``True`` if the command succeeds, ``False`` otherwise.
    """
    params = dict((k, pipes.quote(v)) for k, v in params.items())
    return os.system(command.format(**params)) == 0
