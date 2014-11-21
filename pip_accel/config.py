# Configuration defaults for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 16, 2014
# URL: https://github.com/paylogic/pip-accel

"""
:py:mod:`pip_accel.config` - Configuration handling
===================================================

This module defines the :py:class:`Config` class which is used throughout the
pip accelerator. At runtime an instance of :py:class:`Config` is created and
passed down like this:

.. digraph:: config_dependency_injection

   node [fontsize=10, shape=rect]

   PipAccelerator -> BinaryDistributionManager
   BinaryDistributionManager -> CacheManager
   CacheManager -> LocalCacheBackend
   CacheManager -> S3CacheBackend
   BinaryDistributionManager -> SystemPackageManager

The :py:class:`.PipAccelerator` class receives its configuration object from
its caller. Usually this will be :py:func:`.main()` but when pip-accel is used
as a Python API the person embedding or extending pip-accel is responsible for
providing the configuration object. This is intended as a form of `dependency
injection`_ that enables non-default configurations to be injected into
pip-accel.

.. _dependency injection: http://en.wikipedia.org/wiki/Dependency_injection
"""

# Standard library modules.
import os
import os.path
import sys

# Modules included in our package.
from pip_accel.utils import expand_user

# External dependencies.
from cached_property import cached_property
from humanfriendly import coerce_boolean

class Config(object):

    """Configuration of the pip accelerator."""

    @cached_property
    def cache_format_revision(self):
        """
        The revision of the binary distribution cache format in use (an integer).

        This number is encoded in the directory name of the binary cache so
        that multiple revisions can peacefully coexist. When pip-accel breaks
        backwards compatibility this number is bumped so that pip-accel starts
        using a new directory.
        """
        return 7

    @cached_property
    def download_cache(self):
        """
        The absolute pathname of pip's download cache directory (a string).

        If the environment variable ``$PIP_DOWNLOAD_CACHE`` is set the value of
        this variable is used, otherwise ``~/.pip/download-cache`` is expanded
        using :py:func:`.expand_user()`.
        """
        return expand_user(os.environ.get('PIP_DOWNLOAD_CACHE', '~/.pip/download-cache'))

    @cached_property
    def source_index(self):
        """
        The absolute pathname of pip-accel's source index directory (a string).

        This is the ``sources`` subdirectory of :py:data:`data_directory` so it
        defaults to ``~/.pip-accel/sources`` expanded using
        :py:func:`.expand_user()`.
        """
        return os.path.join(self.data_directory, 'sources')

    @cached_property
    def binary_cache(self):
        """
        The absolute pathname of pip-accel's binary cache directory (a string).

        This is the ``binaries`` subdirectory of :py:data:`data_directory` so
        it defaults to ``~/.pip-accel/binaries`` expanded using
        :py:func:`.expand_user()`.
        """
        return os.path.join(self.data_directory, 'binaries')

    @cached_property
    def data_directory(self):
        """
        The absolute pathname of the directory where pip-accel's data files are stored (a string).

        If the environment variable ``$PIP_ACCEL_CACHE`` is set the value of
        this variable is used, otherwise if the effective user id is 0 (for
        ``root``) the ``/var/cache/pip-accel`` directory is used, otherwise
        ``~/.pip-accel`` is expanded using :py:func:`.expand_user()`.
        """
        default_directory = '/var/cache/pip-accel' if os.getuid() == 0 else '~/.pip-accel'
        return expand_user(os.environ.get('PIP_ACCEL_CACHE', default_directory))

    @cached_property
    def on_debian(self):
        """``True`` if running on a Debian derived system, ``False`` otherwise."""
        return os.path.exists('/etc/debian_version')

    @cached_property
    def install_prefix(self):
        """
        The absolute pathname of the installation prefix to use (a string).

        This property is based on :py:data:`sys.prefix` except that when
        :py:data:`sys.prefix` is ``/usr`` and we're running on a Debian derived
        system ``/usr/local`` is used instead.

        The reason for this is that on Debian derived systems only apt (dpkg)
        should be allowed to touch files in ``/usr/lib/pythonX.Y/dist-packages``
        and ``python setup.py install`` knows this (see the ``posix_local``
        installation scheme in ``/usr/lib/pythonX.Y/sysconfig.py`` on Debian
        derived systems). Because pip-accel replaces ``python setup.py
        install`` it has to replicate this logic. Inferring all of this from
        the :py:mod:`sysconfig` module would be nice but that module wasn't
        available in Python 2.6.
        """
        return '/usr/local' if sys.prefix == '/usr' and self.on_debian else sys.prefix

    @cached_property
    def python_executable(self):
        """The absolute pathname of the Python executable (a string)."""
        return sys.executable or os.path.join(self.install_prefix, 'bin', 'python')

    @cached_property
    def auto_install(self):
        """
        ``True`` if automatic installation of missing system packages is
        enabled, ``False`` otherwise. You can set this configuration option
        using the environment variable ``$PIP_ACCEL_AUTO_INSTALL`` (refer to
        :py:func:`~humanfriendly.coerce_boolean()` for details on how the value
        of the environment variable is interpreted).
        """
        value = os.environ.get('PIP_ACCEL_AUTO_INSTALL')
        return coerce_boolean(value) if value else None

    @cached_property
    def s3_readonly(self):
        """
        This property toggles the cache manager into read only mode for S3. 
        You can set this configuration option using the environment
        variable ``$PIP_ACCEL_S3_READONLY``.

        For details please refer to the :py:mod:`pip_accel.caches.s3` module.
        """
        return os.environ.get('PIP_ACCEL_S3_READONLY')

    @cached_property
    def s3_cache_bucket(self):
        """
        The name of the Amazon S3 bucket where binary distribution archives are
        cached (a string or ``None``). You can set this configuration option
        using the environment variable ``$PIP_ACCEL_S3_BUCKET``.

        For details please refer to the :py:mod:`pip_accel.caches.s3` module.
        """
        return os.environ.get('PIP_ACCEL_S3_BUCKET')

    @cached_property
    def s3_cache_prefix(self):
        """
        The cache prefix for binary distribution archives in the Amazon S3
        bucket (a string).  You can set this configuration option using the
        environment variable ``$PIP_ACCEL_S3_PREFIX``.

        For details please refer to the :py:mod:`pip_accel.caches.s3` module.
        """
        return os.environ.get('PIP_ACCEL_S3_PREFIX', '')
