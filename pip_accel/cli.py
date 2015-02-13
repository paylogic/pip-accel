# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: February 13, 2015
# URL: https://github.com/paylogic/pip-accel

"""
:py:mod:`pip_accel.cli` - Command line interface for the ``pip-accel`` program
==============================================================================
"""

# Standard library modules.
import logging
import os
import sys
import textwrap

# Modules included in our package.
from pip_accel import PipAccelerator
from pip_accel.config import Config
from pip_accel.exceptions import NothingToDoError

# External dependencies.
import coloredlogs

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

def main():
    """The command line interface for the ``pip-accel`` program."""
    arguments = sys.argv[1:]
    # If no arguments are given, the help text of pip-accel is printed.
    if not arguments:
        usage()
        sys.exit(0)
    # If no install subcommand is given we pass the command line straight
    # to pip without any changes and exit immediately afterwards.
    if 'install' not in arguments:
        # This will not return.
        os.execvp('pip', ['pip'] + arguments)
    else:
        arguments = [arg for arg in arguments if arg != 'install']
    # Initialize logging output.
    coloredlogs.install()
    # Adjust verbosity based on -v, -q, --verbose, --quiet options.
    for argument in list(arguments):
        if match_option(argument, '-v', '--verbose'):
            coloredlogs.increase_verbosity()
        elif match_option(argument, '-q', '--quiet'):
            coloredlogs.decrease_verbosity()
    # Perform the requested action(s).
    try:
        accelerator = PipAccelerator(Config())
        accelerator.install_from_arguments(arguments)
    except NothingToDoError as e:
        # Don't print a traceback for this (it's not very user friendly) and
        # exit with status zero to stay compatible with pip. For more details
        # please refer to https://github.com/paylogic/pip-accel/issues/47.
        logger.warning("%s", e)
        sys.exit(0)
    except Exception:
        logger.exception("Caught unhandled exception!")
        sys.exit(1)

def usage():
    """Print a usage message to the terminal."""
    print(textwrap.dedent("""
        Usage: pip-accel [PIP_ARGS]

        The pip-accel program is a wrapper for pip, the Python package manager. It
        accelerates the usage of pip to initialize Python virtual environments given
        one or more requirements files. The pip-accel command supports all subcommands
        and options supported by pip, however the only added value is in the "pip
        install" subcommand.

        For more information please refer to the GitHub project page
        at https://github.com/paylogic/pip-accel
    """).strip())

def match_option(argument, short_option, long_option):
    """
    Match a command line argument against a short and long option.

    :param argument: The command line argument (a string).
    :param short_option: The short option (a string).
    :param long_option: The long option (a string).
    :returns: ``True`` if the argument matches, ``False`` otherwise.
    """
    return short_option[1] in argument[1:] if is_short_option(argument) else argument == long_option

def is_short_option(argument):
    """
    Check if a command line argument is a short option.

    :param argument: The command line argument (a string).
    :returns: ``True`` if the argument is a short option, ``False`` otherwise.
    """
    return len(argument) >= 2 and argument[0] == '-' and argument[1] != '-'
