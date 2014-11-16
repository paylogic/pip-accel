# Utility functions for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 16, 2014
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
import hashlib
import os
import pipes
import platform
import pwd
import re
import sys

# Look up the home directory of the effective user id so we can generate
# pathnames relative to the home directory.
HOME = pwd.getpwuid(os.getuid()).pw_dir

def add_archive_extension(source, target):
    """
    Make sure a Python source distribution archive has the right filename extension.

    :param source: The pathname of a readable distribution archive (a string).
    :param target: The pathname that the archive will get (a string).
    :returns: The target pathname with the right filename extension.
    """
    filetype = guess_archive_type(source)
    normalized_target = target.lower()
    if filetype == 'gzip' and not normalized_target.endswith(('.tgz', '.tar.gz')):
        target += '.tar.gz'
    elif filetype == 'bzip2' and not normalized_target.endswith('.bz2'):
        target += '.bz2'
    elif filetype == 'zip' and not normalized_target.endswith('.zip'):
        target == '.zip'
    return target

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

def guess_archive_type(pathname):
    """
    Guess the file type of a Python source distribution archive.

    Checks for known "magic" file headers to identify the type of the archive.
    Previously this used the ``file`` executable, now it checks the magic file
    headers itself. I could have used any of the numerous ``libmagic`` bindings
    on PyPI, but that would add a binary dependency to ``pip-accel`` and I
    don't want that :-).

    :param pathname: The pathname of an existing archive (a string).
    :returns: One of the strings ``gzip``, ``bzip2`` or ``zip`` or the value
              ``None`` when the filename extension cannot be guessed based on
              the file header.
    """
    with open(pathname, 'rb') as handle:
        header = handle.read(2)
    if header.startswith(b'\x1f\x8b'):
        # The gzip compression header is two bytes: 0x1F, 0x8B.
        return 'gzip'
    elif header.startswith(b'BZ'):
        # The bzip2 compression header is two bytes: B, Z.
        return 'bzip2'
    elif header.startswith(b'PK'):
        # According to Wikipedia, ZIP archives don't have an official magic
        # number, but most of the time we'll find two bytes: P, K (for Phil
        # Katz, creator of the format).
        return 'zip'

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

def sha1(text):
    """
    Calculate the hexadecimal SHA1 digest of a string.

    :param text: The string of which to calculate the SHA1 digest.
    :returns: A string of 40 hexadecimal characters.
    """
    return hashlib.sha1(str(text).encode()).hexdigest()
