# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: November 7, 2015
# URL: https://github.com/paylogic/pip-accel

"""
Functions to manipulate Python binary distribution archives.

The functions in this module are used to create, transform and install from
binary distribution archives (which are not supported by tools like
easy_install and pip).
"""

# Standard library modules.
import errno
import fnmatch
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
from pip_accel.utils import AtomicReplace, compact, makedirs

# Initialize a logger for this module.
logger = logging.getLogger(__name__)


class BinaryDistributionManager(object):

    """Generates and transforms Python binary distributions."""

    def __init__(self, config):
        """
        Initialize the binary distribution manager.

        :param config: The pip-accel configuration (a :class:`.Config`
                       object).
        """
        self.config = config
        self.cache = CacheManager(config)
        self.system_package_manager = SystemPackageManager(config)

    def get_binary_dist(self, requirement):
        """
        Get or create a cached binary distribution archive.

        :param requirement: A :class:`.Requirement` object.
        :returns: An iterable of tuples with two values each: A
                  :class:`tarfile.TarInfo` object and a file-like object.

        Gets the cached binary distribution that was previously built for the
        given requirement. If no binary distribution has been cached yet, a new
        binary distribution is built and added to the cache.

        Uses :func:`build_binary_dist()` to build binary distribution
        archives. If this fails with a build error :func:`get_binary_dist()`
        will use :class:`.SystemPackageManager` to check for and install
        missing system packages and retry the build when missing system
        packages were installed.
        """
        cache_file = self.cache.get(requirement)
        if cache_file:
            if self.needs_invalidation(requirement, cache_file):
                logger.info("Invalidating old %s binary (source has changed) ..", requirement)
                cache_file = None
        else:
            logger.debug("%s hasn't been cached yet, doing so now.", requirement)
        if not cache_file:
            # Build the binary distribution.
            try:
                raw_file = self.build_binary_dist(requirement)
            except BuildFailed:
                logger.warning("Build of %s failed, checking for missing dependencies ..", requirement)
                if self.system_package_manager.install_dependencies(requirement):
                    raw_file = self.build_binary_dist(requirement)
                else:
                    raise
            # Transform the binary distribution archive into a form that we can re-use.
            fd, transformed_file = tempfile.mkstemp(prefix='pip-accel-bdist-', suffix='.tar.gz')
            try:
                archive = tarfile.open(transformed_file, 'w:gz')
                try:
                    for member, from_handle in self.transform_binary_dist(raw_file):
                        archive.addfile(member, from_handle)
                finally:
                    archive.close()
                # Push the binary distribution archive to all available backends.
                with open(transformed_file, 'rb') as handle:
                    self.cache.put(requirement, handle)
            finally:
                # Close file descriptor before removing the temporary file.
                # Without closing Windows is complaining that the file cannot
                # be removed because it is used by another process.
                os.close(fd)
                # Cleanup the temporary file.
                os.remove(transformed_file)
            # Get the absolute pathname of the file in the local cache.
            cache_file = self.cache.get(requirement)
            # Enable checksum based cache invalidation.
            self.persist_checksum(requirement, cache_file)
        archive = tarfile.open(cache_file, 'r:gz')
        try:
            for member in archive.getmembers():
                yield member, archive.extractfile(member.name)
        finally:
            archive.close()

    def needs_invalidation(self, requirement, cache_file):
        """
        Check whether a cached binary distribution needs to be invalidated.

        :param requirement: A :class:`.Requirement` object.
        :param cache_file: The pathname of a cached binary distribution (a string).
        :returns: :data:`True` if the cached binary distribution needs to be
                  invalidated, :data:`False` otherwise.
        """
        if self.config.trust_mod_times:
            return requirement.last_modified > os.path.getmtime(cache_file)
        else:
            checksum = self.recall_checksum(cache_file)
            return checksum and checksum != requirement.checksum

    def recall_checksum(self, cache_file):
        """
        Get the checksum of the input used to generate a binary distribution archive.

        :param cache_file: The pathname of the binary distribution archive (a string).
        :returns: The checksum (a string) or :data:`None` (when no checksum is available).
        """
        # EAFP instead of LBYL because of concurrency between pip-accel
        # processes (https://docs.python.org/2/glossary.html#term-lbyl).
        checksum_file = '%s.txt' % cache_file
        try:
            with open(checksum_file) as handle:
                contents = handle.read()
            return contents.strip()
        except IOError as e:
            if e.errno == errno.ENOENT:
                # Gracefully handle missing checksum files.
                return None
            else:
                # Don't swallow exceptions we don't expect!
                raise

    def persist_checksum(self, requirement, cache_file):
        """
        Persist the checksum of the input used to generate a binary distribution.

        :param requirement: A :class:`.Requirement` object.
        :param cache_file: The pathname of a cached binary distribution (a string).

        .. note:: The checksum is only calculated and persisted when
                  :attr:`~.Config.trust_mod_times` is :data:`False`.
        """
        if not self.config.trust_mod_times:
            checksum_file = '%s.txt' % cache_file
            with AtomicReplace(checksum_file) as temporary_file:
                with open(temporary_file, 'w') as handle:
                    handle.write('%s\n' % requirement.checksum)

    def build_binary_dist(self, requirement):
        """
        Build a binary distribution archive from an unpacked source distribution.

        :param requirement: A :class:`.Requirement` object.
        :returns: The pathname of a binary distribution archive (a string).
        :raises: :exc:`.BinaryDistributionError` when the original command
                and the fall back both fail to produce a binary distribution
                archive.

        This method uses the following command to build binary distributions:

        .. code-block:: sh

           $ python setup.py bdist_dumb --format=tar

        This command can fail for two main reasons:

        1. The package is missing binary dependencies.
        2. The ``setup.py`` script doesn't (properly) implement ``bdist_dumb``
           binary distribution format support.

        The first case is dealt with in :func:`get_binary_dist()`. To deal
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
            logger.warning("Build of %s failed, falling back to alternative method ..", requirement)
            return self.build_binary_dist_helper(requirement, ['bdist', '--formats=gztar'])

    def build_binary_dist_helper(self, requirement, setup_command):
        """
        Convert an unpacked source distribution to a binary distribution.

        :param requirement: A :class:`.Requirement` object.
        :param setup_command: A list of strings with the arguments to
                              ``setup.py``.
        :returns: The pathname of the resulting binary distribution (a string).
        :raises: :exc:`.BuildFailed` when the build reports an error (e.g.
                 because of missing binary dependencies like system
                 libraries).
        :raises: :exc:`.NoBuildOutput` when the build does not produce the
                 expected binary distribution archive.
        """
        build_timer = Timer()
        # Make sure the source distribution contains a setup script.
        setup_script = os.path.join(requirement.source_directory, 'setup.py')
        if not os.path.isfile(setup_script):
            msg = "Directory %s (%s %s) doesn't contain a source distribution!"
            raise InvalidSourceDistribution(msg % (requirement.source_directory, requirement.name, requirement.version))
        # Let the user know what's going on.
        build_text = "Building %s binary distribution" % requirement
        logger.info("%s ..", build_text)
        # Cleanup previously generated distributions.
        dist_directory = os.path.join(requirement.source_directory, 'dist')
        if os.path.isdir(dist_directory):
            logger.debug("Cleaning up previously generated distributions in %s ..", dist_directory)
            shutil.rmtree(dist_directory)
        # Let the user know (approximately) which command is being executed
        # (I don't think it's necessary to show them the nasty details :-).
        logger.debug("Executing external command: %s",
                     ' '.join(map(pipes.quote, [self.config.python_executable, 'setup.py'] + setup_command)))
        # Compose the command line needed to build the binary distribution.
        # This nasty command line forces the use of setuptools (instead of
        # distutils) just like pip does. This will cause the `*.egg-info'
        # metadata to be written to a directory instead of a file, which
        # (amongst other things) enables tracking of installed files.
        command_line = [
            self.config.python_executable, '-c',
            ';'.join([
                'import setuptools',
                '__file__=%r' % setup_script,
                r"exec(compile(open(__file__).read().replace('\r\n', '\n'), __file__, 'exec'))",
            ])
        ] + setup_command
        # Redirect all output of the build to a temporary file.
        fd, temporary_file = tempfile.mkstemp()
        try:
            # Start the build.
            build = subprocess.Popen(command_line, cwd=requirement.source_directory, stdout=fd, stderr=fd)
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
                    variables = dict(name=requirement.name,
                                     version=requirement.version,
                                     filenames=concatenate(sorted(filenames)))
                    raise NoBuildOutput("""
                        Build of {name} ({version}) produced more than one
                        distribution archive! (matches: {filenames})
                    """, **variables)
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
                """, message=e.args[0], output=build_output.strip())
                e.args = (enhanced_message,)
                raise
            logger.info("Finished building %s in %s.", requirement.name, build_timer)
            return os.path.join(dist_directory, filenames[0])
        finally:
            # Close file descriptor before removing the temporary file.
            # Without closing Windows is complaining that the file cannot
            # be removed because it is used by another process.
            os.close(fd)
            os.unlink(temporary_file)

    def transform_binary_dist(self, archive_path):
        """
        Transform binary distributions into a form that can be cached for future use.

        :param archive_path: The pathname of the original binary distribution archive.
        :returns: An iterable of tuples with two values each:

                  1. A :class:`tarfile.TarInfo` object.
                  2. A file-like object.

        This method transforms a binary distribution archive created by
        :func:`build_binary_dist()` into a form that can be cached for future
        use. This comes down to making the pathnames inside the archive
        relative to the `prefix` that the binary distribution was built for.
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
            # In my testing the `dumb' tar files created with the `python
            # setup.py bdist' and `python setup.py bdist_dumb' commands contain
            # pathnames that are relative to `/' in one way or another:
            #
            #  - In almost all cases the pathnames look like this:
            #
            #      ./home/peter/.virtualenvs/pip-accel/lib/python2.7/site-packages/pip_accel/__init__.py
            #
            #  - After working on pip-accel for several years I encountered
            #    a pathname like this (Python 2.6 on Mac OS X 10.10.5):
            #
            #      Users/peter/.virtualenvs/pip-accel/lib/python2.6/site-packages/pip_accel/__init__.py
            #
            # Both of the above pathnames are relative to `/' but in different
            # ways :-). The following normpath(join('/', ...))) pathname
            # manipulation logic is intended to handle both cases.
            original_pathname = member.name
            absolute_pathname = os.path.normpath(os.path.join('/', original_pathname))
            if member.isdev():
                logger.warn("Ignoring device file: %s.", absolute_pathname)
            elif not member.isdir():
                modified_pathname = os.path.relpath(absolute_pathname, self.config.install_prefix)
                if os.path.isabs(modified_pathname):
                    logger.warn("Failed to transform pathname in binary distribution"
                                " to relative path! (original: %r, modified: %r)",
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
                    # Yield the modified metadata and a handle to the data.
                    member.name = modified_pathname
                    yield member, handle
        archive.close()

    def install_binary_dist(self, members, virtualenv_compatible=True, prefix=None,
                            python=None, track_installed_files=False):
        """
        Install a binary distribution into the given prefix.

        :param members: An iterable of tuples with two values each:

                        1. A :class:`tarfile.TarInfo` object.
                        2. A file-like object.
        :param prefix: The "prefix" under which the requirements should be
                       installed. This will be a pathname like ``/usr``,
                       ``/usr/local`` or the pathname of a virtual environment.
                       Defaults to :attr:`.Config.install_prefix`.
        :param python: The pathname of the Python executable to use in the shebang
                       line of all executable Python scripts inside the binary
                       distribution. Defaults to :attr:`.Config.python_executable`.
        :param virtualenv_compatible: Whether to enable workarounds to make the
                                      resulting filenames compatible with
                                      virtual environments (defaults to
                                      :data:`True`).
        :param track_installed_files: If this is :data:`True` (not the default for
                                      this method because of backwards
                                      compatibility) pip-accel will create
                                      ``installed-files.txt`` as required by
                                      pip to properly uninstall packages.

        This method installs a binary distribution created by
        :class:`build_binary_dist()` into the given prefix (a directory like
        ``/usr``, ``/usr/local`` or a virtual environment).
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
        installed_files = []
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
            if track_installed_files:
                # Track the installed file's absolute pathname.
                installed_files.append(pathname)
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
        if track_installed_files:
            self.update_installed_files(installed_files)

    def fix_hashbang(self, contents, python):
        """
        Rewrite hashbangs_ to use the correct Python executable.

        :param contents: The contents of the script whose hashbang should be
                         fixed (a string).
        :param python: The absolute pathname of the Python executable (a
                       string).
        :returns: The modified contents of the script (a string).

        .. _hashbangs: http://en.wikipedia.org/wiki/Shebang_(Unix)
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

    def update_installed_files(self, installed_files):
        """
        Track the files installed by a package so pip knows how to remove the package.

        This method is used by :func:`install_binary_dist()` (which collects
        the list of installed files for :func:`update_installed_files()`).

        :param installed_files: A list of absolute pathnames (strings) with the
                                files that were just installed.
        """
        # Find the *.egg-info directory where installed-files.txt should be created.
        pkg_info_files = [fn for fn in installed_files if fnmatch.fnmatch(fn, '*.egg-info/PKG-INFO')]
        # I'm not (yet) sure how reliable the above logic is, so for now
        # I'll err on the side of caution and only act when the results
        # seem to be reliable.
        if len(pkg_info_files) != 1:
            logger.warning("Not tracking installed files (couldn't reliably determine *.egg-info directory)")
        else:
            egg_info_directory = os.path.dirname(pkg_info_files[0])
            installed_files_path = os.path.join(egg_info_directory, 'installed-files.txt')
            logger.debug("Tracking installed files in %s ..", installed_files_path)
            with open(installed_files_path, 'w') as handle:
                for pathname in installed_files:
                    handle.write('%s\n' % os.path.relpath(pathname, egg_info_directory))
