# Functions to manipulate Python binary distribution archives.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: May 24, 2014
# URL: https://github.com/paylogic/pip-accel

"""
Binary distribution archive manipulation
========================================

The functions in this module are used to create, transform and install from
binary distribution archives.
"""

# Standard library modules.
import hashlib
import logging
import os
import os.path
import pipes
import re
import shutil
import subprocess
import tarfile
import tempfile
import time

# External dependencies.
from humanfriendly import Spinner, Timer

# Modules included in our package.
from pip_accel.config import binary_index
from pip_accel.deps import sanity_check_dependencies
from pip_accel.utils import get_python_version

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

def get_binary_dist(package, version, directory, url=None, python='/usr/bin/python', prefix='/usr'):
    """
    Get the cached binary distribution archive that was previously built for
    the given package (name, version) (and optionally URL). If no archive has
    been cached yet, a new binary distribution archive is created and added to
    the cache.

    :param package: The name of the requirement to build.
    :param version: The version of the requirement to build.
    :param directory: The directory where the unpacked sources of the
                      requirement are available.
    :param url: The URL of the requirement, optional. When given this is used
                to generate the filename of the cached binary distribution.
    :param python: The pathname of the Python executable to use to run
                   ``setup.py`` (obviously this should point to a working
                   Python installation).
    :param prefix: The prefix that the original binary distribution was created for.
    :returns: An iterable of tuples with two values each: A
              :py:class:`tarfile.TarInfo` object and a file-like object.
    """
    tag = hashlib.sha1(str(version + url).encode()).hexdigest() if url else version
    cache_file = os.path.join(binary_index, '%s:%s:%s.tar.gz' % (package, tag, get_python_version()))
    if not os.path.isfile(cache_file):
        logger.debug("%s (%s) hasn't been cached yet, doing so now.", package, version)
        # Build the binary distribution.
        try:
            raw_file = build_binary_dist(package, version, directory, python=python)
        except BuildFailed:
            sanity_check_dependencies(package)
            raw_file = build_binary_dist(package, version, directory, python=python)
        # Transform the binary distribution archive into a form that we can re-use.
        transformed_file = '%s.tmp-%i' % (cache_file, os.getpid())
        archive = tarfile.open(transformed_file, 'w:gz')
        for member, from_handle in transform_binary_dist(raw_file, prefix=prefix):
            archive.addfile(member, from_handle)
        archive.close()
        # Try to avoid race conditions between multiple processes by atomically
        # moving the transformed binary distribution into its final place.
        os.rename(transformed_file, cache_file)
        logger.debug("%s (%s) cached as %s.", package, version, cache_file)
    archive = tarfile.open(cache_file, 'r:gz')
    for member in archive.getmembers():
        yield member, archive.extractfile(member.name)
    archive.close()

def build_binary_dist(package, version, directory, python='/usr/bin/python'):
    """
    Convert a single, unpacked source distribution to a binary distribution.
    Raises an exception if it fails to create the binary distribution (probably
    because of missing binary dependencies like system libraries).

    :param package: The name of the requirement to build.
    :param version: The version of the requirement to build.
    :param directory: The directory where the unpacked sources of the
                      requirement are available.
    :param python: The pathname of the Python executable to use to run
                   ``setup.py`` (obviously this should point to a working
                   Python installation).
    :returns: The pathname of the resulting binary distribution (a string).
    """
    build_timer = Timer()
    # Make sure the source distribution contains a setup script.
    setup_script = os.path.join(directory, 'setup.py')
    if not os.path.isfile(setup_script):
        msg = "Directory %s (%s %s) doesn't contain a source distribution!"
        raise InvalidSourceDistribution(msg % (directory, package, version))
    # Let the user know what's going on.
    build_text = "Building binary distribution of %s (%s) .." % (package, version)
    logger.info("%s", build_text)
    # Cleanup previously generated distributions.
    dist_directory = os.path.join(directory, 'dist')
    if os.path.isdir(dist_directory):
        logger.debug("Cleaning up previously generated distributions in %s ..", dist_directory)
        shutil.rmtree(dist_directory)
    # Compose the command line needed to build the binary distribution.
    command_line = '%s setup.py bdist_dumb --format=tar' % pipes.quote(python)
    logger.debug("Executing external command: %s", command_line)
    # Redirect all output of the build to a temporary file.
    fd, temporary_file = tempfile.mkstemp()
    command_line = '%s > "%s" 2>&1' % (command_line, temporary_file)
    try:
        # Start the build.
        build = subprocess.Popen(['sh', '-c', command_line], cwd=directory)
        # Wait for build to finish, provide feedback to the user in the mean time.
        spinner = Spinner(build_text)
        while build.poll() is None:
            spinner.step()
            time.sleep(0.1)
        spinner.clear()
        # Check whether the build succeeded.
        if build.returncode != 0:
            # It it didn't we'll provide the user with some hints as to what went wrong.
            msg = "Failed to build binary distribution of %s (%s)!" % (package, version)
            logger.error("%s", msg)
            with open(temporary_file) as handle:
                logger.info("Build output (will probably provide a hint as to what went wrong):\n%s", handle.read())
            raise BuildFailed(msg)
        # Check if we can find the binary distribution archive.
        filenames = os.listdir(dist_directory)
        if len(filenames) != 1:
            msg = "Build process did not result in one binary distribution! (matches: %s)"
            raise NoBuildOutput(msg % filenames)
        logger.info("Finished building %s (%s) in %s.", package, version, build_timer)
        return os.path.join(dist_directory, filenames[0])
    finally:
        os.unlink(temporary_file)

def transform_binary_dist(archive_path, prefix='/usr'):
    """
    Transform a binary distribution archive created with ``python setup.py
    bdist_dumb --format=tar`` into a form that can be cached for future use.
    This comes down to making the pathnames inside the archive relative to the
    `prefix` that the binary distribution was built for.

    :param archive_path: The pathname of the original binary distribution archive.
    :param prefix: The prefix that the original binary distribution was created for.
    :returns: An iterable of tuples with two values each: A
              :py:class:`tarfile.TarInfo` object and a file-like object.
    """
    # Copy the tar archive file by file so we can rewrite the pathnames.
    logger.debug("Transforming binary distribution: %s.", archive_path)
    logger.debug("Using environment prefix: %s.", prefix)
    archive = tarfile.open(archive_path, 'r')
    for member in archive.getmembers():
        # In my testing the `dumb' tar files created with the `python setup.py
        # bdist' command contain pathnames that are relative to `/' which is
        # kind of awkward: I would like to use os.path.relpath() on them but
        # that won't give the correct result without some preprocessing...
        original_pathname = member.name
        absolute_pathname = re.sub(r'^\./', '/', original_pathname)
        if member.isdev():
            logger.warn("Ignoring device file: %s.", absolute_pathname)
        elif not member.isdir():
            modified_pathname = os.path.relpath(absolute_pathname, prefix)
            if os.path.isabs(modified_pathname):
                logger.warn("Failed to transform pathname in binary distribution to relative path! (original: %r, modified: %r)",
                            original_pathname, modified_pathname)
            else:
                # Rewrite /usr/local to /usr (same goes for all prefixes of course).
                modified_pathname = re.sub('^local/', '', modified_pathname)
                logger.debug("Transformed %r -> %r.", original_pathname, modified_pathname)
                # Get the file data from the input archive.
                handle = archive.extractfile(original_pathname)
                # Yield the pathname, file mode and a handle to the data.
                member.name = modified_pathname
                yield member, handle
    archive.close()

def install_binary_dist(members, prefix, python='/usr/bin/python', enable_workarounds=True):
    """
    Install a binary distribution created with ``python setup.py bdist`` into
    the given prefix (a directory like ``/usr``, ``/usr/local`` or a virtual
    environment).

    :param members: An iterable of tuples with three values each:
                    (pathname, mode, handle).
    :param prefix: The "prefix" under which the requirements should be
                   installed. This will be a pathname like ``/usr``,
                   ``/usr/local`` or the pathname of a virtual environment.
    :param python: The pathname of the Python executable to use in the shebang
                   line of all executable Python scripts inside the binary
                   distribution.
    :param enable_workarounds: Enable workarounds to make the resulting filenames
                               compatible with virtual environments.
    """
    # TODO This is quite slow for modules like Django. Speed it up! Two choices:
    #  1. Run the external tar program to unpack the archive. This will
    #     slightly complicate the fixing up of hashbangs.
    #  2. Using links? The plan: We can maintain a "seed" environment under
    #     $PIP_ACCEL_CACHE and use symbolic and/or hard links to populate other
    #     places based on the "seed" environment.
    for member, from_handle in members:
        pathname = member.name
        # Some binary distributions include C header files (see for example the
        # greenlet package) however the subdirectory of include/ in a virtual
        # environment is a symbolic link to a subdirectory of /usr/include/ so
        # we should never try to install C header files inside the directory
        # pointed to by the symbolic link. Instead we implement the same
        # workaround that pip uses to avoid this problem.
        if enable_workarounds:
            pathname = re.sub('^include/', 'include/site/', pathname)
        pathname = os.path.join(prefix, pathname)
        directory = os.path.dirname(pathname)
        if not os.path.isdir(directory):
            logger.debug("Creating directory: %s ..", directory)
            os.makedirs(directory)
        logger.debug("Creating file: %s ..", pathname)
        with open(pathname, 'wb') as to_handle:
            contents = from_handle.read()
            if contents.startswith(b'#!/'):
                contents = fix_hashbang(python, contents)
            to_handle.write(contents)
        os.chmod(pathname, member.mode)

def fix_hashbang(python, contents):
    """
    Rewrite the hashbang in an executable script so that the Python program
    inside the virtual environment is used instead of a system wide Python.

    :param python: The absolute pathname of the Python program inside the
                   virtual environment.
    :param contents: A string with the contents of the script whose hashbang
                     should be fixed.
    :returns: The modified contents of the script as a string.
    """
    # Separate the first line in the file from the remainder of the contents
    # while preserving the end of line sequence (CR+LF or just an LF) and
    # without having to split all lines in the file (there's no point).
    lines = contents.splitlines()
    hashbang = lines[0]
    # Get the base name of the command in the hashbang and deal with hashbangs
    # like `#!/usr/bin/env python'.
    modified_name = re.sub(b'^env ', b'', os.path.basename(hashbang))
    # Only rewrite hashbangs that actually involve Python.
    if re.match(b'^python(\\d+(\\.\\d+)*)?$', modified_name):
        lines[0] = b'#!' + python.encode('ascii')
        logger.debug("Hashbang %r looks like a Python hashbang! Rewriting it to %r!", hashbang, lines[0])
        contents = b'\n'.join(lines)
    else:
        logger.debug("Warning: Failed to match hashbang: %r.", hashbang)
    return contents

class InvalidSourceDistribution(Exception):
    """
    Raised by :py:func:`build_binary_dist()` when the given directory doesn't
    contain a source distribution.
    """

class BuildFailed(Exception):
    """
    Raised by :py:func:`build_binary_dist()` when a binary distribution build fails.
    """

class NoBuildOutput(Exception):
    """
    Raised by :py:func:`build_binary_dist()` when a binary distribution build
    fails to produce a binary distribution archive.
    """
