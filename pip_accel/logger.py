# Logging for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: May 17, 2013
# URL: https://github.com/paylogic/pip-accel

# Standard library modules.
import logging
import os
import sys

# External dependencies.
from coloredlogs import ColoredStreamHandler

# Initialize the logging subsystem.
logger = logging.getLogger('pip-accel')
logger.setLevel(logging.INFO)
logger.addHandler(ColoredStreamHandler())

# Check if the operator requested verbose output.
if '-v' in sys.argv or 'PIP_ACCEL_VERBOSE' in os.environ:
    logger.setLevel(logging.DEBUG)
