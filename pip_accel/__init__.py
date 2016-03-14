# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: March 14, 2016
# URL: https://github.com/paylogic/pip-accel
#
# TODO Permanently store logs in the pip-accel directory (think about log rotation).
# TODO Maybe we should save the output of `python setup.py bdist_dumb` somewhere as well?

"""
Top level functionality of `pip-accel`.

The Python module :mod:`pip_accel` defines the classes that implement the
top level functionality of the pip accelerator. Instead of using the
``pip-accel`` command you can also use the pip accelerator as a Python module,
in this case you'll probably want to start by taking a look at
the :class:`PipAccelerator` class.

Wheel support
-------------

During the upgrade to pip 6 support for installation of wheels_ was added to
pip-accel. The ``pip-accel`` command line program now downloads and installs
wheels when available for a given requirement, but part of pip-accel's Python
API defaults to the more conservative choice of allowing callers to opt-in to
wheel support.

This is because previous versions of pip-accel would only download source
distributions and pip-accel provides the functionality to convert those source
distributions to "dumb binary distributions". This functionality is exposed to
callers who may depend on this mode of operation. So for now users of the
Python API get to decide whether they're interested in wheels or not.

Setuptools upgrade
~~~~~~~~~~~~~~~~~~

If the requirement set includes wheels and ``setuptools >= 0.8`` is not yet
installed, it will be added to the requirement set and installed together with
the other requirement(s) in order to enable the usage of distributions
installed from wheels (their metadata is different).

.. _wheels: https://pypi.python.org/pypi/wheel
"""

# Standard library modules.
import logging
import os
import os.path
import shutil
import sys
import tempfile

# Modules included in our package.
from pip_accel.bdist import BinaryDistributionManager
from pip_accel.compat import basestring
from pip_accel.exceptions import EnvironmentMismatchError, NothingToDoError
from pip_accel.req import Requirement, TransactionalUpdate
from pip_accel.utils import (
    create_file_url,
    hash_files,
    is_installed,
    makedirs,
    match_option,
    match_option_with_value,
    requirement_is_installed,
    same_directories,
    uninstall,
)

# External dependencies.
from humanfriendly import concatenate, Timer, pluralize
from pip import index as pip_index_module
from pip import wheel as pip_wheel_module
from pip.commands import install as pip_install_module
from pip.commands.install import InstallCommand
from pip.exceptions import DistributionNotFound
from pip.req import InstallRequirement

# Semi-standard module versioning.
__version__ = '0.43'

# Initialize a logger for this module.
logger = logging.getLogger(__name__)


class PipAccelerator(object):

    """
    Accelerator for pip, the Python package manager.

    The :class:`PipAccelerator` class brings together the top level logic of
    pip-accel. This top level logic was previously just a collection of
    functions but that became more unwieldy as the amount of internal state
    increased. The :class:`PipAccelerator` class is intended to make it
    (relatively) easy to build something on top of pip and pip-accel.
    """

    def __init__(self, config, validate=True):
        """
        Initialize the pip accelerator.

        :param config: The pip-accel configuration (a :class:`.Config`
                       object).
        :param validate: :data:`True` to run :func:`validate_environment()`,
                         :data:`False` otherwise.
        """
        self.config = config
        self.bdists = BinaryDistributionManager(self.config)
        if validate:
            self.validate_environment()
        self.initialize_directories()
        self.clean_source_index()
        # Keep a list of build directories created by pip-accel.
        self.build_directories = []
        # We hold on to returned Requirement objects so we can remove their
        # temporary sources after pip-accel has finished.
        self.reported_requirements = []
        # Keep a list of `.eggs' symbolic links created by pip-accel.
        self.eggs_links = []

    def validate_environment(self):
        """
        Make sure :data:`sys.prefix` matches ``$VIRTUAL_ENV`` (if defined).

        This may seem like a strange requirement to dictate but it avoids hairy
        issues like `documented here <https://github.com/paylogic/pip-accel/issues/5>`_.

        The most sneaky thing is that ``pip`` doesn't have this problem
        (de-facto) because ``virtualenv`` copies ``pip`` wherever it goes...
        (``pip-accel`` on the other hand has to be installed by the user).
        """
        environment = os.environ.get('VIRTUAL_ENV')
        if environment:
            if not same_directories(sys.prefix, environment):
                raise EnvironmentMismatchError("""
                    You are trying to install packages in environment #1 which
                    is different from environment #2 where pip-accel is
                    installed! Please install pip-accel under environment #1 to
                    install packages there.

                    Environment #1: {environment} (defined by $VIRTUAL_ENV)

                    Environment #2: {prefix} (Python's installation prefix)
                """, environment=environment, prefix=sys.prefix)

    def initialize_directories(self):
        """Automatically create local directories required by pip-accel."""
        makedirs(self.config.source_index)
        makedirs(self.config.eggs_cache)

    def clean_source_index(self):
        """
        Cleanup broken symbolic links in the local source distribution index.

        The purpose of this method requires some context to understand. Let me
        preface this by stating that I realize I'm probably overcomplicating
        things, but I like to preserve forward / backward compatibility when
        possible and I don't feel like dropping everyone's locally cached
        source distribution archives without a good reason to do so. With that
        out of the way:

        - Versions of pip-accel based on pip 1.4.x maintained a local source
          distribution index based on a directory containing symbolic links
          pointing directly into pip's download cache. When files were removed
          from pip's download cache, broken symbolic links remained in
          pip-accel's local source distribution index directory. This resulted
          in very confusing error messages. To avoid this
          :func:`clean_source_index()` cleaned up broken symbolic links
          whenever pip-accel was about to invoke pip.

        - More recent versions of pip (6.x) no longer support the same style of
          download cache that contains source distribution archives that can be
          re-used directly by pip-accel. To cope with the changes in pip 6.x
          new versions of pip-accel tell pip to download source distribution
          archives directly into the local source distribution index directory
          maintained by pip-accel.

        - It is very reasonable for users of pip-accel to have multiple
          versions of pip-accel installed on their system (imagine a dozen
          Python virtual environments that won't all be updated at the same
          time; this is the situation I always find myself in :-). These
          versions of pip-accel will be sharing the same local source
          distribution index directory.

        - All of this leads up to the local source distribution index directory
          containing a mixture of symbolic links and regular files with no
          obvious way to atomically and gracefully upgrade the local source
          distribution index directory while avoiding fights between old and
          new versions of pip-accel :-).

        - I could of course switch to storing the new local source distribution
          index in a differently named directory (avoiding potential conflicts
          between multiple versions of pip-accel) but then I would have to
          introduce a new configuration option, otherwise everyone who has
          configured pip-accel to store its source index in a non-default
          location could still be bitten by compatibility issues.

        For now I've decided to keep using the same directory for the local
        source distribution index and to keep cleaning up broken symbolic
        links. This enables cooperating between old and new versions of
        pip-accel and avoids trashing user's local source distribution indexes.
        The main disadvantage is that pip-accel is still required to clean up
        broken symbolic links...
        """
        cleanup_timer = Timer()
        cleanup_counter = 0
        for entry in os.listdir(self.config.source_index):
            pathname = os.path.join(self.config.source_index, entry)
            if os.path.islink(pathname) and not os.path.exists(pathname):
                logger.warn("Cleaning up broken symbolic link: %s", pathname)
                os.unlink(pathname)
                cleanup_counter += 1
        logger.debug("Cleaned up %i broken symbolic links from source index in %s.", cleanup_counter, cleanup_timer)

    def install_from_arguments(self, arguments, **kw):
        """
        Download, unpack, build and install the specified requirements.

        This function is a simple wrapper for :func:`get_requirements()`,
        :func:`install_requirements()` and :func:`cleanup_temporary_directories()`
        that implements the default behavior of the pip accelerator. If you're
        extending or embedding pip-accel you may want to call the underlying
        methods instead.

        If the requirement set includes wheels and ``setuptools >= 0.8`` is not
        yet installed, it will be added to the requirement set and installed
        together with the other requirement(s) in order to enable the usage of
        distributions installed from wheels (their metadata is different).

        :param arguments: The command line arguments to ``pip install ..`` (a
                          list of strings).
        :param kw: Any keyword arguments are passed on to
                   :func:`install_requirements()`.
        :returns: The result of :func:`install_requirements()`.
        """
        try:
            requirements = self.get_requirements(arguments, use_wheels=self.arguments_allow_wheels(arguments))
            have_wheels = any(req.is_wheel for req in requirements)
            if have_wheels and not self.setuptools_supports_wheels():
                logger.info("Preparing to upgrade to setuptools >= 0.8 to enable wheel support ..")
                requirements.extend(self.get_requirements(['setuptools >= 0.8']))
            if requirements:
                if '--user' in arguments:
                    from site import USER_BASE
                    kw.setdefault('prefix', USER_BASE)
                return self.install_requirements(requirements, **kw)
            else:
                logger.info("Nothing to do! (requirements already installed)")
                return 0
        finally:
            self.cleanup_temporary_directories()

    def setuptools_supports_wheels(self):
        """
        Check whether setuptools should be upgraded to ``>= 0.8`` for wheel support.

        :returns: :data:`True` when setuptools 0.8 or higher is already
                  installed, :data:`False` otherwise (it needs to be upgraded).
        """
        return requirement_is_installed('setuptools >= 0.8')

    def get_requirements(self, arguments, max_retries=None, use_wheels=False):
        """
        Use pip to download and unpack the requested source distribution archives.

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :param max_retries: The maximum number of times that pip will be asked
                            to download distribution archives (this helps to
                            deal with intermittent failures). If this is
                            :data:`None` then :attr:`~.Config.max_retries` is
                            used.
        :param use_wheels: Whether pip and pip-accel are allowed to use wheels_
                           (:data:`False` by default for backwards compatibility
                           with callers that use pip-accel as a Python API).

        .. warning:: Requirements which are already installed are not included
                     in the result. If this breaks your use case consider using
                     pip's ``--ignore-installed`` option.
        """
        arguments = self.decorate_arguments(arguments)
        # Demote hash sum mismatch log messages from CRITICAL to DEBUG (hiding
        # implementation details from users unless they want to see them).
        with DownloadLogFilter():
            with SetupRequiresPatch(self.config, self.eggs_links):
                # Use a new build directory for each run of get_requirements().
                self.create_build_directory()
                # Check whether -U or --upgrade was given.
                if any(match_option(a, '-U', '--upgrade') for a in arguments):
                    logger.info("Checking index(es) for new version (-U or --upgrade was given) ..")
                else:
                    # If -U or --upgrade wasn't given and all requirements can be
                    # satisfied using the archives in pip-accel's local source
                    # index we don't need pip to connect to PyPI looking for new
                    # versions (that will just slow us down).
                    try:
                        return self.unpack_source_dists(arguments, use_wheels=use_wheels)
                    except DistributionNotFound:
                        logger.info("We don't have all distribution archives yet!")
                # Get the maximum number of retries from the configuration if the
                # caller didn't specify a preference.
                if max_retries is None:
                    max_retries = self.config.max_retries
                # If not all requirements are available locally we use pip to
                # download the missing source distribution archives from PyPI (we
                # retry a couple of times in case pip reports recoverable
                # errors).
                for i in range(max_retries):
                    try:
                        return self.download_source_dists(arguments, use_wheels=use_wheels)
                    except Exception as e:
                        if i + 1 < max_retries:
                            # On all but the last iteration we swallow exceptions
                            # during downloading.
                            logger.warning("pip raised exception while downloading distributions: %s", e)
                        else:
                            # On the last iteration we don't swallow exceptions
                            # during downloading because the error reported by pip
                            # is the most sensible error for us to report.
                            raise
                    logger.info("Retrying after pip failed (%i/%i) ..", i + 1, max_retries)

    def decorate_arguments(self, arguments):
        """
        Change pathnames of local files into ``file://`` URLs with ``#md5=...`` fragments.

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :returns: A copy of the command line arguments with pathnames of local
                  files rewritten to ``file://`` URLs.

        When pip-accel calls pip to download missing distribution archives and
        the user specified the pathname of a local distribution archive on the
        command line, pip will (by default) *not* copy the archive into the
        download directory if an archive for the same package name and
        version is already present.

        This can lead to the confusing situation where the user specifies a
        local distribution archive to install, a different (older) archive for
        the same package and version is present in the download directory and
        `pip-accel` installs the older archive instead of the newer archive.

        To avoid this confusing behavior, the :func:`decorate_arguments()`
        method rewrites the command line arguments given to ``pip install`` so
        that pathnames of local archives are changed into ``file://`` URLs that
        include a fragment with the hash of the file's contents. Here's an
        example:

        - Local pathname: ``/tmp/pep8-1.6.3a0.tar.gz``
        - File URL: ``file:///tmp/pep8-1.6.3a0.tar.gz#md5=19cbf0b633498ead63fb3c66e5f1caf6``

        When pip fills the download directory and encounters a previously
        cached distribution archive it will check the hash, realize the
        contents have changed and replace the archive in the download
        directory.
        """
        arguments = list(arguments)
        for i, value in enumerate(arguments):
            is_constraint_file = (i >= 1 and match_option(arguments[i - 1], '-c', '--constraint'))
            is_requirement_file = (i >= 1 and match_option(arguments[i - 1], '-r', '--requirement'))
            if not is_constraint_file and not is_requirement_file and os.path.isfile(value):
                arguments[i] = '%s#md5=%s' % (create_file_url(value), hash_files('md5', value))
        return arguments

    def unpack_source_dists(self, arguments, use_wheels=False):
        """
        Find and unpack local source distributions and discover their metadata.

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :param use_wheels: Whether pip and pip-accel are allowed to use wheels_
                           (:data:`False` by default for backwards compatibility
                           with callers that use pip-accel as a Python API).
        :returns: A list of :class:`pip_accel.req.Requirement` objects.
        :raises: Any exceptions raised by pip, for example
                 :exc:`pip.exceptions.DistributionNotFound` when not all
                 requirements can be satisfied.

        This function checks whether there are local source distributions
        available for all requirements, unpacks the source distribution
        archives and finds the names and versions of the requirements. By using
        the ``pip install --download`` command we avoid reimplementing the
        following pip features:

        - Parsing of ``requirements.txt`` (including recursive parsing).
        - Resolution of possibly conflicting pinned requirements.
        - Unpacking source distributions in multiple formats.
        - Finding the name & version of a given source distribution.
        """
        unpack_timer = Timer()
        logger.info("Unpacking distribution(s) ..")
        with PatchedAttribute(pip_install_module, 'PackageFinder', CustomPackageFinder):
            requirements = self.get_pip_requirement_set(arguments, use_remote_index=False, use_wheels=use_wheels)
            logger.info("Finished unpacking %s in %s.", pluralize(len(requirements), "distribution"), unpack_timer)
            return requirements

    def download_source_dists(self, arguments, use_wheels=False):
        """
        Download missing source distributions.

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :param use_wheels: Whether pip and pip-accel are allowed to use wheels_
                           (:data:`False` by default for backwards compatibility
                           with callers that use pip-accel as a Python API).
        :raises: Any exceptions raised by pip.
        """
        download_timer = Timer()
        logger.info("Downloading missing distribution(s) ..")
        requirements = self.get_pip_requirement_set(arguments, use_remote_index=True, use_wheels=use_wheels)
        logger.info("Finished downloading distribution(s) in %s.", download_timer)
        return requirements

    def get_pip_requirement_set(self, arguments, use_remote_index, use_wheels=False):
        """
        Get the unpacked requirement(s) specified by the caller by running pip.

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :param use_remote_index: A boolean indicating whether pip is allowed to
                                 connect to the main package index
                                 (http://pypi.python.org by default).
        :param use_wheels: Whether pip and pip-accel are allowed to use wheels_
                           (:data:`False` by default for backwards compatibility
                           with callers that use pip-accel as a Python API).
        :returns: A :class:`pip.req.RequirementSet` object created by pip.
        :raises: Any exceptions raised by pip.
        """
        # Compose the pip command line arguments. This is where a lot of the
        # core logic of pip-accel is hidden and it uses some esoteric features
        # of pip so this method is heavily commented.
        command_line = []
        # Use `--download' to instruct pip to download requirement(s) into
        # pip-accel's local source distribution index directory. This has the
        # following documented side effects (see `pip install --help'):
        #  1. It disables the installation of requirements (without using the
        #     `--no-install' option which is deprecated and slated for removal
        #     in pip 7.x).
        #  2. It ignores requirements that are already installed (because
        #     pip-accel doesn't actually need to re-install requirements that
        #     are already installed we will have work around this later, but
        #     that seems fairly simple to do).
        command_line.append('--download=%s' % self.config.source_index)
        # Use `--find-links' to point pip at pip-accel's local source
        # distribution index directory. This ensures that source distribution
        # archives are never downloaded more than once (regardless of the HTTP
        # cache that was introduced in pip 6.x).
        command_line.append('--find-links=%s' % create_file_url(self.config.source_index))
        # Use `--no-binary=:all:' to ignore wheel distributions by default in
        # order to preserve backwards compatibility with callers that expect a
        # requirement set consisting only of source distributions that can be
        # converted to `dumb binary distributions'.
        if not use_wheels and self.arguments_allow_wheels(arguments):
            command_line.append('--no-binary=:all:')
        # Use `--no-index' to force pip to only consider source distribution
        # archives contained in pip-accel's local source distribution index
        # directory. This enables pip-accel to ask pip "Can the local source
        # distribution index satisfy all requirements in the given requirement
        # set?" which enables pip-accel to keep pip off the internet unless
        # absolutely necessary :-).
        if not use_remote_index:
            command_line.append('--no-index')
        # Use `--no-clean' to instruct pip to unpack the source distribution
        # archives and *not* clean up the unpacked source distributions
        # afterwards. This enables pip-accel to replace pip's installation
        # logic with cached binary distribution archives.
        command_line.append('--no-clean')
        # Use `--build-directory' to instruct pip to unpack the source
        # distribution archives to a temporary directory managed by pip-accel.
        # We will clean up the build directory when we're done using the
        # unpacked source distributions.
        command_line.append('--build-directory=%s' % self.build_directory)
        # Append the user's `pip install ...' arguments to the command line
        # that we just assembled.
        command_line.extend(arguments)
        logger.info("Executing command: pip install %s", ' '.join(command_line))
        # Clear the build directory to prevent PreviousBuildDirError exceptions.
        self.clear_build_directory()
        # During the pip 6.x upgrade pip-accel switched to using `pip install
        # --download' which can produce an interactive prompt as described in
        # issue 51 [1]. The documented way [2] to get rid of this interactive
        # prompt is pip's --exists-action option, but due to what is most
        # likely a bug in pip this doesn't actually work. The environment
        # variable $PIP_EXISTS_ACTION does work however, so if the user didn't
        # set it we will set a reasonable default for them.
        # [1] https://github.com/paylogic/pip-accel/issues/51
        # [2] https://pip.pypa.io/en/latest/reference/pip.html#exists-action-option
        os.environ.setdefault('PIP_EXISTS_ACTION', 'w')
        # Initialize and run the `pip install' command.
        command = InstallCommand()
        opts, args = command.parse_args(command_line)
        if not opts.ignore_installed:
            # If the user didn't supply the -I, --ignore-installed option we
            # will forcefully disable the option. Refer to the documentation of
            # the AttributeOverrides class for further details.
            opts = AttributeOverrides(opts, ignore_installed=False)
        requirement_set = command.run(opts, args)
        # Make sure the output of pip and pip-accel are not intermingled.
        sys.stdout.flush()
        if requirement_set is None:
            raise NothingToDoError("""
                pip didn't generate a requirement set, most likely you
                specified an empty requirements file?
            """)
        else:
            return self.transform_pip_requirement_set(requirement_set)

    def transform_pip_requirement_set(self, requirement_set):
        """
        Transform pip's requirement set into one that `pip-accel` can work with.

        :param requirement_set: The :class:`pip.req.RequirementSet` object
                                reported by pip.
        :returns: A list of :class:`pip_accel.req.Requirement` objects.

        This function converts the :class:`pip.req.RequirementSet` object
        reported by pip into a list of :class:`pip_accel.req.Requirement`
        objects.
        """
        filtered_requirements = []
        for requirement in requirement_set.requirements.values():
            # The `satisfied_by' property is set by pip when a requirement is
            # already satisfied (i.e. a version of the package that satisfies
            # the requirement is already installed) and -I, --ignore-installed
            # is not used. We filter out these requirements because pip never
            # unpacks distributions for these requirements, so pip-accel can't
            # do anything useful with such requirements.
            if requirement.satisfied_by:
                continue
            # The `constraint' property marks requirement objects that
            # constrain the acceptable version(s) of another requirement but
            # don't define a requirement themselves, so we filter them out.
            if requirement.constraint:
                continue
            # All other requirements are reported to callers.
            filtered_requirements.append(requirement)
            self.reported_requirements.append(requirement)
        return sorted([Requirement(self.config, r) for r in filtered_requirements],
                      key=lambda r: r.name.lower())

    def install_requirements(self, requirements, **kw):
        """
        Manually install a requirement set from binary and/or wheel distributions.

        :param requirements: A list of :class:`pip_accel.req.Requirement` objects.
        :param kw: Any keyword arguments are passed on to
                   :func:`~pip_accel.bdist.BinaryDistributionManager.install_binary_dist()`.
        :returns: The number of packages that were just installed (an integer).
        """
        install_timer = Timer()
        install_types = []
        if any(not req.is_wheel for req in requirements):
            install_types.append('binary')
        if any(req.is_wheel for req in requirements):
            install_types.append('wheel')
        logger.info("Installing from %s distributions ..", concatenate(install_types))
        # Track installed files by default (unless the caller specifically opted out).
        kw.setdefault('track_installed_files', True)
        num_installed = 0
        for requirement in requirements:
            # When installing setuptools we need to uninstall distribute,
            # otherwise distribute will shadow setuptools and all sorts of
            # strange issues can occur (e.g. upgrading to the latest
            # setuptools to gain wheel support and then having everything
            # blow up because distribute doesn't know about wheels).
            if requirement.name == 'setuptools' and is_installed('distribute'):
                uninstall('distribute')
            if requirement.is_editable:
                logger.debug("Installing %s in editable form using pip.", requirement)
                with TransactionalUpdate(requirement):
                    command = InstallCommand()
                    opts, args = command.parse_args(['--no-deps', '--editable', requirement.source_directory])
                    command.run(opts, args)
            elif requirement.is_wheel:
                logger.info("Installing %s wheel distribution using pip ..", requirement)
                with TransactionalUpdate(requirement):
                    wheel_version = pip_wheel_module.wheel_version(requirement.source_directory)
                    pip_wheel_module.check_compatibility(wheel_version, requirement.name)
                    requirement.pip_requirement.move_wheel_files(requirement.source_directory)
            else:
                logger.info("Installing %s binary distribution using pip-accel ..", requirement)
                with TransactionalUpdate(requirement):
                    binary_distribution = self.bdists.get_binary_dist(requirement)
                    self.bdists.install_binary_dist(binary_distribution, **kw)
            num_installed += 1
        logger.info("Finished installing %s in %s.",
                    pluralize(num_installed, "requirement"),
                    install_timer)
        return num_installed

    def arguments_allow_wheels(self, arguments):
        """
        Check whether the given command line arguments allow the use of wheels.

        :param arguments: A list of strings with command line arguments.
        :returns: :data:`True` if the arguments allow wheels, :data:`False` if
                  they disallow wheels.

        Contrary to what the name of this method implies its implementation
        actually checks if the user hasn't *disallowed* the use of wheels using
        the ``--no-use-wheel`` option (deprecated in pip 7.x) or the
        ``--no-binary=:all:`` option (introduced in pip 7.x). This is because
        wheels are "opt out" in recent versions of pip. I just didn't like the
        method name ``arguments_dont_disallow_wheels`` ;-).
        """
        return not ('--no-use-wheel' in arguments or match_option_with_value(arguments, '--no-binary', ':all:'))

    def create_build_directory(self):
        """Create a new build directory for pip to unpack its archives."""
        self.build_directories.append(tempfile.mkdtemp(prefix='pip-accel-build-dir-'))

    def clear_build_directory(self):
        """Clear the build directory where pip unpacks the source distribution archives."""
        stat = os.stat(self.build_directory)
        shutil.rmtree(self.build_directory)
        os.makedirs(self.build_directory, stat.st_mode)

    def cleanup_temporary_directories(self):
        """Delete the build directories and any temporary directories created by pip."""
        while self.build_directories:
            shutil.rmtree(self.build_directories.pop())
        for requirement in self.reported_requirements:
            requirement.remove_temporary_source()
        while self.eggs_links:
            symbolic_link = self.eggs_links.pop()
            if os.path.islink(symbolic_link):
                os.unlink(symbolic_link)

    @property
    def build_directory(self):
        """Get the pathname of the current build directory (a string)."""
        if not self.build_directories:
            self.create_build_directory()
        return self.build_directories[-1]


class DownloadLogFilter(logging.Filter):

    """
    Rewrite log messages emitted by pip's ``pip.download`` module.

    When pip encounters hash mismatches it logs a message with the severity
    :data:`~logging.CRITICAL`, however because of the interaction between
    pip-accel and pip hash mismatches are to be expected and handled gracefully
    (refer to :func:`~PipAccelerator.decorate_arguments()` for details). The
    :class:`DownloadLogFilter` context manager changes the severity of these
    log messages to :data:`~logging.DEBUG` in order to avoid confusing users of
    pip-accel.
    """

    KEYWORDS = ("doesn't", "match", "expected", "hash")

    def __enter__(self):
        """Enable the download log filter."""
        self.logger = logging.getLogger('pip.download')
        self.logger.addFilter(self)

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Disable the download log filter."""
        self.logger.removeFilter(self)

    def filter(self, record):
        """Change the severity of selected log records."""
        if isinstance(record.msg, basestring):
            message = record.msg.lower()
            if all(kw in message for kw in self.KEYWORDS):
                record.levelname = 'DEBUG'
                record.levelno = logging.DEBUG
        return 1


class SetupRequiresPatch(object):

    """
    Monkey patch to enable caching of setup requirements.

    This context manager monkey patches ``InstallRequirement.run_egg_info()``
    to enable caching of setup requirements. It works by creating a symbolic
    link called ``.eggs`` in the source directory of unpacked Python source
    distributions which points to a shared directory inside the pip-accel
    data directory. This can only work on platforms that support
    :func:`os.symlink()`` but should fail gracefully elsewhere.

    The :class:`SetupRequiresPatch` context manager doesn't clean up the
    symbolic links because doing so would remove the link when it is still
    being used. Instead the context manager builds up a list of created links
    so that pip-accel can clean these up when it is known that the symbolic
    links are no longer needed.

    For more information about this hack please refer to `issue 49
    <https://github.com/paylogic/pip-accel/issues/49>`_.
    """

    def __init__(self, config, created_links=None):
        """
        Initialize a :class:`SetupRequiresPatch` object.

        :param config: A :class:`~pip_accel.config.Config` object.
        :param created_links: A list where newly created symbolic links are
                              added to (so they can be cleaned up later).
        """
        self.config = config
        self.patch = None
        self.created_links = created_links

    def __enter__(self):
        """Enable caching of setup requirements (by patching the ``run_egg_info()`` method)."""
        if self.patch is None:
            created_links = self.created_links
            original_method = InstallRequirement.run_egg_info
            shared_directory = self.config.eggs_cache

            def run_egg_info_wrapper(self, *args, **kw):
                # Heads up: self is an `InstallRequirement' object here!
                link_name = os.path.join(self.source_dir, '.eggs')
                try:
                    logger.debug("Creating symbolic link: %s -> %s", link_name, shared_directory)
                    os.symlink(shared_directory, link_name)
                    if created_links is not None:
                        created_links.append(link_name)
                except Exception as e:
                    # Always log the failure, but only include a traceback if
                    # it looks like symbolic links should be supported on the
                    # current platform (os.symlink() is available).
                    logger.debug("Failed to create symbolic link! (continuing without)",
                                 exc_info=not isinstance(e, AttributeError))
                # Execute the real run_egg_info() method.
                return original_method(self, *args, **kw)

            # Install the wrapper method for the duration of the context manager.
            self.patch = PatchedAttribute(InstallRequirement, 'run_egg_info', run_egg_info_wrapper)
            self.patch.__enter__()

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Undo the changes that enable caching of setup requirements."""
        if self.patch is not None:
            self.patch.__exit__(exc_type, exc_value, traceback)
            self.patch = None


class CustomPackageFinder(pip_index_module.PackageFinder):

    """
    Custom :class:`pip.index.PackageFinder` to keep pip off the internet.

    This class customizes :class:`pip.index.PackageFinder` to enforce what
    the ``--no-index`` option does for the default package index but doesn't do
    for package indexes registered with the ``--index=`` option in requirements
    files. Judging by pip's documentation the fact that this has to be monkey
    patched seems like a bug / oversight in pip (IMHO).
    """

    @property
    def index_urls(self):
        """Dummy list of index URLs that is always empty."""
        return []

    @index_urls.setter
    def index_urls(self, value):
        """Dummy setter for index URLs that ignores the value set."""
        pass

    @property
    def dependency_links(self):
        """Dummy list of dependency links that is always empty."""
        return []

    @dependency_links.setter
    def dependency_links(self, value):
        """Dummy setter for dependency links that ignores the value set."""
        pass


class PatchedAttribute(object):

    """
    Context manager to temporarily patch an object attribute.

    This context manager changes the value of an object attribute when the
    context is entered and restores the original value when the context is
    exited.
    """

    def __init__(self, object, attribute, value, enabled=True):
        """
        Initialize a :class:`PatchedAttribute` object.

        :param object: The object whose attribute should be patched.
        :param attribute: The name of the attribute to be patched (a string).
        :param value: The temporary value for the attribute.
        :param enabled: :data:`True` to patch the attribute, :data:`False` to
                        do nothing instead. This enables conditional attribute
                        patching while unconditionally using the
                        :keyword:`with` statement.
        """
        self.object = object
        self.attribute = attribute
        self.patched_value = value
        self.original_value = None
        self.enabled = enabled

    def __enter__(self):
        """Change the object attribute when entering the context."""
        if self.enabled:
            self.original_value = getattr(self.object, self.attribute)
            setattr(self.object, self.attribute, self.patched_value)

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Restore the object attribute when leaving the context."""
        if self.enabled:
            setattr(self.object, self.attribute, self.original_value)


class AttributeOverrides(object):

    """
    :class:`AttributeOverrides` enables overriding of object attributes.

    During the pip 6.x upgrade pip-accel switched to using ``pip install
    --download`` which unintentionally broke backwards compatibility with
    previous versions of pip-accel as documented in `issue 52`_.

    The reason for this is that when pip is given the ``--download`` option it
    internally enables ``--ignore-installed`` (which can be problematic for
    certain use cases as described in `issue 52`_). There is no documented way
    to avoid this behavior, so instead pip-accel resorts to monkey patching to
    restore backwards compatibility.

    :class:`AttributeOverrides` is used to replace pip's parsed command line
    options object with an object that defers all attribute access (gets and
    sets) to the original options object but always reports
    ``ignore_installed`` as :data:`False`, even after it was set to :data:`True` by pip
    (as described above).

    .. _issue 52: https://github.com/paylogic/pip-accel/issues/52
    """

    def __init__(self, opts, **overrides):
        """
        Construct an :class:`AttributeOverrides` instance.

        :param opts: The object to which attribute access is deferred.
        :param overrides: The attributes whose value should be overridden.
        """
        object.__setattr__(self, 'opts', opts)
        object.__setattr__(self, 'overrides', overrides)

    def __getattr__(self, name):
        """
        Get an attribute's value from overrides or by deferring attribute access.

        :param name: The name of the attribute (a string).
        :returns: The attribute's value.
        """
        if name in self.overrides:
            logger.debug("AttributeOverrides() getting %s from overrides ..", name)
            return self.overrides[name]
        else:
            logger.debug("AttributeOverrides() getting %s by deferring attribute access ..", name)
            return getattr(self.opts, name)

    def __setattr__(self, name, value):
        """
        Set an attribute's value (unless it has an override).

        :param name: The name of the attribute (a string).
        :param value: The new value for the attribute.
        """
        if name in self.overrides:
            logger.debug("AttributeOverrides() refusing to set %s=%r (attribute has override) ..", name, value)
        else:
            logger.debug("AttributeOverrides() setting %s=%r by deferring attribute access ..", name, value)
            setattr(self.opts, name, value)
