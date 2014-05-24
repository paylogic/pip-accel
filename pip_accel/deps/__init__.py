# Extension of pip-accel that deals with dependencies on system packages.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: May 24, 2014
# URL: https://github.com/paylogic/pip-accel

"""
System package dependency handling
==================================

Extension of the pip accelerator that deals with dependencies on system
packages. Currently only Debian Linux and derivative Linux distributions
are supported by this extension.
"""

# Standard library modules.
import logging
import os
import os.path

try:
    # Python 2.x.
    import ConfigParser as configparser
except ImportError:
    # Python 3.x.
    import configparser

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

def sanity_check_dependencies(project_name, auto_install=None):
    """
    If ``pip-accel`` fails to build a binary distribution, it will call this
    function as a last chance to install missing dependencies. If this function
    does not raise an exception, ``pip-accel`` will retry the build once.

    :param project_name: The project name of a requirement as found on PyPI.
    :param auto_install: ``True`` if dependencies on system packages may be
                         automatically installed, ``False`` if missing system
                         packages should raise an error, ``None`` if the
                         decision should be based on the environment variable
                         ``PIP_ACCEL_AUTO_INSTALL``.

    If missing system packages are found, this function will try to install
    them. If anything "goes wrong" an exception is raised:

    - If ``auto_install=False`` then :py:class:`DependencyCheckFailed` is
      raised
    - If installation of missing packages fails
      :py:class:`DependencyInstallationFailed` is raised
    - If the user refuses to let pip-accel install missing packages
      :py:class:`RefusedAutomaticInstallation` is raised.

    If all goes well nothing is raised, nor is anything returned.
    """
    # Has the caller forbidden us from automatic installation?
    auto_install_forbidden = (auto_install == False)
    if auto_install is not None:
        # If the caller made an explicit choice, we'll respect that.
        auto_install_allowed = auto_install
    else:
        # Otherwise we check the environment variable.
        auto_install_allowed = 'PIP_ACCEL_AUTO_INSTALL' in os.environ
    logger.info("%s: Checking for missing dependencies ..", project_name)
    known_dependencies = current_platform.find_dependencies(project_name)
    if not known_dependencies:
        logger.info("%s: No known dependencies... Maybe you have a suggestion?", project_name)
    else:
        installed_packages = set(current_platform.find_installed())
        missing_packages = [p for p in known_dependencies if p not in installed_packages]
        if not missing_packages:
            logger.info("%s: All known dependencies are already installed.", project_name)
        elif auto_install_forbidden:
            msg = "Missing %i system package%s (%s) required by %s but automatic installation is disabled!"
            raise DependencyCheckFailed(msg % (len(missing_packages), '' if len(missing_packages) == 1 else 's',
                                               ', '.join(missing_packages), project_name))
        else:
            command_line = ['sudo'] + current_platform.install_command(missing_packages)
            if not auto_install_allowed:
                confirm_installation(project_name, missing_packages, command_line)
            logger.info("%s: Missing %i dependenc%s: %s",
                        project_name, len(missing_packages),
                        'y' if len(missing_packages) == 1 else 'ies',
                        " ".join(missing_packages))
            exit_code = os.spawnvp(os.P_WAIT, 'sudo', command_line)
            if exit_code == 0:
                logger.info("%s: Successfully installed %i missing dependenc%s.",
                            project_name, len(missing_packages),
                            len(missing_packages) == 1 and 'y' or 'ies')
            else:
                logger.error("%s: Failed to install %i missing dependenc%s!",
                             project_name, len(missing_packages),
                             len(missing_packages) == 1 and 'y' or 'ies')
                msg = "Failed to install %i system package%s required by %s! (command failed: %s)"
                raise DependencyInstallationFailed(msg % (len(missing_packages), '' if len(missing_packages) == 1 else 's',
                                                          project_name, command_line))

def confirm_installation(project_name, packages, command_line):
    """
    Notify the user that there are missing dependencies and how they can be
    installed. Then ask the user whether we are allowed to install the
    dependencies.

    :param packages: A list of strings with the names of the packages that are
                     missing.
    :param command_line: A list of strings with the command line needed to
                         install the packages.

    Raises :py:class:`RefusedAutomaticInstallation` when the user refuses to
    let pip-accel install any missing dependencies.
    """
    logger.info("%s: You seem to be missing %i dependenc%s: %s",  project_name,
                len(packages), len(packages) == 1 and 'y' or 'ies', " ".join(packages))
    logger.info("%s: I can install %s for you with this command: %s",
                project_name, len(packages) == 1 and 'it' or 'them',
                " ".join(command_line))
    try:
        prompt = "Do you want me to install %s dependenc%s? [y/N] "
        choice = raw_input(prompt % (len(packages) == 1 and 'this' or 'these',
                                     len(packages) == 1 and 'y' or 'ies'))
        if choice.lower().strip() == 'y':
            logger.info("Got permission to install missing dependenc%s.",
                        len(packages) == 1 and 'y' or 'ies')
            return
    except:
        pass
    logger.error("%s: Refused installation of missing dependenc%s!",
                 project_name, len(packages) == 1 and 'y' or 'ies')
    msg = "%s: User canceled automatic installation of missing dependenc%s!"
    raise RefusedAutomaticInstallation(msg % (project_name, 'y' if len(packages) == 1 else 'ies'))

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
                parser = configparser.RawConfigParser()
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
        """
        Find the packages that are installed on the current system.

        :returns: A list of strings with package names.
        """
        return []

    def install_command(self, missing_packages):
        """
        Determine the command line needed to install the given package(s).

        :param missing_packages: A list with the names of one or more system
                                 packages to be installed.

        :returns: A list containing the program name and its arguments.
        """
        raise NotImplemented

class DebianLinux(BasePlatform):

    """
    Simple interface to the package management system of Debian Linux and
    derivative distributions like Ubuntu Linux.
    """

    config = 'debian'

    @staticmethod
    def is_supported():
        """
        Find out if we are running on a Debian (derived) system by checking if
        the file ``/etc/debian_version`` exists (this file is installed by the
        Debian system package ``base-files``).

        :returns: ``True`` if we are, ``False`` if we're not.
        """
        filename = '/etc/debian_version'
        if os.path.exists(filename):
            logger.debug("Looks like we are on a Debian (derived) system (%s exists) ..", filename)
            return True
        else:
            logger.debug("Looks like we're not on a Debian (derived) system (%s doesn't exist) ..", filename)
            return False

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

class DependencyCheckFailed(Exception):
    """
    Custom exception type raised by :py:func:`sanity_check_dependencies()` when
    one or more known to be required system packages are missing and automatic
    installation of missing dependencies is explicitly disabled.
    """

class RefusedAutomaticInstallation(Exception):
    """
    Custom exception type raised by :py:func:`confirm_installation()` when the
    user refuses to install missing system packages.
    """

class DependencyInstallationFailed(Exception):
    """
    Custom exception type raised by :py:func:`sanity_check_dependencies()` when
    installation of missing system packages fails.
    """

# Select the interface to the package manager of the current platform.
for Interface in [DebianLinux, BasePlatform]:
    if Interface.is_supported():
        current_platform = Interface()
        break
