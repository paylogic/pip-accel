# Extension of pip-accel that deals with dependencies on system libraries.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: May 17, 2013
# URL: https://github.com/paylogic/pip-accel

# Standard library modules.
import os

# Internal modules.
from pip_accel.logger import logger

# Enable automatic installation?
AUTO_INSTALL = 'PIP_ACCEL_AUTO_INSTALL' in os.environ

def sanity_check_dependencies(project_name):
    """
    If pip-accel fails to build a binary distribution, it will call this
    function as a last chance to install missing dependencies. Should this
    function return ``True`` then pip-accel will retry the build once.

    Expects the project name of a requirement as found on PyPi.

    Returns ``True`` if missing dependencies were successfully installed,
    ``False`` otherwise.
    """
    logger.info("%s: Checking for missing dependencies ..", project_name)
    known_dependencies = current_platform.find_dependencies(project_name.lower())
    if not known_dependencies:
        logger.info("No known dependencies. Maybe you have a suggestion?")
    else:
        installed_packages = set(current_platform.find_installed())
        missing_packages = [p for p in known_dependencies if p not in installed_packages]
        if not missing_packages:
            logger.info("No known to be missing dependencies found.")
        else:
            command_line = ['sudo'] + current_platform.install_command(missing_packages)
            if AUTO_INSTALL or confirm_installation(missing_packages, command_line):
                exit_code = os.spawnvp(os.P_WAIT, 'sudo', command_line)
                if exit_code == 0:
                    logger.info("Successfully installed %i missing dependenc%s.",
                                len(missing_packages),
                                len(missing_packages) == 1 and 'y' or 'ies')
                    return True
                else:
                    logger.error("Failed to install %i missing dependenc%s!",
                                 len(missing_packages),
                                 len(missing_packages) == 1 and 'y' or 'ies')

def confirm_installation(packages, command_line):
    """
    Notify the user that there are missing dependencies and how they can be
    installed. Then ask the user whether we are allowed to install the
    dependencies.

    Expects two arguments: A list of strings with the names of the packages
    that are missing and a list of strings with the command line needed to
    install the packages.

    Returns ``True`` if the user agrees to the installation, ``False``
    otherwise.
    """
    logger.info("You seem to be missing %i dependenc%s: %s.", len(packages),
                len(packages) == 1 and 'y' or 'ies', " ".join(packages))
    logger.info("I can install %s for you with this command: %s",
                len(packages) == 1 and 'it' or 'them',
                " ".join(command_line))
    try:
        prompt = "Do you want me to install %s dependenc%s? [y/N] "
        choice = raw_input(prompt % (len(packages) == 1 and 'this' or 'these',
                                     len(packages) == 1 and 'y' or 'ies'))
        if choice.lower().strip() == 'y':
            logger.info("Got permission to install missing dependenc%s.",
                        len(packages) == 1 and 'y' or 'ies')
            return True
    except:
        pass
    logger.error("Refused installation of missing dependenc%s!",
                 len(packages) == 1 and 'y' or 'ies')
    return False

class Ubuntu:

    """
    Preliminary platform support for Ubuntu Linux.
    """

    def find_dependencies(self, project_name):
        """
        Find the system packages that should be installed to compile & run a
        known project from PyPi.

        Expects one argument: The name of the project as given on PyPi.

        Returns a list with the names of the system packages that should be
        installed in order to compile and run the project. For unknown projects
        an empty list is returned.
        """
        if project_name == 'lxml':
            return ['libxml2-dev', 'libxslt1-dev']
        elif project_name == 'm2crypto':
            return ['libssl-dev', 'swig']
        elif project_name == 'mysql-python':
            return ['libmysqlclient-dev']
        elif project_name == 'python-mcrypt':
            return ['libmcrypt-dev']
        elif project_name == 'mercurial':
            return ['python-dev']
        else:
            return []

    def find_installed(self):
        """
        Find the packages that are installed on the current system.

        Returns a list of strings (containing package names).
        """
        installed_packages = []
        handle = os.popen('dpkg -l')
        for line in handle:
            tokens = line.split()
            if len(tokens) >= 2 and tokens[0] == 'ii':
                installed_packages.append(tokens[1])
        return installed_packages

    def install_command(self, missing_packages):
        """
        Determine the command line needed to install the given package(s).

        Expects a list with the names of one or more system packages.

        Returns a list containing the program and its arguments.
        """
        return ['apt-get', 'install', '--yes'] + missing_packages

def detect_platform():
    """
    Select the interface to the system package manager.

    Returns an object that provides a simple interface to the system package
    manager, unless the platform is unsupported in which case ``None`` is
    returned.
    """
    # Use the lsb_release program to recognize Ubuntu Linux.
    handle = os.popen('lsb_release -si 2>/dev/null')
    output = handle.read()
    handle.close()
    distributor_id = output.strip().lower()
    if distributor_id == 'ubuntu':
        return Ubuntu()

# The interface to the package manager of the current platform (if any).
current_platform = detect_platform()
