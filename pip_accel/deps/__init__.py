# Extension of pip-accel that deals with dependencies on system packages.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 22, 2014
# URL: https://github.com/paylogic/pip-accel

"""
:py:mod:`pip_accel.deps` - System package dependency handling
=============================================================

The :py:mod:`pip_accel.deps` module is an extension of pip-accel that deals
with dependencies on system packages. Currently only Debian Linux and
derivative Linux distributions are supported by this extension but it should be
fairly easy to add support for other platforms.

The interface between pip-accel and :py:class:`SystemPackageManager` focuses on
:py:func:`~SystemPackageManager.install_dependencies()` (the other methods are
used internally).
"""

# Standard library modules.
import logging
import os
import shlex
import subprocess
import sys

# Modules included in our package.
from pip_accel.compat import configparser
from pip_accel.exceptions import DependencyInstallationFailed, DependencyInstallationRefused, SystemDependencyError

# External dependencies.
from humanfriendly import Timer, concatenate, pluralize

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

class SystemPackageManager(object):

    """Interface to the system's package manager."""

    def __init__(self, config):
        """
        Initialize the system package dependency manager.

        :param config: The pip-accel configuration (a :py:class:`.Config`
                       object).
        """
        # Defaults for unsupported systems.
        self.list_command = 'true'
        self.install_command = 'true'
        self.dependencies = {}
        # Keep a reference to the pip-accel configuration.
        self.config = config
        # Initialize the platform specific package manager interface.
        directory = os.path.dirname(os.path.abspath(__file__))
        for filename in sorted(os.listdir(directory)):
            pathname = os.path.join(directory, filename)
            if filename.endswith('.ini') and os.path.isfile(pathname):
                logger.debug("Loading configuration from %s ..", pathname)
                parser = configparser.RawConfigParser()
                parser.read(pathname)
                # Check if the package manager is supported.
                supported_command = parser.get('commands', 'supported')
                logger.debug("Checking if configuration is supported: %s", supported_command)
                if subprocess.call(supported_command, shell=True) == 0:
                    logger.debug("System package manager configuration is supported!")
                    # Get the commands to list and install system packages.
                    self.list_command = parser.get('commands', 'list')
                    self.install_command = parser.get('commands', 'install')
                    # Get the known dependencies.
                    self.dependencies = dict((n.lower(), v.split()) for n, v
                                             in parser.items('dependencies'))
                    logger.debug("Loaded dependencies of %s: %s",
                                 pluralize(len(self.dependencies), "Python package"),
                                 concatenate(sorted(self.dependencies)))
                else:
                    logger.debug("Command failed, assuming configuration doesn't apply ..")

    def install_dependencies(self, requirement):
        """
        If :py:mod:`pip_accel` fails to build a binary distribution, it will
        call this method as a last chance to install missing dependencies. If
        this function does not raise an exception, :py:mod:`pip_accel` will
        retry the build once.

        :param requirement: A :py:class:`.Requirement` object.
        :returns: ``True`` when missing system packages were installed,
                  ``False`` otherwise.
        :raises: :py:exc:`.DependencyInstallationRefused` when automatic
                 installation is disabled or refused by the operator.
        :raises: :py:exc:`.DependencyInstallationFailed` when the installation
                 of missing system packages fails.
        """
        install_timer = Timer()
        missing_dependencies = self.find_missing_dependencies(requirement)
        if missing_dependencies:
            # Compose the command line for the install command.
            install_command = shlex.split(self.install_command) + missing_dependencies
            if os.getuid() != 0:
                # Prepend `sudo' to the command line.
                install_command.insert(0, 'sudo')
            # Always suggest the installation command to the operator.
            logger.info("You seem to be missing %s: %s",
                        pluralize(len(missing_dependencies), "dependency", "dependencies"),
                        concatenate(missing_dependencies))
            logger.info("You can install %s with this command: %s",
                        "it" if len(missing_dependencies) == 1 else "them", " ".join(install_command))
            if self.config.auto_install is False:
                # Refuse automatic installation and don't prompt the operator when the configuration says no.
                self.installation_refused(requirement, missing_dependencies, "automatic installation is disabled")
            # Get the operator's permission to install the missing package(s).
            if self.config.auto_install or self.confirm_installation(requirement, missing_dependencies, install_command):
                logger.info("Got permission to install %s.",
                            pluralize(len(missing_dependencies), "dependency", "dependencies"))
            else:
                logger.error("Refused installation of missing %s!",
                             "dependency" if len(missing_dependencies) == 1 else "dependencies")
                self.installation_refused(requirement, missing_dependencies, "manual installation was refused")
            if subprocess.call(install_command) == 0:
                logger.info("Successfully installed %s in %s.",
                            pluralize(len(missing_dependencies), "dependency", "dependencies"),
                            install_timer)
                return True
            else:
                logger.error("Failed to install %s.",
                             pluralize(len(missing_dependencies), "dependency", "dependencies"))
                msg = "Failed to install %s required by Python package %s! (%s)"
                raise DependencyInstallationFailed(msg % (pluralize(len(missing_dependencies), "system package", "system packages"),
                                                          requirement.name, concatenate(missing_dependencies)))
        return False

    def find_missing_dependencies(self, requirement):
        """
        Find missing dependencies of a Python package.

        :param requirement: A :py:class:`.Requirement` object.
        :returns: A list of strings with system package names.
        """
        known_dependencies = self.find_known_dependencies(requirement)
        if known_dependencies:
            installed_packages = self.find_installed_packages()
            logger.debug("Checking for missing dependencies of %s ..", requirement.name)
            missing_dependencies = sorted(set(known_dependencies).difference(installed_packages))
            if missing_dependencies:
                logger.debug("Found %s: %s",
                             pluralize(len(missing_dependencies), "missing dependency", "missing dependencies"),
                             concatenate(missing_dependencies))
            else:
                logger.info("All known dependencies are already installed.")
            return missing_dependencies

    def find_known_dependencies(self, requirement):
        """
        Find the known dependencies of a Python package.

        :param requirement: A :py:class:`.Requirement` object.
        :returns: A list of strings with system package names.
        """
        logger.info("Checking for known dependencies of %s ..", requirement.name)
        known_dependencies = sorted(self.dependencies.get(requirement.name.lower(), []))
        if known_dependencies:
            logger.info("Found %s: %s", pluralize(len(known_dependencies), "known dependency", "known dependencies"),
                        concatenate(known_dependencies))
        else:
            logger.info("No known dependencies... Maybe you have a suggestion?")
        return known_dependencies

    def find_installed_packages(self):
        """
        Find the installed system packages.

        :returns: A list of strings with system package names.
        :raises: :py:exc:`.SystemDependencyError` when the command to list the
                 installed system packages fails.
        """
        list_command = subprocess.Popen(self.list_command, shell=True, stdout=subprocess.PIPE)
        stdout, stderr = list_command.communicate()
        if list_command.returncode != 0:
            raise SystemDependencyError("The command to list the installed system packages failed! ({command})",
                                        command=self.list_command)
        installed_packages = sorted(stdout.decode().split())
        logger.debug("Found %i installed system package(s): %s", len(installed_packages), installed_packages)
        return installed_packages

    def installation_refused(self, requirement, missing_dependencies, reason):
        """
        Raise :py:exc:`.DependencyInstallationRefused` with a user friendly message.

        :param requirement: A :py:class:`.Requirement` object.
        :param missing_dependencies: A list of strings with missing dependencies.
        :param reason: The reason why installation was refused (a string).
        """
        msg = "Missing %s (%s) required by Python package %s (%s) but %s!"
        raise DependencyInstallationRefused(msg % (pluralize(len(missing_dependencies), "system package", "system packages"),
                                                   concatenate(missing_dependencies), requirement.name, requirement.version,
                                                   reason))

    def confirm_installation(self, requirement, missing_dependencies, install_command):
        """
        Ask the operator's permission to install missing system packages.

        :param requirement: A :py:class:`.Requirement` object.
        :param missing_dependencies: A list of strings with missing dependencies.
        :param install_command: A list of strings with the command line needed
                                to install the missing dependencies.
        :raises: :py:exc:`.DependencyInstallationRefused` when the operator refuses.
        """
        terminal = "\n"
        try:
            prompt = "\n  Do you want me to install %s %s? [Y/n] "
            choice = raw_input(prompt % ("this" if len(missing_dependencies) == 1 else "these",
                                         "dependency" if len(missing_dependencies) == 1 else "dependencies"))
            return choice.lower().strip() in ('y', '')
        except (Exception, KeyboardInterrupt):
            # Swallow regular exceptions and KeyBoardInterrupt but not SystemExit.
            terminal = "\n\n"
            return False
        finally:
            sys.stdout.write(terminal)
