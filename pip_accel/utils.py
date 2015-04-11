# Utility functions for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: April 11, 2015
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

# External dependencies.
from pip.commands.uninstall import UninstallCommand
from pkg_resources import WorkingSet

# Look up the home directory of the effective user id so we can generate
# pathnames relative to the home directory.
HOME = pwd.getpwuid(os.getuid()).pw_dir

def compact(text, **kw):
    """
    Compact whitespace in a string and format any keyword arguments into the
    resulting string. Preserves paragraphs.

    :param text: The text to compact (a string).
    :param kw: Any keyword arguments to apply using :py:func:`str.format()`.
    :returns: The compacted, formatted string.
    """
    return '\n\n'.join(' '.join(p.split()) for p in text.split('\n\n')).format(**kw)

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

def is_installed(package_name):
    """
    Check whether a package is installed in the current environment.

    :param package_name: The name of the package (a string).
    :returns: ``True`` if the package is installed, ``False`` otherwise.
    """
    return package_name.lower() in (d.key.lower() for d in WorkingSet())

def uninstall(*package_names):
    """
    Uninstall one or more packages using the Python equivalent of ``pip uninstall --yes``.

    The package(s) to uninstall must be installed, otherwise pip will raise an
    ``UninstallationError``. You can check for installed packages using
    :py:func:`is_installed()`.

    :param package_names: The names of one or more Python packages (strings).
    """
    command = UninstallCommand()
    opts, args = command.parse_args(['--yes'] + list(package_names))
    command.run(opts, args)

def find_installed_version(package_name):
    """
    Find the version of an installed package.

    :param package_name: The name of the package (a string).
    :returns: The package's version (a string) or ``None`` if the package can't
              be found.
    """
    package_name = package_name.lower()
    for distribution in WorkingSet():
        if distribution.key.lower() == package_name:
            return distribution.version

def match_option(argument, short_option, long_option):
    """
    Match a command line argument against a short and long option.

    :param argument: The command line argument (a string).
    :param short_option: The short option (a string).
    :param long_option: The long option (a string).
    :returns: ``True`` if the argument matches, ``False`` otherwise.
    """
    return short_option[1] in argument[1:] if is_short_option(argument) else argument == long_option

def is_short_option(argument):
    """
    Check if a command line argument is a short option.

    :param argument: The command line argument (a string).
    :returns: ``True`` if the argument is a short option, ``False`` otherwise.
    """
    return len(argument) >= 2 and argument[0] == '-' and argument[1] != '-'
