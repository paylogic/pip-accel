# Utility functions for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: June 29, 2014
# URL: https://github.com/paylogic/pip-accel

# Standard library modules.
import os
import pipes
import pwd
import re
import sys

# Look up the home directory of the effective user id so we can generate
# pathnames relative to the home directory.
HOME = pwd.getpwuid(os.getuid()).pw_dir

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
    Return a string identifying the currently running Python version.

    :returns: A string like "py2.6" or "py2.7" containing a short mnemonic
              prefix followed by the major and minor version numbers.
    """
    return "py%i.%i" % (sys.version_info[0], sys.version_info[1])
