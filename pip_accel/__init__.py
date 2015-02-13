# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: February 13, 2015
# URL: https://github.com/paylogic/pip-accel
#
# TODO Permanently store logs in the pip-accel directory (think about log rotation).
# TODO Maybe we should save the output of `python setup.py bdist_dumb` somewhere as well?

"""
:py:mod:`pip_accel` - Top level functions and command line interface
====================================================================

The Python module :py:mod:`pip_accel` defines the classes that implement the
top level functionality of the pip accelerator. Instead of using the
``pip-accel`` command you can also use the pip accelerator as a Python module,
in this case you'll probably want to start by taking a look at
the :py:class:`PipAccelerator` class.
"""

# Semi-standard module versioning.
__version__ = '0.22.4'

# Standard library modules.
import logging
import os
import os.path
import shutil
import sys
import tempfile

# Modules included in our package.
from pip_accel.bdist import BinaryDistributionManager
from pip_accel.compat import unquote, urlparse
from pip_accel.exceptions import EnvironmentMismatchError, NothingToDoError
from pip_accel.req import Requirement
from pip_accel.utils import add_archive_extension, makedirs, run

# External dependencies.
from humanfriendly import Timer, pluralize
from pip import index as pip_index_module
from pip import parseopts
from pip.cmdoptions import requirements as requirements_option
from pip.commands import install as pip_install_module
from pip.commands.install import InstallCommand
from pip.exceptions import DistributionNotFound
from pip.log import logger as pip_logger
from pip.status_codes import SUCCESS

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
        self.update_source_index()
        # Create a temporary directory for pip to unpack its archives.
        self.build_directory = tempfile.mkdtemp()
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
        """Automatically create the directories for the download cache and the source index."""
        for directory in [self.config.download_cache, self.config.source_index]:
            makedirs(directory)

    def clean_source_index(self):
        """
        When files are removed from pip's download cache, broken symbolic links
        remain in pip-accel's source index directory. This results in very
        confusing error messages. To avoid this we cleanup broken symbolic
        links before every run.
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

    def update_source_index(self):
        """
        Link newly downloaded source distributions found in pip's download
        cache directory into pip-accel's local source index directory using
        symbolic links.
        """
        update_timer = Timer()
        update_counter = 0
        for download_name in os.listdir(self.config.download_cache):
            download_path = os.path.join(self.config.download_cache, download_name)
            if os.path.isfile(download_path):
                url = unquote(download_name)
                if not url.endswith('.content-type'):
                    components = urlparse(url)
                    original_name = os.path.basename(components.path)
                    modified_name = add_archive_extension(download_path, original_name)
                    archive_path = os.path.join(self.config.source_index, modified_name)
                    if not os.path.isfile(archive_path):
                        logger.debug("Linking files:")
                        logger.debug(" - Source: %s", download_path)
                        logger.debug(" - Target: %s", archive_path)
                        os.symlink(download_path, archive_path)
        logger.debug("Added %i symbolic links to source index in %s.", update_counter, update_timer)

    def install_from_arguments(self, arguments, **kw):
        """
        Download, unpack, build and install the specified requirements.

        This function is a simple wrapper for :py:func:`get_requirements()`,
        :py:func:`install_requirements()` and :py:func:`cleanup_temporary_directories()`
        that implements the default behavior of the pip accelerator. If you're
        extending or embedding pip-accel you may want to call the underlying
        methods instead.

        :param arguments: The command line arguments to ``pip install ..`` (a
                          list of strings).
        :param kw: Any keyword arguments are passed on to
                   :py:func:`install_requirements()`.
        """
        requirements = self.get_requirements(arguments)
        self.install_requirements(requirements, **kw)
        self.cleanup_temporary_directories()

    def get_requirements(self, arguments, max_retries=10):
        """
        Use pip to download and unpack the requested source distribution archives.

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :param max_retries: The maximum number of times that pip will be asked
                            to download source distribution archives (this
                            helps to deal with intermittent failures).
        """
        # If all requirements can be satisfied using the archives in
        # pip-accel's local source index we don't need pip to connect
        # to PyPI looking for new versions (that will slow us down).
        try:
            return self.unpack_source_dists(arguments)
        except DistributionNotFound:
            logger.info("We don't have all source distribution archives yet!")
        # If not all requirements are available locally we use pip to download
        # the missing source distribution archives from PyPI (we retry a couple
        # of times in case pip reports recoverable errors).
        for i in range(max_retries):
            try:
                return self.download_source_dists(arguments)
            except Exception as e:
                if i + 1 < max_retries:
                    # On all but the last iteration we swallow exceptions
                    # during downloading.
                    logger.warning("pip raised exception while downloading source distributions: %s", e)
                else:
                    # On the last iteration we don't swallow exceptions
                    # during downloading because the error reported by pip
                    # is the most sensible error for us to report.
                    raise
            logger.info("Retrying after pip failed (%i/%i) ..", i + 1, max_retries)

    def unpack_source_dists(self, arguments):
        """
        Check whether there are local source distributions available for all
        requirements, unpack the source distribution archives and find the
        names and versions of the requirements. By using the ``pip install
        --no-install`` command we avoid reimplementing the following pip
        features:

        - Parsing of ``requirements.txt`` (including recursive parsing)
        - Resolution of possibly conflicting pinned requirements
        - Unpacking source distributions in multiple formats
        - Finding the name & version of a given source distribution

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :returns: A list of :py:class:`pip_accel.req.Requirement` objects.
        :raises: Any exceptions raised by pip, for example
                 :py:exc:`pip.exceptions.DistributionNotFound` when not all
                 requirements can be satisfied.
        """
        unpack_timer = Timer()
        logger.info("Unpacking source distribution(s) ..")
        # Install our custom package finder to force --no-index behavior.
        original_package_finder = pip_index_module.PackageFinder
        pip_install_module.PackageFinder = CustomPackageFinder
        try:
            requirements = self.get_pip_requirement_set(arguments, use_remote_index=False)
            logger.info("Finished unpacking %s in %s.",
                        pluralize(len(requirements), "source distribution"),
                        unpack_timer)
            return requirements
        finally:
            # Make sure to remove our custom package finder.
            pip_install_module.PackageFinder = original_package_finder

    def download_source_dists(self, arguments):
        """
        Download missing source distributions.

        :param arguments: The command line arguments to ``pip install ...`` (a
                          list of strings).
        :raises: Any exceptions raised by pip.
        """
        try:
            download_timer = Timer()
            logger.info("Downloading missing source distribution(s) ..")
            requirements = self.get_pip_requirement_set(arguments, use_remote_index=True)
            logger.info("Finished downloading source distribution(s) in %s.", download_timer)
            return requirements
        finally:
            # Always update the local source index directory (even if pip
            # reported errors) because we never want to download an archive
            # more than once.
            self.update_source_index()

    def get_pip_requirement_set(self, arguments, use_remote_index):
        """
        Get the unpacked requirement(s) specified by the caller by running pip.

        :param arguments: The command line arguments to ``pip install ..`` (a
                          list of strings).
        :param use_remote_index: A boolean indicating whether pip is allowed to
                                 connect to the main package index
                                 (http://pypi.python.org by default).
        :returns: A :py:class:`pip.req.RequirementSet` object created by pip.
        :raises: Any exceptions raised by pip.
        """
        # Compose the pip command line arguments.
        command_line = ['pip', 'install', '--no-install']
        if use_remote_index:
            command_line.append('--download-cache=%s' % self.config.download_cache)
        else:
            command_line.append('--no-index')
        command_line.extend([
            '--find-links=file://%s' % self.config.source_index,
            '--build-directory=%s' % self.build_directory,
        ])
        command_line.extend(arguments)
        logger.info("Executing command: %s", ' '.join(command_line))
        # Clear the build directory to prevent PreviousBuildDirError exceptions.
        self.clear_build_directory()
        # pip 1.4 has some global state in its command line parser (which we
        # use) and this can causes problems when we invoke more than one
        # InstallCommand in the same process. Here's a workaround.
        requirements_option.default = []
        # Parse the command line arguments so we can pass the resulting parser
        # object to InstallCommand.
        cmd_name, options, args, parser = parseopts(command_line[1:])
        # Initialize our custom InstallCommand.
        pip = CustomInstallCommand(parser)
        # Run the `pip install ...' command.
        exit_status = pip.main(args[1:], options)
        # Make sure the output of pip and pip-accel are not intermingled.
        sys.stdout.flush()
        # If our custom install command intercepted an exception we re-raise it
        # after the local source index has been updated.
        if exit_status != SUCCESS:
            raise pip.intercepted_exception
        elif pip.requirement_set is None:
            raise NothingToDoError("""
                pip didn't generate a requirement set, most likely you
                specified an empty requirements file?
            """)
        else:
            return self.transform_pip_requirement_set(pip.requirement_set)

    def transform_pip_requirement_set(self, requirement_set):
        """
        Convert the :py:class:`pip.req.RequirementSet` object reported by pip
        into a list of :py:class:`pip_accel.req.Requirement` objects.

        .. warning:: Requirements which are already installed are not included
                     in the result because pip never creates unpacked source
                     distribution directories for these requirements. If this
                     breaks your use case consider looking into pip's
                     ``--ignore-installed`` option or file a bug report against
                     pip-accel to force me to find a better way.

        :param requirement_set: The :py:class:`pip.req.RequirementSet` object
                                reported by pip.
        :returns: A list of :py:class:`pip_accel.req.Requirement` objects.
        """
        filtered_requirements = []
        for requirement in requirement_set.requirements.values():
            if requirement.satisfied_by:
                logger.info("Requirement already satisfied: %s.", requirement)
            else:
                filtered_requirements.append(requirement)
                self.reported_requirements.append(requirement)
        return sorted([Requirement(r) for r in filtered_requirements],
                      key=lambda r: r.name.lower())

    def install_requirements(self, requirements, **kw):
        """
        Manually install all requirements from binary distributions.

        :param requirements: A list of :py:class:`pip_accel.req.Requirement` objects.
        :param kw: Any keyword arguments are passed on to
                   :py:func:`~pip_accel.bdist.BinaryDistributionManager.install_binary_dist()`.
        """
        install_timer = Timer()
        logger.info("Installing from binary distributions ..")
        pip = os.path.join(sys.prefix, 'bin', 'pip')
        for requirement in requirements:
            if run('{pip} uninstall --yes {package} >/dev/null 2>&1', pip=pip, package=requirement.name):
                logger.info("Uninstalled previously installed package %s.", requirement.name)
            if requirement.is_editable:
                logger.debug("Installing %s (%s) in editable form using pip.", requirement.name, requirement.version)
                if not run('{pip} install --no-deps --editable {url} >/dev/null 2>&1', pip=pip, url=requirement.url):
                    msg = "Failed to install %s (%s) in editable form!"
                    raise Exception(msg % (requirement.name, requirement.version))
            else:
                binary_distribution = self.bdists.get_binary_dist(requirement)
                self.bdists.install_binary_dist(binary_distribution, **kw)
        logger.info("Finished installing %s in %s.",
                    pluralize(len(requirements), "requirement"),
                    install_timer)

    def clear_build_directory(self):
        """Clear the build directory where pip unpacks the source distribution archives."""
        stat = os.stat(self.build_directory)
        shutil.rmtree(self.build_directory)
        os.makedirs(self.build_directory, stat.st_mode)

    def cleanup_temporary_directories(self):
        """Delete the build directory and any temporary directories created by pip."""
        shutil.rmtree(self.build_directory)
        for requirement in self.reported_requirements:
            requirement.remove_temporary_source()

class CustomInstallCommand(InstallCommand):

    """
    Subclass of :py:class:`pip.commands.install.InstallCommand` that makes it
    easier to run ``pip install`` commands from Python code. Used by
    :py:func:`~PipAccelerator.get_pip_requirement_set()`.
    """

    def main(self, *args, **kw):
        """
        :py:func:`pip.basecommand.Command.main()` expects to be executed only
        once because it unconditionally executes :py:func:`pip.log.logger.consumers.extend()`.
        This means that when we run pip more than once we'll cause it to repeat
        its output as many times as we executed a ``pip install`` command. We
        wrap :py:func:`pip.basecommand.Command.main()` to explicitly reset the
        list of consumers.
        """
        pip_logger.consumers = []
        return super(CustomInstallCommand, self).main(*args, **kw)

    def run(self, *args, **kw):
        """
        The method :py:func:`pip.commands.install.InstallCommand.run()` returns
        a :py:class:`pip.req.RequirementSet` object which pip-accel is
        interested in, however :py:func:`pip.basecommand.Command.main()` (the
        caller of ``run()``) swallows the requirement set (based on my reading
        of the pip 1.4.x source code). We wrap ``run()`` so that we can
        intercept the requirement set. This is a bit sneaky, but I don't fancy
        reimplementing large parts of :py:func:`pip.basecommand.Command.main()`
        inside of pip-accel!
        """
        original_method = super(CustomInstallCommand, self).run
        try:
            self.intercepted_exception = None
            self.requirement_set = original_method(*args, **kw)
            return self.requirement_set
        except (Exception, KeyboardInterrupt) as e:
            self.intercepted_exception = e
            raise

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
