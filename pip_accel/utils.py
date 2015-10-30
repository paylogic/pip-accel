# Utility functions for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: October 30, 2015
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
import platform
import sys

# Modules included in our package.
from pip_accel.compat import WINDOWS

# External dependencies.
from humanfriendly import parse_path
from pip.commands.uninstall import UninstallCommand
from pkg_resources import WorkingSet


def compact(text, **kw):
    """
    Compact whitespace in a string and format any keyword arguments into the
    resulting string. Preserves paragraphs.

    :param text: The text to compact (a string).
    :param kw: Any keyword arguments to apply using :py:func:`str.format()`.
    :returns: The compacted, formatted string.
    """
    return '\n\n'.join(' '.join(p.split()) for p in text.split('\n\n')).format(**kw)


def expand_path(pathname):
    """
    Variant of :py:func:`os.path.expanduser()` that doesn't use ``$HOME`` but
    instead uses the home directory of the effective user id. This is basically
    a workaround for ``sudo -s`` not resetting ``$HOME``.

    :param pathname: A pathname that may start with ``~/``, indicating the path
                     should be interpreted as being relative to the home
                     directory of the current (effective) user.
    :returns: The (modified) pathname.
    """
    # The following logic previously used regular expressions but that approach
    # turned out to be very error prone, hence the current contraption based on
    # direct string manipulation :-).
    home_directory = find_home_directory()
    separators = set([os.sep])
    if os.altsep is not None:
        separators.add(os.altsep)
    if len(pathname) >= 2 and pathname[0] == '~' and pathname[1] in separators:
        pathname = os.path.join(home_directory, pathname[2:])
    return parse_path(pathname)


def find_home_directory():
    """
    Look up the home directory of the effective user id.

    :returns: The pathname of the home directory (a string).

    .. note:: On Windows this uses the ``%APPDATA%`` environment variable (if
              available) and otherwise falls back to ``~/Application Data``.
    """
    if WINDOWS:
        directory = os.environ.get('APPDATA')
        if not directory:
            directory = os.path.expanduser(r'~\Application Data')
    else:
        # This module isn't available on Windows so we have to import it here.
        import pwd
        # Look up the home directory of the effective user id so we can
        # generate pathnames relative to the home directory.
        entry = pwd.getpwuid(os.getuid())
        directory = entry.pw_dir
    return directory


def is_root():
    """Detect whether we're running with super user privileges."""
    return False if WINDOWS else os.getuid() == 0


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


def same_directories(path1, path2):
    """
    Check if two pathnames refer to the same directory.

    :param path1: The first pathname (a string).
    :param path2: The second pathname (a string).
    :returns: :data:`True` if both pathnames refer to the same directory,
              :data:`False` otherwise.
    """
    if all(os.path.isdir(p) for p in (path1, path2)):
        try:
            return os.path.samefile(path1, path2)
        except AttributeError:
            # On Windows and Python 2 os.path.samefile() is unavailable.
            return os.path.realpath(path1) == os.path.realpath(path2)
    else:
        return False


def replace_file(src, dst):
    """
    Overwrite a file (in an atomic fashion when possible).

    :param src: The pathname of the source file (a string).
    :param dst: The pathname of the destination file (a string).
    """
    # Try os.replace() which was introduced in Python 3.3
    # (this should work on POSIX as well as Windows systems).
    try:
        os.replace(src, dst)
        return
    except AttributeError:
        pass
    # Try os.rename() which is atomic on UNIX but refuses to overwrite existing
    # files on Windows.
    try:
        os.rename(src, dst)
        return
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    # Finally we fall back to the dumb approach required only on Windows.
    # See https://bugs.python.org/issue8828 for a long winded discussion.
    os.remove(dst)
    os.rename(src, dst)


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


def match_option_with_value(arguments, option, value):
    """
    Check if a list of command line options contains an option with a value.

    :param arguments: The command line arguments (a list of strings).
    :param option: The long option (a string).
    :param value: The expected value (a string).
    :returns: ``True`` if the command line contains the option/value pair,
              ``False`` otherwise.
    """
    return ('%s=%s' % (option, value) in arguments or
            contains_sublist(arguments, [option, value]))


def contains_sublist(lst, sublst):
    """
    Check if one list contains the items from another list (in the same order).

    :param lst: The main list.
    :param sublist: The sublist to check for.
    :returns: :data:`True` if the main list contains the items from the
              sublist in the same order, :data:`False` otherwise.

    Based on `this StackOverflow answer <http://stackoverflow.com/a/3314913>`_.
    """
    n = len(sublst)
    return any((sublst == lst[i:i + n]) for i in range(len(lst) - n + 1))
