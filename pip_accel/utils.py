# Utility functions for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: January 17, 2016
# URL: https://github.com/paylogic/pip-accel

"""
Utility functions for the pip accelerator.

The :mod:`pip_accel.utils` module defines several miscellaneous/utility
functions that are used throughout :mod:`pip_accel` but don't really belong
with any single module.
"""

# Standard library modules.
import errno
import hashlib
import logging
import os
import platform
import sys

# Modules included in our package.
from pip_accel.compat import pathname2url, urljoin, WINDOWS

# External dependencies.
from humanfriendly import parse_path
from pip.commands.uninstall import UninstallCommand

# The following package(s) are usually bundled with pip but may be unbundled
# by redistributors and pip-accel should handle this gracefully.
try:
    from pip._vendor.pkg_resources import DistributionNotFound, WorkingSet, get_distribution, parse_requirements
except ImportError:
    from pkg_resources import DistributionNotFound, WorkingSet, get_distribution, parse_requirements

# Initialize a logger for this module.
logger = logging.getLogger(__name__)


def compact(text, **kw):
    """
    Compact whitespace in a string and format any keyword arguments into the string.

    :param text: The text to compact (a string).
    :param kw: Any keyword arguments to apply using :func:`str.format()`.
    :returns: The compacted, formatted string.

    The whitespace compaction preserves paragraphs.
    """
    return '\n\n'.join(' '.join(p.split()) for p in text.split('\n\n')).format(**kw)


def expand_path(pathname):
    """
    Expand the home directory in a pathname based on the effective user id.

    :param pathname: A pathname that may start with ``~/``, indicating the path
                     should be interpreted as being relative to the home
                     directory of the current (effective) user.
    :returns: The (modified) pathname.

    This function is a variant of :func:`os.path.expanduser()` that doesn't use
    ``$HOME`` but instead uses the home directory of the effective user id.
    This is basically a workaround for ``sudo -s`` not resetting ``$HOME``.
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
    # Also expand environment variables.
    return parse_path(pathname)


def create_file_url(pathname):
    """
    Create a ``file:...`` URL from a local pathname.

    :param pathname: The pathname of a local file or directory (a string).
    :returns: A URL that refers to the local file or directory (a string).
    """
    return urljoin('file:', pathname2url(os.path.abspath(pathname)))


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
    discovered using :func:`platform.python_implementation()` and the major
    and minor version numbers are extracted from :data:`sys.version_info`.

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
    :returns: :data:`True` when the directory was created, :data:`False` if it already
              existed.
    :raises: Any exceptions raised by :func:`os.makedirs()` except for
             :data:`errno.EEXIST` (this error is swallowed and :data:`False` is
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


def hash_files(method, *files):
    """
    Calculate the hexadecimal digest of one or more local files.

    :param method: The hash method (a string, given to :func:`hashlib.new()`).
    :param files: The pathname(s) of file(s) to hash (zero or more strings).
    :returns: The calculated hex digest (a string).
    """
    context = hashlib.new(method)
    for filename in files:
        with open(filename, 'rb') as handle:
            while True:
                chunk = handle.read(4096)
                if not chunk:
                    break
                context.update(chunk)
    return context.hexdigest()


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


class AtomicReplace(object):

    """Context manager to atomically replace a file's contents."""

    def __init__(self, filename):
        """
        Initialize a :class:`AtomicReplace` object.

        :param filename: The pathname of the file to replace (a string).
        """
        self.filename = filename
        self.temporary_file = '%s.tmp-%i' % (filename, os.getpid())

    def __enter__(self):
        """
        Prepare to replace the file's contents.

        :returns: The pathname of a temporary file in the same directory as the
                  file to replace (a string). Using this temporary file ensures
                  that :func:`replace_file()` doesn't fail due to a
                  cross-device rename operation.
        """
        logger.debug("Using temporary file to avoid partial reads: %s", self.temporary_file)
        return self.temporary_file

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Replace the file's contents (if no exception occurred) using :func:`replace_file()`."""
        if exc_type is None:
            logger.debug("Moving temporary file into place: %s", self.filename)
            replace_file(self.temporary_file, self.filename)


def requirement_is_installed(expr):
    """
    Check whether a requirement is installed.

    :param expr: A requirement specification similar to those used in pip
                 requirement files (a string).
    :returns: :data:`True` if the requirement is available (installed),
              :data:`False` otherwise.
    """
    required_dist = next(parse_requirements(expr))
    try:
        installed_dist = get_distribution(required_dist.key)
        return installed_dist in required_dist
    except DistributionNotFound:
        return False


def is_installed(package_name):
    """
    Check whether a package is installed in the current environment.

    :param package_name: The name of the package (a string).
    :returns: :data:`True` if the package is installed, :data:`False` otherwise.
    """
    return package_name.lower() in (d.key.lower() for d in WorkingSet())


def uninstall(*package_names):
    """
    Uninstall one or more packages using the Python equivalent of ``pip uninstall --yes``.

    The package(s) to uninstall must be installed, otherwise pip will raise an
    ``UninstallationError``. You can check for installed packages using
    :func:`is_installed()`.

    :param package_names: The names of one or more Python packages (strings).
    """
    command = UninstallCommand()
    opts, args = command.parse_args(['--yes'] + list(package_names))
    command.run(opts, args)


def match_option(argument, short_option, long_option):
    """
    Match a command line argument against a short and long option.

    :param argument: The command line argument (a string).
    :param short_option: The short option (a string).
    :param long_option: The long option (a string).
    :returns: :data:`True` if the argument matches, :data:`False` otherwise.
    """
    return short_option[1] in argument[1:] if is_short_option(argument) else argument == long_option


def is_short_option(argument):
    """
    Check if a command line argument is a short option.

    :param argument: The command line argument (a string).
    :returns: :data:`True` if the argument is a short option, :data:`False` otherwise.
    """
    return len(argument) >= 2 and argument[0] == '-' and argument[1] != '-'


def match_option_with_value(arguments, option, value):
    """
    Check if a list of command line options contains an option with a value.

    :param arguments: The command line arguments (a list of strings).
    :param option: The long option (a string).
    :param value: The expected value (a string).
    :returns: :data:`True` if the command line contains the option/value pair,
              :data:`False` otherwise.
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
