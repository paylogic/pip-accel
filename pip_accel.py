#!/usr/bin/env python

# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: May 15, 2013
# URL: https://github.com/paylogic/pip-accel
#
# TODO Consider using pip's API instead of running it as a subprocess.
# TODO Permanently store logs in the pip-accel directory (think about log rotation).
# TODO Maybe we should save the output of `python setup.py bdist_dumb` somewhere as well?
# FIXME When we run pip to download source distributions it's silent for a long time... (buffered output)

"""
Usage: pip-accel [ARGUMENTS TO PIP]

The pip-accel program is a wrapper for pip, the Python package manager. It
accelerates the usage of pip to initialize Python virtual environments given
one or more requirements files. The pip-accel command supports all subcommands
and options supported by pip, however it is only useful for the "pip install"
subcommand.

For more information please refer to the GitHub project page
at https://github.com/paylogic/pip-accel
"""

import os
import os.path
import pkg_resources
import pwd
import re
import sys
import tarfile
import time
import urllib
import urlparse

# Whether a user is directly looking at the output.
INTERACTIVE = os.isatty(1)

# Check if the operator requested verbose output.
VERBOSE = '-v' in sys.argv

# Find the environment where requirements are to be installed.
ENVIRONMENT = os.path.abspath(os.environ.get('VIRTUAL_ENV', sys.prefix))

# The main loop of pip-accel retries at most this many times to counter pip errors
# due to connectivity issues with PyPi and/or linked distribution websites.
MAX_RETRIES = 10

# The version number of the binary distribution cache format in use. When we
# break backwards compatibility we bump this number so that pip-accel knows it
# should clear the cache before proceeding.
CACHE_FORMAT_REVISION = 2

# Look up the home directory of the effective user id so we can generate
# pathnames relative to the home directory.
HOME = pwd.getpwuid(os.getuid()).pw_dir

def expanduser(pathname):
    """
    Variant of os.path.expanduser() that doesn't use $HOME but instead uses the
    home directory of the effective user id. This is basically a workaround for
    ``sudo -s`` not resetting $HOME.
    """
    return re.sub('^~/', HOME, pathname)

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
    Main logic of the pip-accel command.
    """
    arguments = sys.argv[1:]
    if not arguments:
        message("%s\n", __doc__.strip(), prefix=False)
        sys.exit(0)
    # If no install subcommand is given we pass the command line straight
    # to pip without any changes and exit immediately afterwards.
    if 'install' not in arguments:
        sys.exit(os.spawnvp(os.P_WAIT, 'pip', ['pip'] + arguments))
    main_timer = Timer()
    initialize_directories()
    # Execute "pip install" in a loop in order to retry after intermittent
    # error responses from servers (which can happen quite frequently).
    try:
        for i in xrange(1, MAX_RETRIES):
            requirements = unpack_source_dists(arguments)
            if requirements is None:
                download_source_dists(arguments)
            elif not requirements:
                message("No requirements found in pip's output, probably there's nothing to do.\n")
                return
            else:
                if build_binary_dists(requirements) and install_requirements(requirements):
                    message("Done! Took %s to install %i package%s.\n", main_timer, len(requirements), '' if len(requirements) == 1 else 's')
                return
    except InstallationError:
        # Abort early when pip reports installation errors.
        message("Error: Pip reported unrecoverable installation errors. Please fix and rerun!\n")
        sys.exit(1)
    # Abort when after N retries we still failed to download source distributions.
    message("Error: External command failed %i times, aborting!\n" % MAX_RETRIES)
    sys.exit(1)

def unpack_source_dists(arguments):
    """
    Check whether there are local source distributions available for all
    requirements, unpack the source distribution archives and find the names
    and versions of the requirements. By using the "pip install --no-install"
    command we avoid reimplementing the following pip features:

     - Parsing of "requirements.txt" (including recursive parsing)
     - Resolution of possibly conflicting pinned requirements
     - Unpacking source distributions in multiple formats
     - Finding the name & version of a given source distribution

    Expects one argument: a list of strings with the command line arguments to
    be passed to the `pip` command.

    Returns the list of tuples also returned by and documented under the
    parse_requirements() function, unless `pip` fails in which case None is
    returned instead.
    """
    unpack_timer = Timer()
    message("Unpacking local source distributions ..\n")
    # Execute pip to unpack the source distributions.
    output = run_pip(arguments + ['-v', '-v', '--no-install'],
                     use_remote_index=False)
    if output is not None:
        # If pip succeeded, parse its output to find the pinned requirements.
        message("Unpacked local source distributions in %s.\n", unpack_timer)
        return parse_requirements(output)
    else:
        # If pip failed, notify the user.
        interactive_message("Warning: We probably don't have all source distributions yet")
        return None

def parse_requirements(pip_output):
    """
    Parse the output of `pip install -v -v --no-install` to find the pinned
    requirements reported by pip.

    Expects one argument: a list containing all lines of output reported by a
    `pip install -v -v --no-install ...` command.

    Returns a list of tuples where each tuple contains three values in this
    order: (package-name, package-version, directory). The third value points
    to an existing directory containing the unpacked sources.
    """
    requirements = []
    # This is the relevant (verbose) output of a normal "pip install something" command:
    #   Source in /some/directory has version 1.2.3, which satisfies requirement something
    # This is the relevant (verbose) output of a "pip install --editable /another/directory" command:
    #   Source in /some/directory has version 2.3.4, which satisfies requirement foobar==2.3.4 from file:///another/directory
    pattern = re.compile(r'^\s*Source in (.+?) has version (.+?), which satisfies requirement ([^ ]+)')
    for line in pip_output:
        match = pattern.match(line)
        if match:
            directory = match.group(1)
            version = match.group(2)
            requirement = pkg_resources.Requirement.parse(match.group(3))
            requirements.append((requirement.project_name, version, directory))
    message("Found %i requirement%s in pip's output.\n",
            len(requirements), '' if len(requirements) == 1 else 's')
    for name, version, directory in requirements:
        debug(" - %s (%s)\n", name, version)
    return requirements

def download_source_dists(arguments):
    """
    Download missing source distributions.

    Expects one argument: a list containing all lines of output reported by
    `pip install -v -v --no-install`.
    """
    download_timer = Timer()
    message("Downloading source distributions ..\n")
    # Execute pip to download missing source distributions.
    output = run_pip(arguments + ['--no-install'],
                     use_remote_index=True)
    if output is not None:
        message("Finished downloading source distributions in %s.\n", download_timer)
    else:
        interactive_message("Warning: Failed to download one or more source distributions")

def find_binary_dists():
    """
    Find all previously cached binary distributions.

    Returns a dictionary with (package-name, package-version) tuples as keys
    and pathnames of binary archives as values.
    """
    message("Scanning binary distribution index ..\n")
    distributions = {}
    for filename in sorted(os.listdir(binary_index), key=str.lower):
        match = re.match(r'^(.+?):(.+?)\.tar\.gz$', filename)
        if match:
            key = (match.group(1).lower(), match.group(2))
            debug("Matched %s in %s\n", key, filename)
            distributions[key] = os.path.join(binary_index, filename)
        else:
            message("Failed to match filename: %s\n", filename)
    message("Found %i existing binary distribution%s.\n",
            len(distributions), '' if len(distributions) == 1 else 's')
    for (name, version), filename in distributions.iteritems():
        debug(" - %s (%s) in %s\n", name, version, filename)
    return distributions

def build_binary_dists(requirements):
    """
    Convert source distributions to binary distributions.

    Expects a list of tuples in the format of the return value of the
    parse_requirements() function.

    Returns True if it succeeds in building a binary distribution, False
    otherwise (probably because of missing binary dependencies like system
    libraries).
    """
    existing_binary_dists = find_binary_dists()
    message("Building binary distributions ..\n")
    for name, version, directory in requirements:
        # Check if a binary distribution already exists.
        filename = existing_binary_dists.get((name.lower(), version))
        if filename:
            debug("Existing binary distribution for %s (%s) found at %s\n", name, version, filename)
            continue
        # Make sure the source distribution contains a setup script.
        setup_script = os.path.join(directory, 'setup.py')
        if not os.path.isfile(setup_script):
            message("Warning: Package %s (%s) is not a source distribution.\n", name, version)
            continue
        old_directory = os.getcwd()
        # Build a binary distribution.
        os.chdir(directory)
        message("Building binary distribution of %s (%s) ..\n", name, version)
        status = (os.system('python setup.py bdist_dumb --format=gztar') == 0)
        os.chdir(old_directory)
        if not status:
            message("Failed to build binary distribution!\n")
            return False
        # Move the generated distribution to the binary index.
        filenames = os.listdir(os.path.join(directory, 'dist'))
        if len(filenames) != 1:
            message("Error: Build process did not result in one binary distribution! (matches: %s)\n", filenames)
            return False
        cache_file = '%s:%s.tar.gz' % (name, version)
        message("Copying binary distribution %s to cache as %s.\n", filenames[0], cache_file)
        cache_binary_distribution(os.path.join(directory, 'dist', filenames[0]),
                                  os.path.join(binary_index, cache_file))
    message("Finished building binary distributions.\n")
    return True

def cache_binary_distribution(input_path, output_path):
    """
    Transform a binary distribution archive created with `python setup.py
    bdist_dumb --format=gztar` into a form that can be cached for future use.
    This comes down to making the pathnames inside the archive relative to the
    "prefix" that the binary distribution was built for.

    Expects two arguments: The pathname of the original binary distribution
    archive and the pathname of the binary distribution in the cache
    directory.
    """
    # Copy the tar archive file by file so we can rewrite their pathnames.
    debug("Expected prefix in binary distribution archive: %s\n", ENVIRONMENT)
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
            debug("Warning: Ignoring device file: %s\n", absolute_pathname)
        elif not member.isdir():
            modified_pathname = os.path.relpath(absolute_pathname, ENVIRONMENT)
            if os.path.isabs(modified_pathname):
                message("Warning: Failed to transform pathname in binary distribution to relative path! (original: %r, modified: %r)\n",
                        original_pathname, modified_pathname)
            else:
                debug("Transformed %r -> %r.\n", original_pathname, modified_pathname)
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

    Expects a list of tuples in the format of the return value of the
    parse_requirements() function.

    Returns True if it succeeds in installing all requirements from binary
    distribution archives, False otherwise.
    """
    install_timer = Timer()
    existing_binary_dists = find_binary_dists()
    message("Installing from binary distributions ..\n")
    for name, version, directory in requirements:
        filename = existing_binary_dists.get((name.lower(), version))
        if not filename:
            message("Error: No binary distribution of %s (%s) available!\n", name, version)
            return False
        install_binary_dist(filename, install_prefix=install_prefix)
    message("Finished installing all requirements in %s.\n", install_timer)
    return True

def install_binary_dist(filename, install_prefix=ENVIRONMENT):
    """
    Install a binary distribution created with `python setup.py bdist` into the
    given prefix (a directory like /usr, /usr/local or a virtual environment).

    Expects two arguments: The pathname of the tar archive and the pathname of
    the installation prefix.
    """
    # TODO This is quite slow for modules like Django. Speed it up! Two choices:
    #  1. Run the external tar program to unpack the archive. This will
    #     slightly complicate the fixing up of hashbangs.
    #  2. Using links? The plan: We can maintain a "seed" environment under
    #     $PIP_ACCEL_CACHE and use symbolic and/or hard links to populate other
    #     places based on the "seed" environment.
    install_timer = Timer()
    python = os.path.join(install_prefix, 'bin', 'python')
    message("Installing binary distribution %s to %s ..\n", filename, install_prefix)
    archive = tarfile.open(filename, 'r:gz')
    for member in archive.getmembers():
        install_path = os.path.join(install_prefix, member.name)
        directory = os.path.dirname(install_path)
        if not os.path.isdir(directory):
            debug("Creating directory: %s\n", directory)
            os.makedirs(directory)
        debug("Writing file: %s\n", install_path)
        file_handle = archive.extractfile(member)
        with open(install_path, 'w') as handle:
            contents = file_handle.read()
            if contents.startswith('#!/'):
                contents = fix_hashbang(python, contents)
            handle.write(contents)
        os.chmod(install_path, member.mode)
    archive.close()
    message("Finished installing binary distribution in %s.\n", install_timer)

def fix_hashbang(python, contents):
    """
    Rewrite the hashbang in an executable script so that the Python program
    inside the virtual environment is used instead of a system wide Python.

    Expects two arguments: The absolute pathname of the Python program inside
    the virtual environment and a string with the contents of the script whose
    hashbang should be fixed.

    Returns the modified contents of the script as a string.
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
        debug("Hashbang %r looks like a Python hashbang! We'll rewrite it!\n", hashbang)
        parts[0] = '#!%s' % python
        contents = ''.join(parts)
    else:
        message("Warning: Failed to match hashbang: %r\n", hashbang)
    return contents

def run_pip(arguments, use_remote_index):
    """
    Execute a modified `pip install` command.

    Expects two arguments: A list of strings containing the arguments that will
    be passed to `pip` followed by a boolean indicating whether `pip` may
    contact http://pypi.python.org.

    Returns a list of strings with the lines of output from `pip` on success,
    None otherwise (`pip` exited with a nonzero exit status).

    Note that if pip reports an unrecoverable installation error, the custom
    exception type `InstallationError` is raised so that the pip accelerator
    can abort immediately instead of entering the retry loop.
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
        command_line += ['pip'] + arguments
    message("Executing command: %s\n", ' '.join(command_line))
    pip = os.popen(' '.join(command_line))
    output = []
    for line in pip:
        message("  %s\n", line.rstrip(), prefix=False)
        output.append(line)
        if re.search(r'\bInstallationError:', line):
            raise InstallationError
    if pip.close() is None:
        update_source_dists_index()
        return output
    else:
        # Explicit is better than implicit.
        return None

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
                message("Linking files:\n")
                message(" - Source: %s\n", download_path)
                message(" - Target: %s\n", archive_path)
                os.symlink(download_path, archive_path)

def add_extension(download_path, archive_path):
    """
    Make sure all cached source distributions have the right file extension,
    because not all distribution sites provide URLs with proper filenames in
    them while we really need the proper filenames to build the local source
    index.

    Expects two arguments: The pathname of the source distribution archive in
    the download cache and the pathname of the distribution archive in the
    source index directory.

    Returns the (possibly modified) pathname of the distribution archive in the
    source index directory.

    Previously this used the "file" executable, now it checks the magic file
    headers itself. I could have used any of the numerous libmagic bindings on
    PyPi, but that would add a binary dependency to pip-accel and I don't want
    that :-).
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
                debug("Binary distribution cache format is compatible.\n")
                return
    debug("Binary distribution cache format is incompatible; clearing cache ..\n")
    for entry in os.listdir(binary_index):
        pathname = os.path.join(binary_index, entry)
        debug(" - Deleting %s\n", pathname)
        os.unlink(pathname)
    with open(index_version_file, 'w') as handle:
        handle.write("%i\n" % CACHE_FORMAT_REVISION)

def interactive_message(text):
    """
    Show a message to the operator for 5 seconds.

    Expects one argument: the text to present to the user.
    """
    for i in range(5, 0, -1):
        message("%s, retrying after %i second%s .. ", text, i, '' if i == 1 else 's')
        time.sleep(1)
    message("\n", prefix=False)

def debug(text, *args, **kw):
    """
    Print a formatted message to the console if the operator requested verbose
    execution.

    Expects the same arguments as the message() function.
    """
    if VERBOSE:
        message(text, *args, **kw)

def message(text, *args, **kw):
    """
    Print a formatted message to the console. By default the prefix
    `(pip-accel)` is added to the text.

    Expects at least one argument: The text to print. If further positional
    arguments are received the text will be formatted using those arguments and
    the `%` operator. The prefix can be disabled by passing the keyword
    argument `prefix=False`.
    """
    if kw.get('prefix', True):
        text = '(pip-accel) ' + text
    if INTERACTIVE:
        text = '\r' + text
    sys.stderr.write(text % args)

class InstallationError(Exception):
    """
    Custom exception type used to signal that pip reported an unrecoverable
    installation error. The pip accelerator can't do anything useful when pip
    reports such errors, so it will simply abort.
    """
    pass

class Timer:

    """
    Easy to use timer to keep track of long during operations.
    """

    def __init__(self):
        self.start_time = time.time()

    def __str__(self):
        return "%.2f seconds" % self.elapsed_time

    @property
    def elapsed_time(self):
        return time.time() - self.start_time

if __name__ == '__main__':
    main()
