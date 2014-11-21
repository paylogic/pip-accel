# Accelerator for pip, the Python package manager.
#
# Authors:
#  - Adam Feuer <adam@adamfeuer.com>
#  - Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 16, 2014
# URL: https://github.com/paylogic/pip-accel
#
# A word of warning: Do *not* use the cached_property decorator here, because
# it interacts badly with the metaclass magic performed by the base class. I
# wasted about an hour trying to get it to work but it became more and more
# apparent that it was never going to work the way I wanted it to :-)

"""
:py:mod:`pip_accel.caches.s3` - Amazon S3 cache backend
=======================================================

This module implements a cache backend that stores distribution archives in a
user defined `Amazon S3 <http://aws.amazon.com/s3/>`_ bucket. To enable this
backend you need to define the configuration option :py:attr:`.Config.s3_cache_bucket`
and configure your Amazon S3 API credentials (see the readme for
details).

A note about robustness
-----------------------

The Amazon S3 cache backend implemented in :py:mod:`pip_accel.caches.s3` is
specifically written to gracefully disable itself when it encounters known
errors such as:

- The environment variable ``$PIP_ACCEL_S3_BUCKET`` is not set (i.e. the user
  hasn't configured the backend yet).

- The :py:mod:`boto` package is not installed (i.e. the user ran ``pip install
  pip-accel`` instead of ``pip install 'pip-accel[s3]'``).

- The connection to the Amazon S3 API can't be established (e.g. because API
  credentials haven't been correctly configured).

- The connection to the configured Amazon S3 bucket can't be established (e.g.
  because the bucket doesn't exist or the configured credentials don't provide
  access to the bucket).

Optionally if you are using Read Only credentials you can disable put() by setting
the environment variable PIP_ACCEL_S3_READONLY to any value.

Additionally :py:class:`~pip_accel.caches.CacheManager` automatically disables
cache backends that raise exceptions on
:py:class:`~pip_accel.caches.AbstractCacheBackend.get()` and
:py:class:`~pip_accel.caches.AbstractCacheBackend.put()` operations. The end
result is that when the Amazon S3 backend fails you will just revert to using
the cache on the local file system.
"""

# Standard library modules.
import logging
import os

# External dependencies.
from humanfriendly import Timer

# Modules included in our package.
from pip_accel.caches import AbstractCacheBackend
from pip_accel.exceptions import CacheBackendDisabledError, CacheBackendError
from pip_accel.utils import makedirs

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

class S3CacheBackend(AbstractCacheBackend):

    """The S3 cache backend stores distribution archives in a user defined Amazon S3 bucket."""

    PRIORITY = 20

    def get(self, filename):
        """
        Download a cached distribution archive from the configured Amazon S3
        bucket to the local cache.

        :param filename: The filename of the distribution archive (a string).
        :returns: The pathname of a distribution archive on the local file
                  system or ``None``.
        :raises: :py:exc:`.CacheBackendError` when any underlying method fails.
        """
        timer = Timer()
        # Check if the distribution archive is available.
        raw_key = self.get_cache_key(filename)
        logger.info("Checking if distribution archive is available in S3 bucket: %s", raw_key)
        key = self.s3_bucket.get_key(raw_key)
        if key is None:
            logger.debug("Distribution archive is not available in S3 bucket.")
        else:
            # Download the distribution archive to the local binary index.
            # TODO Shouldn't this use LocalCacheBackend.put() instead of
            #      implementing the same steps manually?!
            logger.info("Downloading distribution archive from S3 bucket ..")
            local_file = os.path.join(self.config.binary_cache, filename)
            makedirs(os.path.dirname(local_file))
            key.get_contents_to_filename(local_file)
            logger.debug("Finished downloading distribution archive from S3 bucket in %s.", timer)
            return local_file

    def put(self, filename, handle):
        """
        Upload a distribution archive to the configured Amazon S3 bucket.

        :param filename: The filename of the distribution archive (a string).
        :param handle: A file-like object that provides access to the
                       distribution archive.
        :raises: :py:exc:`.CacheBackendError` when any underlying method fails.
        """

        # Early exit if readonly enabled
        if self.config.s3_readonly:
            logger.info('Skipping S3 Upload, S3 Readonly enabled')
            return

        timer = Timer()
        raw_key = self.get_cache_key(filename)
        logger.info("Uploading distribution archive to S3 bucket: %s", raw_key)
        key = self.boto.s3.key.Key(self.s3_bucket)
        key.key = raw_key
        key.set_contents_from_file(handle)
        logger.info("Finished uploading distribution archive to S3 bucket in %s.", timer)

    @property
    def s3_bucket(self):
        """
        Connect to the user defined Amazon S3 bucket.

        Called on demand by :py:func:`get()` and :py:func:`put()`. Caches its
        return value so that only a single connection is created.

        :returns: A :py:class:`boto.s3.bucket.Bucket` object.
        :raises: :py:exc:`.CacheBackendDisabledError` when the user hasn't
                 defined :py:attr:`.Config.s3_cache_bucket`.
        :raises: :py:exc:`.CacheBackendError` when the connection to the Amazon
                 S3 bucket fails.
        """
        if not hasattr(self, 'cached_bucket'):
            self.ensure_boto_installed()
            if not self.config.s3_cache_bucket:
                raise CacheBackendDisabledError("""
                    To use Amazon S3 as a cache you have to set the environment
                    variable $PIP_ACCEL_S3_BUCKET and configure your Amazon S3
                    API credentials (see the documentation for details).
                """)
            try:
                logger.debug("Connecting to Amazon S3 bucket: %s", self.config.s3_cache_bucket)
                self.cached_bucket = self.connect_to_s3().get_bucket(self.config.s3_cache_bucket)
            except (self.boto.exception.BotoClientError, self.boto.exception.BotoServerError):
                raise CacheBackendError("""
                    Failed to connect to the configured Amazon S3 bucket
                    {bucket}! Are you sure the bucket exists and is accessible
                    using the provided credentials? The Amazon S3 cache backend
                    will be disabled for now.
                """, bucket=repr(self.config.s3_cache_bucket))
        return self.cached_bucket

    def connect_to_s3(self):
        """
        Connect to the Amazon S3 API.

        Called on demand by :py:attr:`s3_bucket`.

        :returns: A :py:class:`boto.s3.connection.S3Connection` object.
        :raises: :py:exc:`.CacheBackendError` when the connection to the Amazon
                 S3 API fails.
        """
        self.ensure_boto_installed()
        try:
            logger.debug("Connecting to Amazon S3 API ..")
            return self.boto.connect_s3()
        except (self.boto.exception.BotoClientError, self.boto.exception.BotoServerError):
            raise CacheBackendError("""
                Failed to connect to the Amazon S3 API! Most likely your
                credentials are not correctly configured. The Amazon S3
                cache backend will be disabled for now.
            """)

    def ensure_boto_installed(self):
        """
        Dynamically import the :py:mod:`boto` module.

        Called on demand by :py:attr:`s3_connection`. This allows references to
        variables defined by the :py:mod:`boto` module without having to import
        Boto everywhere (that would break importing of the
        :py:mod:`pip_accel.caches.s3` module when Boto is not installed).

        :raises: :py:exc:`.CacheBackendError` when :py:mod:`boto` is not installed.
        """
        try:
            logger.debug("Checking if Boto is installed ..")
            self.boto = __import__('boto')
        except ImportError:
            raise CacheBackendError("""
                Boto is required to use Amazon S3 as a cache but it looks like
                Boto is not installed! You can resolve this issue by installing
                pip-accel using the command `pip install pip-accel[s3]'. The
                Amazon S3 cache backend will be disabled for now.
            """)

    def get_cache_key(self, filename):
        """
        Compose an S3 cache key based on :py:attr:`.Config.s3_cache_prefix` and
        the given filename.

        :param filename: The filename of the distribution archive (a string).
        :returns: The cache key for the given filename (a string).
        """
        return '/'.join(filter(None, [self.config.s3_cache_prefix, filename]))
