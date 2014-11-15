# Configuration defaults for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 15, 2014
# URL: https://github.com/paylogic/pip-accel

# Standard library modules.
import os
import os.path

# Modules included in our package.
from pip_accel.utils import expand_user

# The version number of the binary distribution cache format in use. This
# version number is encoded in the directory name of the binary cache so that
# multiple versions can peacefully coexist. When we break backwards
# compatibility we bump this number so that pip-accel starts using a new
# directory.
cache_format_revision = 7

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

# Get the S3 configuration options (if set).
s3_cache_bucket = os.environ.get('PIP_ACCEL_S3_BUCKET')
s3_cache_prefix = os.environ.get('PIP_ACCEL_S3_PREFIX', '')

# Generate the absolute pathnames of the source/binary caches.
source_index = os.path.join(pip_accel_cache, 'sources')
binary_index = os.path.join(pip_accel_cache, 'binaries')
index_version_file = os.path.join(pip_accel_cache, 'version.txt')

# Check if we're running on a Debian derived system.
on_debian = os.path.exists('/etc/debian_version')
