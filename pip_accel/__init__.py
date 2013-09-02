# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: September 2, 2013
# URL: https://github.com/paylogic/pip-accel
#
# TODO Permanently store logs in the pip-accel directory (think about log rotation).
# TODO Maybe we should save the output of `python setup.py bdist_dumb` somewhere as well?

"""
The Python module :py:mod:`pip_accel` defines the classes and functions that
implement the functionality of the pip accelerator and the ``pip-accel``
command. Instead of using the ``pip-accel`` command you can also use the pip
accelerator as a Python module. In this case you'll probably want to start by
taking a look at the following functions:

- :py:func:`unpack_source_dists`
- :py:func:`download_source_dists`
- :py:func:`install_requirements`
"""

# Semi-standard module versioning.
__version__ = '0.10.2'

# Standard library modules.
import os
import os.path
import pipes
import pkg_resources
import shutil
import sys
import tempfile
import textwrap
import urllib
import urlparse

# Modules included in our package.
from pip_accel.bdist import get_binary_dist, install_binary_dist
from pip_accel.config import (binary_index, download_cache,
                              index_version_file, source_index)
from pip_accel.logger import logger

# External dependencies.
import coloredlogs
from humanfriendly import Timer
from pip import parseopts
from pip.backwardcompat import string_types
from pip.cmdoptions import requirements as requirements_option
from pip.commands.install import InstallCommand
from pip.exceptions import DistributionNotFound, InstallationError
from pip.log import logger as pip_logger
from pip.status_codes import SUCCESS

# Find the environment where requirements are to be installed.
ENVIRONMENT = os.path.abspath(os.environ.get('VIRTUAL_ENV', sys.prefix))

# The main loop of pip-accel retries at most this many times to counter pip errors
# due to connectivity issues with PyPI and/or linked distribution websites.
MAX_RETRIES = 10

# The version number of the binary distribution cache format in use. When we
# break backwards compatibility we bump this number so that pip-accel knows it
# should clear the cache before proceeding.
CACHE_FORMAT_REVISION = 4

def main():
    """
    Main logic of the ``pip-accel`` command.
    """
    arguments = sys.argv[1:]
    # If no arguments are given, the help text of pip-accel is printed.
    if not arguments:
        print_usage()
        sys.exit(0)
    # If no install subcommand is given we pass the command line straight
    # to pip without any changes and exit immediately afterwards.
    elif 'install' not in arguments:
        sys.exit(os.spawnvp(os.P_WAIT, 'pip', ['pip'] + arguments))
    # Initialize logging output.
    coloredlogs.install()
    # Increase verbosity based on -v, --verbose options.
    for argument in arguments:
        if argument == '--verbose' or (len(argument) >= 2 and argument[0] ==
                '-' and argument[1] != '-' and 'v' in argument):
            coloredlogs.increase_verbosity()
    # Make sure the prefix is the same as the environment.
    if not os.path.samefile(sys.prefix, ENVIRONMENT):
        logger.error("You are trying to install packages in environment #1 which is different from environment #2 where pip-accel is installed! Please install pip-accel under environment #1 to install packages there.")
        logger.info("Environment #1: %s ($VIRTUAL_ENV)", ENVIRONMENT)
        logger.info("Environment #2: %s (installation prefix)", sys.prefix)
        sys.exit(1)
    main_timer = Timer()
    initialize_directories()
    build_directory = tempfile.mkdtemp()
    # Execute "pip install" in a loop in order to retry after intermittent
    # error responses from servers (which can happen quite frequently).
    try:
        for i in xrange(1, MAX_RETRIES):
            try:
                requirements = unpack_source_dists(arguments, build_directory)
            except DistributionNotFound:
                logger.warn("We don't have all source distributions yet!")
                download_source_dists(arguments, build_directory)
            else:
                if not requirements:
                    logger.info("No unsatisfied requirements found, probably there's nothing to do.")
                else:
                    install_requirements(requirements)
                    logger.info("Done! Took %s to install %i package%s.", main_timer, len(requirements), '' if len(requirements) == 1 else 's')
                return
            logger.warn("pip failed, retrying (%i/%i) ..", i + 1, MAX_RETRIES)
    except InstallationError:
        # Abort early when pip reports installation errors.
        logger.fatal("pip reported unrecoverable installation errors. Please fix and rerun!")
        sys.exit(1)
    finally:
        # Always cleanup temporary build directory.
        shutil.rmtree(build_directory)
    # Abort when after N retries we still failed to download source distributions.
    logger.fatal("External command failed %i times, aborting!" % MAX_RETRIES)
    sys.exit(1)

def print_usage():
    """
    Report the usage of the pip-accel command to the console.
    """
    print textwrap.dedent("""
        Usage: pip-accel [ARGUMENTS TO PIP]

        The pip-accel program is a wrapper for pip, the Python package manager. It
        accelerates the usage of pip to initialize Python virtual environments given
        one or more requirements files. The pip-accel command supports all subcommands
        and options supported by pip, however it is only useful for the "pip install"
        subcommand.

        For more information please refer to the GitHub project page
        at https://github.com/paylogic/pip-accel
    """).strip()

def clear_build_directory(directory):
    """
    Since pip 1.4 there is a new exception that's raised by pip:
    ``PreviousBuildDirError``. Unfortunately pip-accel apparently triggers the
    worst possible side effect of this new "feature" and the only way to avoid
    it is to start with an empty build directory in every step of pip-accel's
    process (possibly very inefficient).

    :param directory: The build directory to clear.
    """
    logger.debug("Clearing build directory ..")
    if os.path.isdir(directory):
        shutil.rmtree(directory)
    os.makedirs(directory)

def unpack_source_dists(arguments, build_directory):
    """
    Check whether there are local source distributions available for all
    requirements, unpack the source distribution archives and find the names
    and versions of the requirements. By using the ``pip install --no-install``
    command we avoid reimplementing the following pip features:

    - Parsing of ``requirements.txt`` (including recursive parsing)
    - Resolution of possibly conflicting pinned requirements
    - Unpacking source distributions in multiple formats
    - Finding the name & version of a given source distribution

    :param arguments: A list of strings with the command line arguments to be
                      passed to the ``pip`` command.

    :returns: A list of tuples with three strings each: The name of a
              requirement (package), its version number and the directory where
              the unpacked source distribution is located. If ``pip`` fails, an
              exception will be raised by ``pip``.
    """
    unpack_timer = Timer()
    logger.info("Unpacking local source distributions ..")
    clear_build_directory(build_directory)
    # Execute pip to unpack the source distributions.
    requirement_set = run_pip(arguments + ['--no-install'],
                              use_remote_index=False,
                              build_directory=build_directory)
    logger.info("Unpacked local source distributions in %s.", unpack_timer)
    requirements = []
    for install_requirement in sorted_requirements(requirement_set):
        if install_requirement.satisfied_by:
            logger.info("Requirement already satisfied: %s.", install_requirement)
        else:
            req = ensure_parsed_requirement(install_requirement)
            requirements.append((req.project_name,
                                 install_requirement.installed_version,
                                 install_requirement.source_dir))
    return requirements

def sorted_requirements(requirement_set):
    """
    Sort the requirements in a ``RequirementSet``.

    :param requirement_set: A ``RequirementSet`` object produced by ``pip``.
    :returns: A list of sorted ``InstallRequirement`` objects.
    """
    return sorted(requirement_set.requirements.values(),
                  key=lambda r: ensure_parsed_requirement(r).project_name.lower())

def ensure_parsed_requirement(install_requirement):
    """
    ``InstallRequirement`` objects in ``RequirementSet`` objects have a ``req``
    member, which apparently can be either a string or a
    ``pkg_resources.Requirement`` object. This function makes sure we're
    dealing with a ``pkg_resources.Requirement`` object.

    This was "copied" from the pip source code, I'm not sure if this code is
    actually necessary but it doesn't hurt and ``pip`` probably did it for a
    reason. Right? :-)

    :param install_requirement: An ``InstallRequirement`` object
                                produced by ``pip``.
    :returns: A ``pkg_resources.Requirement`` object.
    """
    req = install_requirement.req
    if isinstance(req, string_types):
        req = pkg_resources.Requirement.parse(req)
    return req

def download_source_dists(arguments, build_directory):
    """
    Download missing source distributions.

    :param arguments: A list with the arguments intended for ``pip``.
    """
    download_timer = Timer()
    logger.info("Downloading source distributions ..")
    clear_build_directory(build_directory)
    # Execute pip to download missing source distributions.
    try:
        run_pip(arguments + ['--no-install'], use_remote_index=True, build_directory=build_directory)
        logger.info("Finished downloading source distributions in %s.", download_timer)
    except Exception, e:
        logger.warn("pip raised an exception while downloading source distributions: %s.", e)

def install_requirements(requirements, install_prefix=ENVIRONMENT):
    """
    Manually install all requirements from binary distributions.

    :param requirements: A list of tuples in the format of the return value of
                         :py:func:`unpack_source_dists()`.
    :param install_prefix: The "prefix" under which the requirements should be
                           installed. This will be a pathname like ``/usr``,
                           ``/usr/local`` or the pathname of a virtual
                           environment.
    :returns: ``True`` if it succeeds in installing all requirements from
              binary distribution archives, ``False`` otherwise.
    """
    install_timer = Timer()
    logger.info("Installing from binary distributions ..")
    python = os.path.join(install_prefix, 'bin', 'python')
    pip = os.path.join(install_prefix, 'bin', 'pip')
    for name, version, directory in requirements:
        if os.system('%s uninstall --yes %s >/dev/null 2>&1' % (pipes.quote(pip), pipes.quote(name))) == 0:
            logger.info("Uninstalled previously installed package %s.", name)
        members = get_binary_dist(name, version, directory, prefix=install_prefix, python=python)
        install_binary_dist(members, prefix=install_prefix, python=python)
    logger.info("Finished installing all requirements in %s.", install_timer)
    return True

def run_pip(arguments, use_remote_index, build_directory=None):
    """
    Execute a modified ``pip install`` command. This function assumes that the
    arguments concern a ``pip install`` command (:py:func:`main()` makes sure
    of this).

    :param arguments: A list of strings containing the arguments that will be
                      passed to ``pip``.
    :param use_remote_index: A boolean indicating whether ``pip`` is allowed to
                             contact http://pypi.python.org.
    :returns: A ``RequirementSet`` object created by ``pip``, unless an
              exception is raised by ``pip`` (in which case the exception will
              bubble up).
    """
    command_line = []
    for i, arg in enumerate(arguments):
        if arg == 'install':
            command_line += ['pip'] + arguments[:i+1] + [
                    '--download-cache=%s' % download_cache,
                    '--find-links=file://%s' % source_index]
            if build_directory:
                command_line += ['--build-directory=%s' % build_directory]
            if not use_remote_index:
                command_line += ['--no-index']
            command_line += arguments[i+1:]
            break
    else:
        command_line = ['pip'] + arguments
    logger.info("Executing command: %s", ' '.join(command_line))
    # XXX Nasty hack required for pip 1.4 compatibility (workaround for global state).
    requirements_option.default = []
    cmd_name, options, args, parser = parseopts(command_line[1:])
    pip = CustomInstallCommand(parser)
    exit_status = pip.main(args[1:], options)
    # Make sure the output of pip and pip-accel are not intermingled.
    sys.stdout.flush()
    update_source_dists_index()
    if exit_status == SUCCESS:
        return pip.requirement_set
    else:
        raise pip.intercepted_exception

class CustomInstallCommand(InstallCommand):

    """
    Subclass of ``pip.commands.install.InstallCommand`` that makes it easier to
    run ``pip install`` from Python.
    """

    def main(self, *args, **kw):
        """
        ``pip.basecommand.Command.main()`` expects to be executed only once; it
        unconditionally executes ``pip.log.logger.consumers.extend()``. This
        means that when we run ``pip`` more than once we'll cause it to repeat
        its output as many times as we executed a ``pip install`` command. We
        wrap ``main()`` to explicitly reset the list of consumers.
        """
        pip_logger.consumers = []
        return super(CustomInstallCommand, self).main(*args, **kw)


    def run(self, *args, **kw):
        """
        The method ``pip.commands.install.InstallCommand.run()`` returns a
        ``RequirementSet`` object which ``pip-accel`` is interested in, however
        ``pip.basecommand.Command.main()`` (the caller of ``run()``) swallows
        the requirement set (based on my reading of the pip 1.3.x source code).
        We wrap ``run()`` so that we can intercept the requirement set. This is
        a bit sneaky, but I don't fancy reimplementing large parts of
        ``pip.basecommand.Command.main()`` inside ``pip-accel``!
        """
        original_method = super(CustomInstallCommand, self).run
        try:
            self.intercepted_exception = None
            self.requirement_set = original_method(*args, **kw)
            return self.requirement_set
        except Exception, e:
            self.intercepted_exception = e
            raise

def update_source_dists_index():
    """
    Link newly downloaded source distributions into the local index directory
    using symbolic links.
    """
    for download_name in os.listdir(download_cache):
        download_path = os.path.join(download_cache, download_name)
        url = urllib.unquote(download_name)
        if not url.endswith('.content-type'):
            components = urlparse.urlparse(url)
            archive_name = os.path.basename(components.path)
            archive_path = os.path.join(source_index, add_extension(download_path, archive_name))
            if not os.path.isfile(archive_path):
                logger.info("Linking files:")
                logger.info(" - Source: %s", download_path)
                logger.info(" - Target: %s", archive_path)
                os.symlink(download_path, archive_path)

def add_extension(download_path, archive_path):
    """
    Make sure all cached source distributions have the right file extension,
    because not all distribution sites provide URLs with proper filenames in
    them while we really need the proper filenames to build the local source
    index.

    :param download_path: The pathname of the source distribution archive in
                          the download cache.
    :param archive_path: The pathname of the distribution archive in the source
                         index directory.
    :returns: The (possibly modified) pathname of the distribution archive in
              the source index directory.

    Previously this used the ``file`` executable, now it checks the magic file
    headers itself. I could have used any of the numerous ``libmagic`` bindings
    on PyPI, but that would add a binary dependency to ``pip-accel`` and I
    don't want that :-).
    """
    handle = open(download_path)
    header = handle.read(2)
    handle.close()
    if header.startswith('\x1f\x8b'):
        # The gzip compression header is two bytes: 0x1F, 0x8B.
        if not archive_path.endswith(('.tgz', '.tar.gz')):
            archive_path += '.tar.gz'
    elif header.startswith('BZ'):
        # The bzip2 compression header is two bytes: B, Z.
        if not archive_path.endswith('.bz2'):
            archive_path += '.bz2'
    elif header.startswith('PK'):
        # According to Wikipedia, ZIP archives don't have an official magic
        # number, but most of the time we'll find two bytes: P, K (for Phil
        # Katz, creator of the format).
        if not archive_path.endswith('.zip'):
            archive_path += '.zip'
    return archive_path

def initialize_directories():
    """
    Create the directories for the download cache, the source index and the
    binary index if any of them don't exist yet and reset the binary index
    when its format changes.
    """
    # Create all required directories on the fly.
    for directory in [download_cache, source_index, binary_index]:
        if not os.path.isdir(directory):
            os.makedirs(directory)
    # Invalidate the binary distribution cache when the
    # format is changed in backwards incompatible ways.
    if os.path.isfile(index_version_file):
        with open(index_version_file) as handle:
            if int(handle.read()) == CACHE_FORMAT_REVISION:
                logger.debug("Binary distribution cache format is compatible.")
                return
    logger.debug("Binary distribution cache format is incompatible; clearing cache ..")
    for entry in os.listdir(binary_index):
        pathname = os.path.join(binary_index, entry)
        logger.debug(" - Deleting %s.", pathname)
        os.unlink(pathname)
    with open(index_version_file, 'w') as handle:
        handle.write("%i\n" % CACHE_FORMAT_REVISION)

if __name__ == '__main__':
    main()
