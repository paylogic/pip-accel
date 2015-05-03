# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: May 3, 2015
# URL: https://github.com/paylogic/pip-accel
#
# TODO Permanently store logs in the pip-accel directory (think about log rotation).
# TODO Maybe we should save the output of `python setup.py bdist_dumb` somewhere as well?

"""
:py:mod:`pip_accel` - Top level functionality
=============================================

The Python module :py:mod:`pip_accel` defines the classes that implement the
top level functionality of the pip accelerator. Instead of using the
``pip-accel`` command you can also use the pip accelerator as a Python module,
in this case you'll probably want to start by taking a look at
the :py:class:`PipAccelerator` class.

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

# Semi-standard module versioning.
__version__ = '0.29'

# Standard library modules.
import logging
import os
import os.path
import shutil
import sys
import tempfile

# Modules included in our package.
from pip_accel.bdist import BinaryDistributionManager
from pip_accel.exceptions import EnvironmentMismatchError, NothingToDoError
from pip_accel.req import Requirement
from pip_accel.utils import is_installed, makedirs, run, uninstall

# External dependencies.
from humanfriendly import concatenate, Timer, pluralize
from pip import index as pip_index_module
from pip import wheel as pip_wheel_module
from pip._vendor import pkg_resources
from pip.commands import install as pip_install_module
from pip.commands.install import InstallCommand
from pip.exceptions import DistributionNotFound

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

class PipAccelerator(object):

    """
    Accelerator for pip, the Python package manager.

    The :py:class:`PipAccelerator` class brings together the top level logic of
    pip-accel. This top level logic was previously just a collection of
    functions but that became more unwieldy as the amount of internal state
    increased. The :py:class:`PipAccelerator` class is intended to make it
    (relatively) easy to build something on top of pip and pip-accel.
    """

    def __init__(self, config, validate=True):
        """
        Initialize the pip accelerator.

        :param config: The pip-accel configuration (a :py:class:`.Config`
                       object).
        :param validate: ``True`` to run :py:func:`validate_environment()`,
                         ``False`` otherwise.
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

    def validate_environment(self):
        """
        Make sure :py:data:`sys.prefix` matches ``$VIRTUAL_ENV`` (if defined).

        This may seem like a strange requirement to dictate but it avoids hairy
        issues like `documented here <https://github.com/paylogic/pip-accel/issues/5>`_.

        The most sneaky thing is that ``pip`` doesn't have this problem
        (de-facto) because ``virtualenv`` copies ``pip`` wherever it goes...
        (``pip-accel`` on the other hand has to be installed by the user).
        """
        environment = os.environ.get('VIRTUAL_ENV')
        if environment:
            try:
                # Because os.path.samefile() itself can raise exceptions, e.g.
                # when $VIRTUAL_ENV points to a non-existing directory, we use
                # an assertion to allow us to use a single code path :-)
                assert os.path.samefile(sys.prefix, environment)
            except Exception:
                raise EnvironmentMismatchError("""
                    You are trying to install packages in environment #1 which
                    is different from environment #2 where pip-accel is
                    installed! Please install pip-accel under environment #1 to
                    install packages there.

                    Environment #1: {environment} (defined by $VIRTUAL_ENV)

                    Environment #2: {prefix} (Python's installation prefix)
                """, environment=environment,
                     prefix=sys.prefix)

    def initialize_directories(self):
        """Automatically create the local source distribution index directory."""
        makedirs(self.config.source_index)

    def clean_source_index(self):
        """
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
          :py:func:`clean_source_index()` cleaned up broken symbolic links
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

        This function is a simple wrapper for :py:func:`get_requirements()`,
        :py:func:`install_requirements()` and :py:func:`cleanup_temporary_directories()`
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
                   :py:func:`install_requirements()`.
        :returns: The result of :py:func:`install_requirements()`.
        """
        try:
            use_wheels = ('--no-use-wheel' not in arguments)
            requirements = self.get_requirements(arguments, use_wheels=use_wheels)
            have_wheels = any(req.is_wheel for req in requirements)
            if have_wheels and not self.setuptools_supports_wheels():
                logger.info("Preparing to upgrade to setuptools >= 0.8 to enable wheel support ..")
                requirements.extend(self.get_requirements(['setuptools >= 0.8']))
            if requirements:
                return self.install_requirements(requirements, **kw)
            else:
                logger.info("Nothing to do! (requirements already installed)")
                return 0
        finally:
            self.cleanup_temporary_directories()

    def setuptools_supports_wheels(self):
        """
        Check whether setuptools should be upgraded to ``>= 0.8`` for wheel support.

        :returns: ``True`` when setuptools needs to be upgraded, ``False`` otherwise.
        """
        # Don't use pkg_resources.Requirement.parse, to avoid the override
        # in distribute, that converts `setuptools' to `distribute'.
        setuptools_requirement = next(pkg_resources.parse_requirements('setuptools >= 0.8'))
        try:
            installed_setuptools = pkg_resources.get_distribution('setuptools')
            if installed_setuptools in setuptools_requirement:
                # setuptools >= 0.8 is already installed; nothing to do.
                return True
        except pkg_resources.DistributionNotFound:
            pass
        # We need to install setuptools >= 0.8.
        return False

    def get_requirements(self, arguments, max_retries=None, use_wheels=False):
        """
        Use pip to download and unpack the requested source distribution archives.

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :param max_retries: The maximum number of times that pip will be asked
                            to download distribution archives (this helps to
                            deal with intermittent failures). If this is
                            ``None`` then :py:attr:`~.Config.max_retries` is
                            used.
        :param use_wheels: Whether pip and pip-accel are allowed to use wheels_
                           (``False`` by default for backwards compatibility
                           with callers that use pip-accel as a Python API).

        .. warning:: Requirements which are already installed are not included
                     in the result. If this breaks your use case consider using
                     pip's ``--ignore-installed`` option.
        """
        # Use a new build directory for each run of get_requirements().
        self.create_build_directory()
        # If all requirements can be satisfied using the archives in
        # pip-accel's local source index we don't need pip to connect
        # to PyPI looking for new versions (that will slow us down).
        try:
            return self.unpack_source_dists(arguments, use_wheels=use_wheels)
        except DistributionNotFound:
            logger.info("We don't have all distribution archives yet!")
        # Get the maximum number of retries from the configuration if the
        # caller didn't specify a preference.
        if max_retries is None:
            max_retries = self.config.max_retries
        # If not all requirements are available locally we use pip to download
        # the missing source distribution archives from PyPI (we retry a couple
        # of times in case pip reports recoverable errors).
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

    def unpack_source_dists(self, arguments, use_wheels=False):
        """
        Check whether there are local source distributions available for all
        requirements, unpack the source distribution archives and find the
        names and versions of the requirements. By using the ``pip install
        --download`` command we avoid reimplementing the following pip
        features:

        - Parsing of ``requirements.txt`` (including recursive parsing)
        - Resolution of possibly conflicting pinned requirements
        - Unpacking source distributions in multiple formats
        - Finding the name & version of a given source distribution

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :param use_wheels: Whether pip and pip-accel are allowed to use wheels_
                           (``False`` by default for backwards compatibility
                           with callers that use pip-accel as a Python API).
        :returns: A list of :py:class:`pip_accel.req.Requirement` objects.
        :raises: Any exceptions raised by pip, for example
                 :py:exc:`pip.exceptions.DistributionNotFound` when not all
                 requirements can be satisfied.
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
                           (``False`` by default for backwards compatibility
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

        :param arguments: The command line arguments to ``pip install ..`` (a
                          list of strings).
        :param use_remote_index: A boolean indicating whether pip is allowed to
                                 connect to the main package index
                                 (http://pypi.python.org by default).
        :param use_wheels: Whether pip and pip-accel are allowed to use wheels_
                           (``False`` by default for backwards compatibility
                           with callers that use pip-accel as a Python API).
        :returns: A :py:class:`pip.req.RequirementSet` object created by pip.
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
        command_line.append('--find-links=file://%s' % self.config.source_index)
        # Use `--no-use-wheel' to ignore wheel distributions by default in
        # order to preserve backwards compatibility with callers that expect a
        # requirement set consisting only of source distributions that can be
        # converted to `dumb binary distributions'.
        if not use_wheels and '--no-use-wheel' not in arguments:
            command_line.append('--no-use-wheel')
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
        Convert the :py:class:`pip.req.RequirementSet` object reported by pip
        into a list of :py:class:`pip_accel.req.Requirement` objects.

        :param requirement_set: The :py:class:`pip.req.RequirementSet` object
                                reported by pip.
        :returns: A list of :py:class:`pip_accel.req.Requirement` objects.
        """
        filtered_requirements = []
        for requirement in requirement_set.requirements.values():
            # The `satisfied_by' property is set by pip when a requirement is
            # already satisfied (i.e. a version of the package that satisfies
            # the requirement is already installed) and -I, --ignore-installed
            # is not used. We filter out these requirements because pip never
            # unpacks distributions for these requirements, so pip-accel can't
            # do anything useful with such requirements.
            if not requirement.satisfied_by:
                filtered_requirements.append(requirement)
                self.reported_requirements.append(requirement)
        return sorted([Requirement(self.config, r) for r in filtered_requirements],
                      key=lambda r: r.name.lower())

    def install_requirements(self, requirements, **kw):
        """
        Manually install a requirement set from binary and/or wheel distributions.

        :param requirements: A list of :py:class:`pip_accel.req.Requirement` objects.
        :param kw: Any keyword arguments are passed on to
                   :py:func:`~pip_accel.bdist.BinaryDistributionManager.install_binary_dist()`.
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
            # If we're upgrading over an older version, first remove the
            # old version to make sure we don't leave files from old
            # versions around.
            if is_installed(requirement.name):
                uninstall(requirement.name)
            # When installing setuptools we need to uninstall distribute,
            # otherwise distribute will shadow setuptools and all sorts of
            # strange issues can occur (e.g. upgrading to the latest
            # setuptools to gain wheel support and then having everything
            # blow up because distribute doesn't know about wheels).
            if requirement.name == 'setuptools' and is_installed('distribute'):
                uninstall('distribute')
            if requirement.is_editable:
                logger.debug("Installing %s in editable form using pip.", requirement)
                if not run('{pip} install --no-deps --editable {url} >/dev/null 2>&1',
                           pip=self.pip_executable,
                           url=requirement.url):
                    msg = "Failed to install %s in editable form!"
                    raise Exception(msg % requirement)
            elif requirement.is_wheel:
                logger.info("Installing %s wheel distribution using pip ..", requirement)
                wheel_version = pip_wheel_module.wheel_version(requirement.source_directory)
                pip_wheel_module.check_compatibility(wheel_version, requirement.name)
                requirement.pip_requirement.move_wheel_files(requirement.source_directory)
            else:
                binary_distribution = self.bdists.get_binary_dist(requirement)
                self.bdists.install_binary_dist(binary_distribution, **kw)
            num_installed += 1
        logger.info("Finished installing %s in %s.",
                    pluralize(num_installed, "requirement"),
                    install_timer)
        return num_installed

    def create_build_directory(self):
        """
        Create a new build directory for pip to unpack its archives.
        """
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

    @property
    def build_directory(self):
        """Get the pathname of the current build directory (a string)."""
        if not self.build_directories:
            self.create_build_directory()
        return self.build_directories[-1]

    @property
    def pip_executable(self):
        """Get the absolute pathname of the ``pip`` executable (a string)."""
        return os.path.join(sys.prefix, 'bin', 'pip')

class CustomPackageFinder(pip_index_module.PackageFinder):

    """
    This class customizes :py:class:`pip.index.PackageFinder` to enforce what
    the ``--no-index`` option does for the default package index but doesn't do
    for package indexes registered with the ``--index=`` option in requirements
    files. Judging by pip's documentation the fact that this has to be monkey
    patched seems like a bug / oversight in pip (IMHO).
    """

    @property
    def index_urls(self):
        return []

    @index_urls.setter
    def index_urls(self, value):
        pass

    @property
    def dependency_links(self):
        return []

    @dependency_links.setter
    def dependency_links(self, value):
        pass

class PatchedAttribute(object):

    """
    This context manager changes the value of an object attribute when the
    context is entered and restores the original value when the context is
    exited.
    """

    def __init__(self, object, attribute, value):
        self.object = object
        self.attribute = attribute
        self.patched_value = value
        self.original_value = None

    def __enter__(self):
        self.original_value = getattr(self.object, self.attribute)
        setattr(self.object, self.attribute, self.patched_value)

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        setattr(self.object, self.attribute, self.original_value)

class AttributeOverrides(object):

    """
    :py:class:`AttributeOverrides` enables overriding of object attributes.

    During the pip 6.x upgrade pip-accel switched to using ``pip install
    --download`` which unintentionally broke backwards compatibility with
    previous versions of pip-accel as documented in `issue 52`_.

    The reason for this is that when pip is given the ``--download`` option it
    internally enables ``--ignore-installed`` (which can be problematic for
    certain use cases as described in `issue 52`_). There is no documented way
    to avoid this behavior, so instead pip-accel resorts to monkey patching to
    restore backwards compatibility.

    :py:class:`AttributeOverrides` is used to replace pip's parsed command line
    options object with an object that defers all attribute access (gets and
    sets) to the original options object but always reports
    ``ignore_installed`` as ``False``, even after it was set to ``True`` by pip
    (as described above).

    .. _issue 52: https://github.com/paylogic/pip-accel/issues/52
    """

    def __init__(self, opts, **overrides):
        """
        Construct an :py:class:`AttributeOverrides` instance.

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
