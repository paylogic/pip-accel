# Extension of pip-accel that deals with dependencies on system packages.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: June 16, 2013
# URL: https://github.com/paylogic/pip-accel

"""
Extension of the pip accelerator that deals with dependencies on system
packages. Currently only Debian Linux and derivative Linux distributions are
supported by this extension.
"""

# Standard library modules.
import ConfigParser
import os
import os.path

# Internal modules.
from pip_accel.logger import logger

# Enable automatic installation?
AUTO_INSTALL = 'PIP_ACCEL_AUTO_INSTALL' in os.environ

def sanity_check_dependencies(project_name):
    """
    If ``pip-accel`` fails to build a binary distribution, it will call this
    function as a last chance to install missing dependencies. Should this
    function return ``True`` then ``pip-accel`` will retry the build once.

    :param project_name: The project name of a requirement as found on PyPI.

    :returns: ``True`` if any missing system packages were successfully
              installed, ``False`` otherwise.
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

    :param packages: A list of strings with the names of the packages that are
                     missing.
    :param command_line: A list of strings with the command line needed to
                         install the packages.

    :returns: ``True`` if the user agrees to the installation, ``False``
              otherwise.
    """
    logger.info("You seem to be missing %i dependenc%s: %s", len(packages),
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

class BasePlatform(object):

    """
    Base class for system package manager interfaces. Also implements the mock
    interface for platforms which are not (yet) supported by the pip
    accelerator.
    """

    @staticmethod
    def is_supported():
        """
        Check whether the current system supports the implemented package
        manager.
        """
        logger.debug("Falling back to dummy package manager interface ..")
        return True

    def __init__(self):
        """
        Load any predefined dependencies for the platform from a configuration
        file bundled with the pip accelerator.
        """
        config_name = getattr(self, 'config', '')
        if config_name:
            script = os.path.abspath(__file__)
            directory = os.path.dirname(script)
            config_path = os.path.join(directory, '%s.ini' % config_name)
            if os.path.isfile(config_path):
                logger.debug("Loading system package configuration from %s ..", config_path)
                parser = ConfigParser.RawConfigParser()
                parser.read(config_path)
                if parser.has_section('dependencies'):
                    self.dependencies = dict((n.lower(), v.split()) for n, v in parser.items('dependencies'))

    def find_dependencies(self, project_name):
        """
        Find the system packages that should be installed to compile and run a
        known project from PyPI.

        :param project_name: The name of the project as given on PyPI.

        :returns: A list with the names of the system packages that should be
                  installed in order to compile and run the project. For
                  unknown projects an empty list is returned.
        """
        return self.dependencies.get(project_name.lower(), [])

    def find_installed(self):
        return []

class DebianLinux(BasePlatform):

    """
    Simple interface to the package management system of Debian Linux and
    derivative distributions like Ubuntu Linux.
    """

    config = 'debian'

    @staticmethod
    def is_supported():
        """
        Use the ``lsb_release`` program to check whether we are on a Debian
        Linux system (or a derivative distribution of Debian like Ubuntu).

        :returns: ``True`` if we are, ``False`` if we're not.
        """
        logger.debug("Checking if we're on a Debian (derived) system ..")
        handle = os.popen('lsb_release -si 2>/dev/null')
        output = handle.read()
        handle.close()
        distributor_id = output.strip()
        logger.debug("Distributor ID: %s", distributor_id)
        if distributor_id.lower() in ('debian', 'ubuntu'):
            logger.debug("Using Debian package manager interface ..")
            return True

    def find_installed(self):
        """
        Find the packages that are installed on the current system.

        :returns: A list of strings with package names.
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

        :param missing_packages: A list with the names of one or more system
                                 packages to be installed.

        :returns: A list containing the program name and its arguments.
        """
        return ['apt-get', 'install', '--yes'] + missing_packages

# Select the interface to the package manager of the current platform.
for Interface in [DebianLinux, BasePlatform]:
    if Interface.is_supported():
        current_platform = Interface()
        break
