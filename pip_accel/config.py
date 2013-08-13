# Configuration defaults for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: August 12, 2013
# URL: https://github.com/paylogic/pip-accel

# Standard library modules.
import os
import os.path

# Modules included in our package.
from pip_accel.utils import expand_user

# Select the default location of the download cache and other files based on
# the user running the pip-accel command (root goes to /var/cache/pip-accel,
# otherwise ~/.pip-accel).
if os.getuid() == 0:
    download_cache = '/root/.pip/download-cache'
    pip_accel_cache = '/var/cache/pip-accel'
else:
    download_cache = expand_user('~/.pip/download-cache')
    pip_accel_cache = expand_user('~/.pip-accel')

# Enable overriding the default locations with environment variables.
if 'PIP_DOWNLOAD_CACHE' in os.environ:
    download_cache = expand_user(os.environ['PIP_DOWNLOAD_CACHE'])
if 'PIP_ACCEL_CACHE' in os.environ:
    pip_accel_cache = expand_user(os.environ['PIP_ACCEL_CACHE'])

# Generate the absolute pathnames of the source/binary caches.
source_index = os.path.join(pip_accel_cache, 'sources')
binary_index = os.path.join(pip_accel_cache, 'binaries')
index_version_file = os.path.join(pip_accel_cache, 'version.txt')
