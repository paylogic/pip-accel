# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: January 10, 2016
# URL: https://github.com/paylogic/pip-accel

"""
Configuration handling for `pip-accel`.

This module defines the :class:`Config` class which is used throughout the
pip accelerator. At runtime an instance of :class:`Config` is created and
passed down like this:

.. digraph:: config_dependency_injection

   node [fontsize=10, shape=rect]

   PipAccelerator -> BinaryDistributionManager
   BinaryDistributionManager -> CacheManager
   CacheManager -> LocalCacheBackend
   CacheManager -> S3CacheBackend
   BinaryDistributionManager -> SystemPackageManager

The :class:`.PipAccelerator` class receives its configuration object from
its caller. Usually this will be :func:`.main()` but when pip-accel is used
as a Python API the person embedding or extending pip-accel is responsible for
providing the configuration object. This is intended as a form of `dependency
injection`_ that enables non-default configurations to be injected into
pip-accel.

Support for runtime configuration
---------------------------------

The properties of the :class:`Config` class can be set at runtime using
regular attribute assignment syntax. This overrides the default values of the
properties (whether based on environment variables, configuration files or hard
coded defaults).

Support for configuration files
-------------------------------

You can use a configuration file to permanently configure certain options of
pip-accel. If ``/etc/pip-accel.conf`` and/or ``~/.pip-accel/pip-accel.conf``
exist they are automatically loaded. You can also set the environment variable
``$PIP_ACCEL_CONFIG`` to load a configuration file in a non-default location.
If all three files exist the system wide file is loaded first, then the user
specific file is loaded and then the file set by the environment variable is
loaded (duplicate settings are overridden by the configuration file that's
loaded last).

Here is an example of the available options:

        .. code-block:: ini

           [pip-accel]
           auto-install = yes
           max-retries = 3
           data-directory = ~/.pip-accel
           s3-bucket = my-shared-pip-accel-binary-cache
           s3-prefix = ubuntu-trusty-amd64
           s3-readonly = yes

Note that the configuration options shown above are just examples, they are not
meant to represent the configuration defaults.

----

.. _dependency injection: http://en.wikipedia.org/wiki/Dependency_injection
"""

# Standard library modules.
import logging
import os
import os.path
import sys

# Modules included in our package.
from pip_accel.compat import configparser
from pip_accel.utils import is_root, expand_path

# External dependencies.
from coloredlogs import DEFAULT_LOG_FORMAT
from cached_property import cached_property
from humanfriendly import coerce_boolean, parse_path

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

# The locations of the user specific and system wide configuration files.
LOCAL_CONFIG = '~/.pip-accel/pip-accel.conf'
GLOBAL_CONFIG = '/etc/pip-accel.conf'


class Config(object):

    """Configuration of the pip accelerator."""

    def __init__(self, load_configuration_files=True, load_environment_variables=True):
        """
        Initialize the configuration of the pip accelerator.

        :param load_configuration_files: If this is :data:`True` (the default) then
                                         configuration files in known locations
                                         are automatically loaded.
        :param load_environment_variables: If this is :data:`True` (the default) then
                                           environment variables are used to
                                           initialize the configuration.
        """
        self.overrides = {}
        self.configuration = {}
        self.environment = os.environ if load_environment_variables else {}
        if load_configuration_files:
            for filename in self.available_configuration_files:
                self.load_configuration_file(filename)

    @cached_property
    def available_configuration_files(self):
        """A list of strings with the absolute pathnames of the available configuration files."""
        known_files = [GLOBAL_CONFIG, LOCAL_CONFIG, self.environment.get('PIP_ACCEL_CONFIG')]
        absolute_paths = [parse_path(pathname) for pathname in known_files if pathname]
        return [pathname for pathname in absolute_paths if os.path.isfile(pathname)]

    def load_configuration_file(self, configuration_file):
        """
        Load configuration defaults from a configuration file.

        :param configuration_file: The pathname of a configuration file (a
                                   string).
        :raises: :exc:`Exception` when the configuration file cannot be
                 loaded.
        """
        configuration_file = parse_path(configuration_file)
        logger.debug("Loading configuration file: %s", configuration_file)
        parser = configparser.RawConfigParser()
        files_loaded = parser.read(configuration_file)
        if len(files_loaded) != 1:
            msg = "Failed to load configuration file! (%s)"
            raise Exception(msg % configuration_file)
        elif not parser.has_section('pip-accel'):
            msg = "Missing 'pip-accel' section in configuration file! (%s)"
            raise Exception(msg % configuration_file)
        else:
            self.configuration.update(parser.items('pip-accel'))

    def __setattr__(self, name, value):
        """
        Override the value of a property at runtime.

        :param name: The name of the property to override (a string).
        :param value: The overridden value of the property.
        """
        attribute = getattr(self, name, None)
        if isinstance(attribute, (property, cached_property)):
            self.overrides[name] = value
        else:
            self.__dict__[name] = value

    def get(self, property_name=None, environment_variable=None, configuration_option=None, default=None):
        """
        Internal shortcut to get a configuration option's value.

        :param property_name: The name of the property that users can set on
                              the :class:`Config` class (a string).
        :param environment_variable: The name of the environment variable (a
                                     string).
        :param configuration_option: The name of the option in the
                                     configuration file (a string).
        :param default: The default value.
        :returns: The value of the environment variable or configuration file
                  option or the default value.
        """
        if self.overrides.get(property_name) is not None:
            return self.overrides[property_name]
        elif environment_variable and self.environment.get(environment_variable):
            return self.environment[environment_variable]
        elif self.configuration.get(configuration_option) is not None:
            return self.configuration[configuration_option]
        else:
            return default

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
    def source_index(self):
        """
        The absolute pathname of pip-accel's source index directory (a string).

        This is the ``sources`` subdirectory of :data:`data_directory`.
        """
        return self.get(property_name='source_index',
                        default=os.path.join(self.data_directory, 'sources'))

    @cached_property
    def binary_cache(self):
        """
        The absolute pathname of pip-accel's binary cache directory (a string).

        This is the ``binaries`` subdirectory of :data:`data_directory`.
        """
        return self.get(property_name='binary_cache',
                        default=os.path.join(self.data_directory, 'binaries'))

    @cached_property
    def eggs_cache(self):
        """
        The absolute pathname of pip-accel's eggs cache directory (a string).

        This is the ``eggs`` subdirectory of :data:`data_directory`. It is used
        to cache setup requirements which avoids continuous rebuilding of setup
        requirements.
        """
        return self.get(property_name='eggs_cache',
                        default=os.path.join(self.data_directory, 'eggs'))

    @cached_property
    def data_directory(self):
        """
        The absolute pathname of the directory where pip-accel's data files are stored (a string).

        - Environment variable: ``$PIP_ACCEL_CACHE``
        - Configuration option: ``data-directory``
        - Default: ``/var/cache/pip-accel`` if running as ``root``, ``~/.pip-accel`` otherwise
        """
        return expand_path(self.get(property_name='data_directory',
                                    environment_variable='PIP_ACCEL_CACHE',
                                    configuration_option='data-directory',
                                    default='/var/cache/pip-accel' if is_root() else '~/.pip-accel'))

    @cached_property
    def on_debian(self):
        """:data:`True` if running on a Debian derived system, :data:`False` otherwise."""
        return self.get(property_name='on_debian',
                        default=os.path.exists('/etc/debian_version'))

    @cached_property
    def install_prefix(self):
        """
        The absolute pathname of the installation prefix to use (a string).

        This property is based on :data:`sys.prefix` except that when
        :data:`sys.prefix` is ``/usr`` and we're running on a Debian derived
        system ``/usr/local`` is used instead.

        The reason for this is that on Debian derived systems only apt (dpkg)
        should be allowed to touch files in ``/usr/lib/pythonX.Y/dist-packages``
        and ``python setup.py install`` knows this (see the ``posix_local``
        installation scheme in ``/usr/lib/pythonX.Y/sysconfig.py`` on Debian
        derived systems). Because pip-accel replaces ``python setup.py
        install`` it has to replicate this logic. Inferring all of this from
        the :mod:`sysconfig` module would be nice but that module wasn't
        available in Python 2.6.
        """
        return self.get(property_name='install_prefix',
                        default='/usr/local' if sys.prefix == '/usr' and self.on_debian else sys.prefix)

    @cached_property
    def python_executable(self):
        """The absolute pathname of the Python executable (a string)."""
        return self.get(property_name='python_executable',
                        default=sys.executable or os.path.join(self.install_prefix, 'bin', 'python'))

    @cached_property
    def auto_install(self):
        """
        Whether automatic installation of missing system packages is enabled.

        :data:`True` if automatic installation of missing system packages is
        enabled, :data:`False` if it is disabled, :data:`None` otherwise (in this case
        the user will be prompted at the appropriate time).

        - Environment variable: ``$PIP_ACCEL_AUTO_INSTALL`` (refer to
          :func:`~humanfriendly.coerce_boolean()` for details on how the
          value of the environment variable is interpreted)
        - Configuration option: ``auto-install`` (also parsed using
          :func:`~humanfriendly.coerce_boolean()`)
        - Default: :data:`None`
        """
        value = self.get(property_name='auto_install',
                         environment_variable='PIP_ACCEL_AUTO_INSTALL',
                         configuration_option='auto-install')
        if value is not None:
            return coerce_boolean(value)

    @cached_property
    def log_format(self):
        """
        The format of log messages written to the terminal.

        - Environment variable: ``$PIP_ACCEL_LOG_FORMAT``
        - Configuration option: ``log-format``
        - Default: :data:`~coloredlogs.DEFAULT_LOG_FORMAT`
        """
        return self.get(property_name='log_format',
                        environment_variable='PIP_ACCEL_LOG_FORMAT',
                        configuration_option='log-format',
                        default=DEFAULT_LOG_FORMAT)

    @cached_property
    def log_verbosity(self):
        """
        The verbosity of log messages written to the terminal.

        - Environment variable: ``$PIP_ACCEL_LOG_VERBOSITY``
        - Configuration option: ``log-verbosity``
        - Default: 'INFO' (a string).
        """
        return self.get(property_name='log_verbosity',
                        environment_variable='PIP_ACCEL_LOG_VERBOSITY',
                        configuration_option='log-verbosity',
                        default='INFO')

    @cached_property
    def max_retries(self):
        """
        The number of times to retry ``pip install --download`` if it fails.

        - Environment variable: ``$PIP_ACCEL_MAX_RETRIES``
        - Configuration option: ``max-retries``
        - Default: ``3``
        """
        value = self.get(property_name='max_retries',
                         environment_variable='PIP_ACCEL_MAX_RETRIES',
                         configuration_option='max-retries')
        try:
            n = int(value)
            if n >= 0:
                return n
        except:
            return 3

    @cached_property
    def trust_mod_times(self):
        """
        Whether to trust file modification times for cache invalidation.

        - Environment variable: ``$PIP_ACCEL_TRUST_MOD_TIMES``
        - Configuration option: ``trust-mod-times``
        - Default: :data:`True` unless the AppVeyor_ continuous integration
                   environment is detected (see `issue 62`_).

        .. _AppVeyor: http://www.appveyor.com
        .. _issue 62: https://github.com/paylogic/pip-accel/issues/62
        """
        on_appveyor = coerce_boolean(os.environ.get('APPVEYOR', 'False'))
        return coerce_boolean(self.get(property_name='trust_mod_times',
                                       environment_variable='PIP_ACCEL_TRUST_MOD_TIMES',
                                       configuration_option='trust-mod-times',
                                       default=(not on_appveyor)))

    @cached_property
    def s3_cache_url(self):
        """
        The URL of the Amazon S3 API endpoint to use.

        By default this points to the official Amazon S3 API endpoint. You can
        change this option if you're running a local Amazon S3 compatible
        storage service that you want pip-accel to use.

        - Environment variable: ``$PIP_ACCEL_S3_URL``
        - Configuration option: ``s3-url``
        - Default: ``https://s3.amazonaws.com``

        For details please refer to the :mod:`pip_accel.caches.s3` module.
        """
        return self.get(property_name='s3_cache_url',
                        environment_variable='PIP_ACCEL_S3_URL',
                        configuration_option='s3-url',
                        default='https://s3.amazonaws.com')

    @cached_property
    def s3_cache_bucket(self):
        """
        Name of Amazon S3 bucket where binary distributions are cached (a string or :data:`None`).

        - Environment variable: ``$PIP_ACCEL_S3_BUCKET``
        - Configuration option: ``s3-bucket``
        - Default: :data:`None`

        For details please refer to the :mod:`pip_accel.caches.s3` module.
        """
        return self.get(property_name='s3_cache_bucket',
                        environment_variable='PIP_ACCEL_S3_BUCKET',
                        configuration_option='s3-bucket')

    @cached_property
    def s3_cache_create_bucket(self):
        """
        Whether to automatically create the Amazon S3 bucket when it's missing.

        - Environment variable: ``$PIP_ACCEL_S3_CREATE_BUCKET``
        - Configuration option: ``s3-create-bucket``
        - Default: :data:`False`

        For details please refer to the :mod:`pip_accel.caches.s3` module.
        """
        return coerce_boolean(self.get(property_name='s3_cache_create_bucket',
                                       environment_variable='PIP_ACCEL_S3_CREATE_BUCKET',
                                       configuration_option='s3-create-bucket',
                                       default=False))

    @cached_property
    def s3_cache_prefix(self):
        """
        Cache prefix for binary distribution archives in Amazon S3 bucket (a string or :data:`None`).

        - Environment variable: ``$PIP_ACCEL_S3_PREFIX``
        - Configuration option: ``s3-prefix``
        - Default: :data:`None`

        For details please refer to the :mod:`pip_accel.caches.s3` module.
        """
        return self.get(property_name='s3_cache_prefix',
                        environment_variable='PIP_ACCEL_S3_PREFIX',
                        configuration_option='s3-prefix')

    @cached_property
    def s3_cache_readonly(self):
        """
        Whether the Amazon S3 bucket is considered read only.

        If this is :data:`True` then the Amazon S3 bucket will only be used for
        :class:`~pip_accel.caches.s3.S3CacheBackend.get()` operations (all
        :class:`~pip_accel.caches.s3.S3CacheBackend.put()` operations will
        be disabled).

        - Environment variable: ``$PIP_ACCEL_S3_READONLY`` (refer to
          :func:`~humanfriendly.coerce_boolean()` for details on how the
          value of the environment variable is interpreted)
        - Configuration option: ``s3-readonly`` (also parsed using
          :func:`~humanfriendly.coerce_boolean()`)
        - Default: :data:`False`

        For details please refer to the :mod:`pip_accel.caches.s3` module.
        """
        return coerce_boolean(self.get(property_name='s3_cache_readonly',
                                       environment_variable='PIP_ACCEL_S3_READONLY',
                                       configuration_option='s3-readonly',
                                       default=False))

    @cached_property
    def s3_cache_timeout(self):
        """
        The socket timeout in seconds for connections to Amazon S3 (an integer).

        This value is injected into Boto's configuration to override the
        default socket timeout used for connections to Amazon S3.

        - Environment variable: ``$PIP_ACCEL_S3_TIMEOUT``
        - Configuration option: ``s3-timeout``
        - Default: ``60`` (`Boto's default`_)

        .. _Boto's default: http://boto.readthedocs.org/en/latest/boto_config_tut.html
        """
        value = self.get(property_name='s3_cache_timeout',
                         environment_variable='PIP_ACCEL_S3_TIMEOUT',
                         configuration_option='s3-timeout')
        try:
            n = int(value)
            if n >= 0:
                return n
        except:
            return 60

    @cached_property
    def s3_cache_retries(self):
        """
        The number of times to retry failed requests to Amazon S3 (an integer).

        This value is injected into Boto's configuration to override the
        default number of times to retry failed requests to Amazon S3.

        - Environment variable: ``$PIP_ACCEL_S3_RETRIES``
        - Configuration option: ``s3-retries``
        - Default: ``5`` (`Boto's default`_)
        """
        value = self.get(property_name='s3_cache_retries',
                         environment_variable='PIP_ACCEL_S3_RETRIES',
                         configuration_option='s3-retries')
        try:
            n = int(value)
            if n >= 0:
                return n
        except:
            return 5
