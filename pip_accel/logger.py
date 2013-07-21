# Logging for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: July 21, 2013
# URL: https://github.com/paylogic/pip-accel

"""
Logging for the pip accelerator.
"""

# Standard library modules.
import logging
import os
import sys

# External dependency.
import coloredlogs
coloredlogs.install()

# Initialize the logging subsystem.
logger = logging.getLogger('pip-accel')
logger.setLevel(logging.DEBUG)

# Check if the operator requested verbose output.
if '-v' in sys.argv or 'PIP_ACCEL_VERBOSE' in os.environ:
    logging.getLogger().setLevel(logging.DEBUG)
