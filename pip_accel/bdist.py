# Functions to manipulate Python binary distribution archives.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 28, 2014
# URL: https://github.com/paylogic/pip-accel

"""
:py:mod:`pip_accel.bdist` - Binary distribution archive manipulation
====================================================================

The functions in this module are used to create, transform and install from
binary distribution archives.
"""

# Standard library modules.
import logging
import os
import os.path
import pipes
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

# External dependencies.
from humanfriendly import Spinner, Timer, concatenate

# Modules included in our package.
from pip_accel.caches import CacheManager
from pip_accel.deps import SystemPackageManager
from pip_accel.exceptions import BuildFailed, InvalidSourceDistribution, NoBuildOutput
from pip_accel.utils import compact, makedirs

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

class BinaryDistributionManager(object):

    """Generates and transforms Python binary distributions."""

    def __init__(self, config):
        """
        Initialize the binary distribution manager.

        :param config: The pip-accel configuration (a :py:class:`.Config`
                       object).
        """
        self.config = config
        self.cache = CacheManager(config)
        self.system_package_manager = SystemPackageManager(config)

    def get_binary_dist(self, requirement):
        """
        Get the cached binary distribution that was previously built for the
        given requirement. If no binary distribution has been cached yet, a new
        binary distribution is built and added to the cache.

        Uses :py:func:`build_binary_dist()` to build binary distribution
        archives. If this fails with a build error :py:func:`get_binary_dist()`
        will use :py:class:`.SystemPackageManager` to check for and install
        missing system packages and retry the build when missing system
        packages were installed.

        :param requirement: A :py:class:`.Requirement` object.
        :returns: An iterable of tuples with two values each: A
                  :py:class:`tarfile.TarInfo` object and a file-like object.
        """
        cache_file = self.cache.get(requirement)
        if not cache_file:
            logger.debug("%s (%s) hasn't been cached yet, doing so now.", requirement.name, requirement.version)
            # Build the binary distribution.
            try:
                raw_file = self.build_binary_dist(requirement)
            except BuildFailed:
                logger.warning("Build of %s (%s) failed, checking for missing dependencies ..", requirement.name, requirement.version)
                if self.system_package_manager.install_dependencies(requirement):
                    raw_file = self.build_binary_dist(requirement)
                else:
                    raise
            # Transform the binary distribution archive into a form that we can re-use.
            transformed_file = os.path.join(tempfile.gettempdir(), os.path.basename(raw_file))
            archive = tarfile.open(transformed_file, 'w:gz')
            for member, from_handle in self.transform_binary_dist(raw_file):
                archive.addfile(member, from_handle)
            archive.close()
            # Push the binary distribution archive to all available backends.
            with open(transformed_file, 'rb') as handle:
                self.cache.put(requirement, handle)
            # Cleanup the temporary file.
            os.remove(transformed_file)
            # Get the absolute pathname of the file in the local cache.
            cache_file = self.cache.get(requirement)
        archive = tarfile.open(cache_file, 'r:gz')
        for member in archive.getmembers():
            yield member, archive.extractfile(member.name)
        archive.close()

    def build_binary_dist(self, requirement):
        """
        Build a binary distribution archive from an unpacked source distribution.

        :param requirement: A :py:class:`.Requirement` object.
        :returns: The pathname of a binary distribution archive (a string).
        :raises: :py:exc:`.BinaryDistributionError` when the original command
                and the fall back both fail to produce a binary distribution
                archive.

        This method uses the following command to build binary distributions:

        .. code-block:: sh

           $ python setup.py bdist_dumb --format=tar

        This command can fail for two main reasons:

        1. The package is missing binary dependencies.
        2. The ``setup.py`` script doesn't (properly) implement ``bdist_dumb``
           binary distribution format support.

        The first case is dealt with in :py:func:`get_binary_dist()`. To deal
        with the second case this method falls back to the following command:

        .. code-block:: sh

           $ python setup.py bdist

        This fall back is almost never needed, but there are Python packages
        out there which require this fall back (this method was added because
        the installation of ``Paver==1.2.3`` failed, see `issue 37`_ for
        details about that).

        .. _issue 37: https://github.com/paylogic/pip-accel/issues/37
        """
        try:
            return self.build_binary_dist_helper(requirement, ['bdist_dumb', '--format=tar'])
        except (BuildFailed, NoBuildOutput):
            logger.warning("Build of %s (%s) failed, falling back to alternative method ..",
                           requirement.name, requirement.version)
            return self.build_binary_dist_helper(requirement, ['bdist'])

    def build_binary_dist_helper(self, requirement, setup_command):
        """
        Convert a single, unpacked source distribution to a binary
        distribution. Raises an exception if it fails to create the binary
        distribution (probably because of missing binary dependencies like
        system libraries).

        :param requirement: A :py:class:`.Requirement` object.
        :param setup_command: A list of strings with the arguments to
                              ``setup.py``.
        :returns: The pathname of the resulting binary distribution (a string).
        :raises: :py:exc:`.BuildFailed` when the build reports an error.
        :raises: :py:exc:`.NoBuildOutput` when the build does not produce the
                 expected binary distribution archive.
        """
        build_timer = Timer()
        # Make sure the source distribution contains a setup script.
        setup_script = os.path.join(requirement.source_directory, 'setup.py')
        if not os.path.isfile(setup_script):
            msg = "Directory %s (%s %s) doesn't contain a source distribution!"
            raise InvalidSourceDistribution(msg % (requirement.source_directory, requirement.name, requirement.version))
        # Let the user know what's going on.
        build_text = "Building %s (%s) binary distribution" % (requirement.name, requirement.version)
        logger.info("%s ..", build_text)
        # Cleanup previously generated distributions.
        dist_directory = os.path.join(requirement.source_directory, 'dist')
        if os.path.isdir(dist_directory):
            logger.debug("Cleaning up previously generated distributions in %s ..", dist_directory)
            shutil.rmtree(dist_directory)
        # Compose the command line needed to build the binary distribution.
        command_line = ' '.join(pipes.quote(t) for t in [self.config.python_executable, 'setup.py'] + setup_command)
        logger.debug("Executing external command: %s", command_line)
        # Redirect all output of the build to a temporary file.
        fd, temporary_file = tempfile.mkstemp()
        command_line = '%s > "%s" 2>&1' % (command_line, temporary_file)
        try:
            # Start the build.
            build = subprocess.Popen(['sh', '-c', command_line], cwd=requirement.source_directory)
            # Wait for the build to finish and provide feedback to the user in the mean time.
            spinner = Spinner(label=build_text, timer=build_timer)
            while build.poll() is None:
                spinner.step()
                # Don't tax the CPU too much.
                time.sleep(0.2)
            spinner.clear()
            # Make sure the build succeeded and produced a binary distribution archive.
            try:
                # If the build reported an error we'll try to provide the user with
                # some hints about what went wrong.
                if build.returncode != 0:
                    raise BuildFailed("Failed to build {name} ({version}) binary distribution!",
                                      name=requirement.name, version=requirement.version)
                # Check if the build created the `dist' directory (the os.listdir()
                # call below will raise an exception if we don't check for this).
                if not os.path.isdir(dist_directory):
                    raise NoBuildOutput("Build of {name} ({version}) did not produce a binary distribution archive!",
                                        name=requirement.name, version=requirement.version)
                # Check if we can find the binary distribution archive.
                filenames = os.listdir(dist_directory)
                if len(filenames) != 1:
                    raise NoBuildOutput("Build of {name} ({version}) produced more than one distribution archive! (matches: {filenames})",
                                        name=requirement.name, version=requirement.version, filenames=concatenate(sorted(filenames)))
            except Exception as e:
                # Decorate the exception with the output of the failed build.
                with open(temporary_file) as handle:
                    build_output = handle.read()
                enhanced_message = compact("""
                    {message}

                    Please check the build output because it will probably
                    provide a hint about what went wrong.

                    Build output:

                    {output}
                """, message=e.args[0],
                     output=build_output.strip())
                e.args = (enhanced_message,)
                raise
            logger.info("Finished building %s (%s) in %s.", requirement.name, requirement.version, build_timer)
            return os.path.join(dist_directory, filenames[0])
        finally:
            os.unlink(temporary_file)

    def transform_binary_dist(self, archive_path):
        """
        Transform a binary distribution archive created by
        :py:func:`build_binary_dist()` into a form that can be cached for
        future use. This comes down to making the pathnames inside the archive
        relative to the `prefix` that the binary distribution was built for.

        :param archive_path: The pathname of the original binary distribution archive.
        :returns: An iterable of tuples with two values each:

                  1. A :py:class:`tarfile.TarInfo` object.
                  2. A file-like object.
        """
        # Copy the tar archive file by file so we can rewrite the pathnames.
        logger.debug("Transforming binary distribution: %s.", archive_path)
        archive = tarfile.open(archive_path, 'r')
        for member in archive.getmembers():
            # Some source distribution archives on PyPI that are distributed as ZIP
            # archives contain really weird permissions: the world readable bit is
            # missing. I've encountered this with the httplib2 (0.9) and
            # google-api-python-client (1.2) packages. I assume this is a bug of
            # some kind in the packaging process on "their" side.
            if member.mode & stat.S_IXUSR:
                # If the owner has execute permissions we'll give everyone read and
                # execute permissions (only the owner gets write permissions).
                member.mode = 0o755
            else:
                # If the owner doesn't have execute permissions we'll give everyone
                # read permissions (only the owner gets write permissions).
                member.mode = 0o644
            # In my testing the `dumb' tar files created with the `python setup.py
            # bdist' command contain pathnames that are relative to `/' which is
            # kind of awkward: I would like to use os.path.relpath() on them but
            # that won't give the correct result without some preprocessing...
            original_pathname = member.name
            absolute_pathname = re.sub(r'^\./', '/', original_pathname)
            if member.isdev():
                logger.warn("Ignoring device file: %s.", absolute_pathname)
            elif not member.isdir():
                modified_pathname = os.path.relpath(absolute_pathname, self.config.install_prefix)
                if os.path.isabs(modified_pathname):
                    logger.warn("Failed to transform pathname in binary distribution to relative path! (original: %r, modified: %r)",
                                original_pathname, modified_pathname)
                else:
                    # Rewrite /usr/local to /usr (same goes for all prefixes of course).
                    modified_pathname = re.sub('^local/', '', modified_pathname)
                    # Rewrite /dist-packages/ to /site-packages/. For details see
                    # https://wiki.debian.org/Python#Deviations_from_upstream.
                    if self.config.on_debian:
                        modified_pathname = modified_pathname.replace('/dist-packages/', '/site-packages/')
                    # Enable operators to debug the transformation process.
                    logger.debug("Transformed %r -> %r.", original_pathname, modified_pathname)
                    # Get the file data from the input archive.
                    handle = archive.extractfile(original_pathname)
                    # Yield the pathname, file mode and a handle to the data.
                    member.name = modified_pathname
                    yield member, handle
        archive.close()

    def install_binary_dist(self, members, virtualenv_compatible=True, prefix=None, python=None):
        """
        Install a binary distribution created by :py:class:`build_binary_dist()`
        into the given prefix (a directory like ``/usr``, ``/usr/local`` or a
        virtual environment).

        :param members: An iterable of tuples with two values each:

                        1. A :py:class:`tarfile.TarInfo` object.
                        2. A file-like object.
        :param prefix: The "prefix" under which the requirements should be
                       installed. This will be a pathname like ``/usr``,
                       ``/usr/local`` or the pathname of a virtual environment.
                       Defaults to :py:attr:`.Config.install_prefix`.
        :param python: The pathname of the Python executable to use in the shebang
                       line of all executable Python scripts inside the binary
                       distribution. Defaults to :py:attr:`.Config.python_executable`.
        :param virtualenv_compatible: Whether to enable workarounds to make the
                                      resulting filenames compatible with
                                      virtual environments (defaults to
                                      ``True``).
        """
        # TODO This is quite slow for modules like Django. Speed it up! Two choices:
        #  1. Run the external tar program to unpack the archive. This will
        #     slightly complicate the fixing up of hashbangs.
        #  2. Using links? The plan: We can maintain a "seed" environment under
        #     $PIP_ACCEL_CACHE and use symbolic and/or hard links to populate other
        #     places based on the "seed" environment.
        module_search_path = set(map(os.path.normpath, sys.path))
        prefix = os.path.normpath(prefix or self.config.install_prefix)
        python = os.path.normpath(python or self.config.python_executable)
        for member, from_handle in members:
            pathname = member.name
            if virtualenv_compatible:
                # Some binary distributions include C header files (see for example
                # the greenlet package) however the subdirectory of include/ in a
                # virtual environment is a symbolic link to a subdirectory of
                # /usr/include/ so we should never try to install C header files
                # inside the directory pointed to by the symbolic link. Instead we
                # implement the same workaround that pip uses to avoid this
                # problem.
                pathname = re.sub('^include/', 'include/site/', pathname)
            if self.config.on_debian and '/site-packages/' in pathname:
                # On Debian based system wide Python installs the /site-packages/
                # directory is not in Python's module search path while
                # /dist-packages/ is. We try to be compatible with this.
                match = re.match('^(.+?)/site-packages', pathname)
                if match:
                    site_packages = os.path.normpath(os.path.join(prefix, match.group(0)))
                    dist_packages = os.path.normpath(os.path.join(prefix, match.group(1), 'dist-packages'))
                    if dist_packages in module_search_path and site_packages not in module_search_path:
                        pathname = pathname.replace('/site-packages/', '/dist-packages/')
            pathname = os.path.join(prefix, pathname)
            directory = os.path.dirname(pathname)
            if not os.path.isdir(directory):
                logger.debug("Creating directory: %s ..", directory)
                makedirs(directory)
            logger.debug("Creating file: %s ..", pathname)
            with open(pathname, 'wb') as to_handle:
                contents = from_handle.read()
                if contents.startswith(b'#!/'):
                    contents = self.fix_hashbang(contents, python)
                to_handle.write(contents)
            os.chmod(pathname, member.mode)

    def fix_hashbang(self, contents, python):
        """
        Rewrite the hashbang_ in an executable script so that the correct
        Python executable is used.

        :param contents: The contents of the script whose hashbang should be
                         fixed (a string).
        :param python: The absolute pathname of the Python executable (a
                       string).
        :returns: The modified contents of the script (a string).

        .. _hashbang: http://en.wikipedia.org/wiki/Shebang_(Unix)
        """
        lines = contents.splitlines()
        if lines:
            hashbang = lines[0]
            # Get the base name of the command in the hashbang.
            executable = os.path.basename(hashbang)
            # Deal with hashbangs like `#!/usr/bin/env python'.
            executable = re.sub(b'^env ', b'', executable)
            # Only rewrite hashbangs that actually involve Python.
            if re.match(b'^python(\\d+(\\.\\d+)*)?$', executable):
                lines[0] = b'#!' + python.encode('ascii')
                logger.debug("Rewriting hashbang %r to %r!", hashbang, lines[0])
                contents = b'\n'.join(lines)
        return contents
