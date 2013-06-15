# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: June 15, 2013
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
- :py:func:`build_binary_dists`
- :py:func:`install_requirements`
"""

# Semi-standard module versioning.
__version__ = '0.8.16'

# Standard library modules.
import logging
import os
import os.path
import pkg_resources
import pwd
import re
import sys
import tarfile
import textwrap
import time
import urllib
import urlparse

# External dependencies.
from coloredlogs import ColoredStreamHandler
from pip.backwardcompat import string_types
from pip.baseparser import create_main_parser
from pip.commands.install import InstallCommand
from pip.exceptions import DistributionNotFound, InstallationError
from pip.status_codes import SUCCESS

# Initialize the logging subsystem.
logger = logging.getLogger('pip-accel')
logger.setLevel(logging.INFO)
logger.addHandler(ColoredStreamHandler())

# Whether a user is directly looking at the output.
INTERACTIVE = os.isatty(1)

# Check if the operator requested verbose output.
if '-v' in sys.argv or 'PIP_ACCEL_VERBOSE' in os.environ:
    logger.setLevel(logging.DEBUG)

# Find the environment where requirements are to be installed.
ENVIRONMENT = os.path.abspath(os.environ.get('VIRTUAL_ENV', sys.prefix))

# The main loop of pip-accel retries at most this many times to counter pip errors
# due to connectivity issues with PyPI and/or linked distribution websites.
MAX_RETRIES = 10

# The version number of the binary distribution cache format in use. When we
# break backwards compatibility we bump this number so that pip-accel knows it
# should clear the cache before proceeding.
CACHE_FORMAT_REVISION = 3

# Look up the home directory of the effective user id so we can generate
# pathnames relative to the home directory.
HOME = pwd.getpwuid(os.getuid()).pw_dir

def expanduser(pathname):
    """
    Variant of :py:func:`os.path.expanduser()` that doesn't use ``$HOME`` but
    instead uses the home directory of the effective user id. This is basically
    a workaround for ``sudo -s`` not resetting ``$HOME``.

    :param pathname: A pathname that may start with ``~/``, indicating the path
                     should be interpreted as being relative to the home
                     directory of the current (effective) user.
    """
    return re.sub('^~(?=/)', HOME, pathname)

# Select the default location of the download cache and other files based on
# the user running the pip-accel command (root goes to /var/cache/pip-accel,
# otherwise ~/.pip-accel).
if os.getuid() == 0:
    download_cache = '/root/.pip/download-cache'
    pip_accel_cache = '/var/cache/pip-accel'
else:
    download_cache = expanduser('~/.pip/download-cache')
    pip_accel_cache = expanduser('~/.pip-accel')

# Enable overriding the default locations with environment variables.
if 'PIP_DOWNLOAD_CACHE' in os.environ:
    download_cache = expanduser(os.environ['PIP_DOWNLOAD_CACHE'])
if 'PIP_ACCEL_CACHE' in os.environ:
    pip_accel_cache = expanduser(os.environ['PIP_ACCEL_CACHE'])

# Generate the absolute pathnames of the source/binary caches.
source_index = os.path.join(pip_accel_cache, 'sources')
binary_index = os.path.join(pip_accel_cache, 'binaries')
index_version_file = os.path.join(pip_accel_cache, 'version.txt')

def main():
    """
    Main logic of the ``pip-accel`` command.
    """
    arguments = sys.argv[1:]
    if not arguments:
        print_usage()
        sys.exit(0)
    # If no install subcommand is given we pass the command line straight
    # to pip without any changes and exit immediately afterwards.
    if 'install' not in arguments:
        sys.exit(os.spawnvp(os.P_WAIT, 'pip', ['pip'] + arguments))
    # Make sure the prefix is the same as the environment.
    if not os.path.samefile(sys.prefix, ENVIRONMENT):
        logger.error("You are trying to install in prefix #1 which is different from prefix #2 where pip-accel is installed! Please install pip-accel under the other prefix to install packages there.")
        logger.info("Prefix #1: %s (the environment prefix)", ENVIRONMENT)
        logger.info("Prefix #2: %s (the installation prefix)", sys.prefix)
        sys.exit(1)
    main_timer = Timer()
    initialize_directories()
    # Execute "pip install" in a loop in order to retry after intermittent
    # error responses from servers (which can happen quite frequently).
    try:
        for i in xrange(1, MAX_RETRIES):
            try:
                requirements = unpack_source_dists(arguments)
            except DistributionNotFound:
                logger.warn("Warning: We don't have all source distributions yet!")
                download_source_dists(arguments)
            else:
                if not requirements:
                    logger.info("No unsatisfied requirements found, probably there's nothing to do.")
                else:
                    if build_binary_dists(requirements) and install_requirements(requirements):
                        logger.info("Done! Took %s to install %i package%s.", main_timer, len(requirements), '' if len(requirements) == 1 else 's')
                    else:
                        sys.exit(1)
                return
    except InstallationError:
        # Abort early when pip reports installation errors.
        logger.fatal("Error: Pip reported unrecoverable installation errors. Please fix and rerun!")
        sys.exit(1)
    # Abort when after N retries we still failed to download source distributions.
    logger.fatal("Error: External command failed %i times, aborting!" % MAX_RETRIES)
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

def unpack_source_dists(arguments):
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
    # Execute pip to unpack the source distributions.
    requirement_set = run_pip(arguments + ['--no-install'],
                              use_remote_index=False)
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

def download_source_dists(arguments):
    """
    Download missing source distributions.

    :param arguments: A list with the arguments intended for ``pip``.
    """
    download_timer = Timer()
    logger.info("Downloading source distributions ..")
    # Execute pip to download missing source distributions.
    try:
        run_pip(arguments + ['--no-install'], use_remote_index=True)
        logger.info("Finished downloading source distributions in %s.", download_timer)
    except Exception, e:
        logger.warn("Error: pip raised an exception while downloading source distributions: %s.", e)

def find_binary_dists():
    """
    Find all previously cached binary distributions.

    :returns: A dictionary with (package-name, package-version, python-version)
              tuples as keys and pathnames of binary archives as values.
    """
    logger.info("Scanning binary distribution index ..")
    distributions = {}
    for filename in sorted(os.listdir(binary_index), key=str.lower):
        if filename.endswith('.tar.gz'):
            basename = re.sub('\.tar.gz$', '', filename)
            parts = basename.split(':')
            if len(parts) == 3:
                key = (parts[0].lower(), parts[1], parts[2])
                logger.debug("Matched %s in %s.", key, filename)
                distributions[key] = os.path.join(binary_index, filename)
                continue
        logger.debug("Failed to match filename: %s.", filename)
    logger.info("Found %i existing binary distribution%s.",
                len(distributions), '' if len(distributions) == 1 else 's')
    for (name, version, pyversion), filename in distributions.iteritems():
        logger.debug(" - %s (%s, %s) in %s.", name, version, pyversion, filename)
    return distributions

def build_binary_dists(requirements):
    """
    Convert source distributions to binary distributions.

    :param requirements: A list of tuples in the format of the return value of
                         the :py:func:`unpack_source_dists()` function.

    :returns: ``True`` if it succeeds in building a binary distribution,
              ``False`` otherwise (probably because of missing binary
              dependencies like system libraries).
    """
    existing_binary_dists = find_binary_dists()
    logger.info("Building binary distributions ..")
    pyversion = get_python_version()
    for name, version, directory in requirements:
        # Check if a binary distribution already exists.
        filename = existing_binary_dists.get((name.lower(), version, pyversion))
        if filename:
            logger.debug("Existing binary distribution for %s (%s) found at %s.", name, version, filename)
            continue
        # Make sure the source distribution contains a setup script.
        setup_script = os.path.join(directory, 'setup.py')
        if not os.path.isfile(setup_script):
            logger.warn("Warning: Package %s (%s) is not a source distribution.", name, version)
            continue
        old_directory = os.getcwd()
        # Build a binary distribution.
        os.chdir(directory)
        logger.info("Building binary distribution of %s (%s) ..", name, version)
        status = (os.system('"%s/bin/python" setup.py bdist_dumb --format=gztar' % ENVIRONMENT) == 0)
        os.chdir(old_directory)
        if not status:
            logger.error("Failed to build binary distribution of %s! (%s)!", name, version)
            return False
        # Move the generated distribution to the binary index.
        filenames = os.listdir(os.path.join(directory, 'dist'))
        if len(filenames) != 1:
            logger.error("Error: Build process did not result in one binary distribution! (matches: %s)", filenames)
            return False
        cache_file = '%s:%s:%s.tar.gz' % (name, version, pyversion)
        logger.info("Copying binary distribution %s to cache as %s.", filenames[0], cache_file)
        cache_binary_distribution(os.path.join(directory, 'dist', filenames[0]),
                                  os.path.join(binary_index, cache_file))
    logger.info("Finished building binary distributions.")
    return True

def cache_binary_distribution(input_path, output_path):
    """
    Transform a binary distribution archive created with ``python setup.py
    bdist_dumb --format=gztar`` into a form that can be cached for future use.
    This comes down to making the pathnames inside the archive relative to the
    `prefix` that the binary distribution was built for.

    :param input_path: The pathname of the original binary distribution archive
    :param output_path: The pathname of the binary distribution in the cache
                        directory.
    """
    # Copy the tar archive file by file so we can rewrite their pathnames.
    logger.debug("Expected prefix in binary distribution archive: %s.", ENVIRONMENT)
    input_bdist = tarfile.open(input_path, 'r:gz')
    output_bdist = tarfile.open(output_path, 'w:gz')
    for member in input_bdist.getmembers():
        # In my testing the `dumb' tar files created with the `python setup.py
        # bdist' command contain pathnames that are relative to `/' which is
        # kind of awkward: I would like to use os.path.relpath() on them but
        # that won't give the correct result without preprocessing...
        original_pathname = member.name
        absolute_pathname = re.sub(r'^\./', '/', original_pathname)
        if member.isdev():
            logger.debug("Warning: Ignoring device file: %s.", absolute_pathname)
        elif not member.isdir():
            modified_pathname = os.path.relpath(absolute_pathname, ENVIRONMENT)
            if os.path.isabs(modified_pathname):
                logger.warn("Warning: Failed to transform pathname in binary distribution to relative path! (original: %r, modified: %r)",
                            original_pathname, modified_pathname)
            else:
                logger.debug("Transformed %r -> %r.", original_pathname, modified_pathname)
                # Get the file data from the input archive.
                file_data = input_bdist.extractfile(original_pathname)
                # Use all metadata from the input archive but modify the filename.
                member.name = modified_pathname
                # Copy modified metadata + original file data to output archive.
                output_bdist.addfile(member, file_data)
    input_bdist.close()
    output_bdist.close()

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
    existing_binary_dists = find_binary_dists()
    pyversion = get_python_version()
    logger.info("Installing from binary distributions ..")
    for name, version, directory in requirements:
        filename = existing_binary_dists.get((name.lower(), version, pyversion))
        if not filename:
            logger.error("Error: No binary distribution of %s (%s) available!", name, version)
            return False
        install_binary_dist(filename, install_prefix=install_prefix)
    logger.info("Finished installing all requirements in %s.", install_timer)
    return True

def install_binary_dist(filename, install_prefix=ENVIRONMENT):
    """
    Install a binary distribution created with ``python setup.py bdist`` into
    the given prefix (a directory like ``/usr``, ``/usr/local`` or a virtual
    environment).

    :param filename: The pathname of the tar archive.
    :param install_prefix: The "prefix" under which the requirements should be
                           installed. This will be a pathname like ``/usr``,
                           ``/usr/local`` or the pathname of a virtual
                           environment.
    """
    # TODO This is quite slow for modules like Django. Speed it up! Two choices:
    #  1. Run the external tar program to unpack the archive. This will
    #     slightly complicate the fixing up of hashbangs.
    #  2. Using links? The plan: We can maintain a "seed" environment under
    #     $PIP_ACCEL_CACHE and use symbolic and/or hard links to populate other
    #     places based on the "seed" environment.
    install_timer = Timer()
    python = os.path.join(install_prefix, 'bin', 'python')
    logger.info("Installing binary distribution %s to %s ..", filename, install_prefix)
    archive = tarfile.open(filename, 'r:gz')
    for member in archive.getmembers():
        install_path = os.path.join(install_prefix, member.name)
        directory = os.path.dirname(install_path)
        if not os.path.isdir(directory):
            logger.debug("Creating directory: %s ..", directory)
            os.makedirs(directory)
        logger.debug("Writing file: %s ..", install_path)
        file_handle = archive.extractfile(member)
        with open(install_path, 'w') as handle:
            contents = file_handle.read()
            if contents.startswith('#!/'):
                contents = fix_hashbang(python, contents)
            handle.write(contents)
        os.chmod(install_path, member.mode)
    archive.close()
    logger.info("Finished installing binary distribution in %s.", install_timer)

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
    parts = re.split(r'(\r?\n)', contents, 1)
    hashbang = parts[0]
    # Get the base name of the command in the hashbang and deal with hashbangs
    # like `#!/usr/bin/env python'.
    modified_name = re.sub('^env ', '', os.path.basename(hashbang))
    # Only rewrite hashbangs that actually involve Python.
    if re.match(r'^python(\d+(\.\d+)*)?$', modified_name):
        logger.debug("Hashbang %r looks like a Python hashbang! We'll rewrite it!", hashbang)
        parts[0] = '#!%s' % python
        contents = ''.join(parts)
    else:
        logger.debug("Warning: Failed to match hashbang: %r.", hashbang)
    return contents

def run_pip(arguments, use_remote_index):
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
            if not use_remote_index:
                command_line += ['--no-index']
            command_line += arguments[i+1:]
            break
    else:
        command_line = ['pip'] + arguments
    logger.info("Executing command: %s.", ' '.join(command_line))
    parser = create_main_parser()
    pip = CustomInstallCommand(parser)
    initial_options, args = parser.parse_args(command_line[1:])
    exit_status = pip.main(command_line[2:], initial_options)
    # Make sure the output of pip and pip-accel are not intermingled.
    sys.stdout.flush()
    update_source_dists_index()
    if exit_status == SUCCESS:
        return pip.requirement_set
    else:
        raise pip.intercepted_exception

class CustomInstallCommand(InstallCommand):

    """
    Required to call ``pip`` as a Python module instead of a subprocess.

    The ``pip.commands.install.InstallCommand.run()`` method returns a
    ``RequirementSet`` object which ``pip-accel`` is interested in, however
    ``pip.basecommand.Command.main()`` swallows the requirement set (based on
    my reading of the pip 1.3.x source code).

    To work around the problem described above, we subclass ``InstallCommand``
    to wrap the run() method. Yes this is a bit sneaky, but I don't fancy
    reimplementing ``pip.basecommand.Command.main()`` inside ``pip-accel``!
    """

    def run(self, *args, **kw):
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

def get_python_version():
    """
    Return a string identifying the currently running Python version.

    :returns: A string like "py2.6" or "py2.7" containing a short mnemonic
              prefix followed by the major and minor version numbers.
    """
    return "py%i.%i" % (sys.version_info[0], sys.version_info[1])

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

class Timer:

    """
    Easy to use timer to keep track of long during operations.
    """

    def __init__(self):
        """
        Store the time when the timer object was created.
        """
        self.start_time = time.time()

    @property
    def elapsed_time(self):
        """
        Get the number of seconds elapsed since the timer object was created.
        """
        return time.time() - self.start_time

    def __str__(self):
        """
        When a timer object is coerced to a string it will show the number of
        seconds elapsed since the timer object was created.
        """
        return "%.2f seconds" % self.elapsed_time

if __name__ == '__main__':
    main()
