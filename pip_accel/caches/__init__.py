# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 15, 2014
# URL: https://github.com/paylogic/pip-accel

"""
:py:mod:`pip_accel.caches` - Support for multiple cache backends
================================================================

This module defines an abstract base class (:py:class:`AbstractCacheBackend`)
to be inherited by custom cache backends in order to easily integrate them in
pip-accel. The cache backends included in pip-accel are built on top of the
same mechanism.

Additionally this module defines :py:class:`CacheManager` which makes it
possible to merge the available cache backends into a single logical cache
which automatically disables backends that report errors.
"""

# Standard library modules.
import hashlib
import logging

# Modules included in our package.
from pip_accel.config import cache_format_revision
from pip_accel.utils import compact, get_python_version

# External dependencies.
from humanfriendly import concatenate, pluralize
from pkg_resources import get_entry_map

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

# Initialize the registry of cache backends.
registered_backends = set()

class CacheBackendMeta(type):

    """Metaclass to intercept cache backend definitions."""

    def __init__(cls, name, bases, dict):
        type.__init__(cls, name, bases, dict)
        registered_backends.add(cls)

class AbstractCacheBackend(object):

    """
    Abstract base class for implementations of pip-accel cache backends.

    Subclasses of this class are used by pip-accel to store Python distribution
    archives in order to accelerate performance and gain independence of
    external systems like PyPI and distribution sites.

    This base class automatically registers subclasses at definition time,
    providing a simple and elegant registration mechanism for custom backends.
    Based on the article `Using Metaclasses to Create Self-Registering Plugins
    <http://effbot.org/zone/metaclass-plugins.htm>`_.
    """

    PRIORITY = 0

    def get(self, filename):
        """
        This method is called by pip-accel before fetching or building a
        distribution archive, in order to check whether a previously cached
        distribution archive is available for re-use.

        :param filename: The expected filename of the distribution archive (a
                         string).
        :returns: The absolute pathname of a local file or ``None`` when the
                  distribution archive hasn't been cached.
        """
        raise NotImplementedError()

    def put(self, filename, handle):
        """
        This method is called by pip-accel after fetching or building a
        distribution archive, in order to cache the distribution archive.

        :param filename: The filename of the distribution archive (a string).
        :param handle: A file-like object that provides access to the
                       distribution archive.
        """
        raise NotImplementedError()

    def __repr__(self):
        return self.__class__.__name__

# Obscure syntax gymnastics to define a class with a metaclass whose
# definition is compatible with Python 2.x as well as Python 3.x.
# See also: https://wiki.python.org/moin/PortingToPy3k/BilingualQuickRef#metaclasses
AbstractCacheBackend = CacheBackendMeta('AbstractCacheBackend',
                                        AbstractCacheBackend.__bases__,
                                        dict(AbstractCacheBackend.__dict__))

class CacheManager(object):

    """
    Interface to treat multiple cache backends as a single one.

    The cache manager automatically disables cache backends that raise
    exceptions on ``get()`` and ``put()`` operations.
    """

    def __init__(self):
        """
        Initialize a cache manager.

        Automatically initializes instances of all registered cache backends
        based on setuptools' support for entry points which makes it possible
        for external Python packages to register additional cache backends
        without any modifications to pip-accel.
        """
        for entry_point in get_entry_map('pip-accel', 'pip_accel.cache_backends').values():
            logger.debug("Importing cache backend: %s", entry_point.module_name)
            __import__(entry_point.module_name)
        # Initialize instances of all registered cache backends (sorted by
        # priority so that e.g. the local file system is checked before S3).
        self.backends = sorted((b() for b in registered_backends if b != AbstractCacheBackend),
                               key=lambda b: b.PRIORITY)
        logger.debug("Initialized %s: %s",
                     pluralize(len(self.backends), "cache backend", "cache backends"),
                     concatenate(map(repr, self.backends)))

    def get(self, package, version, url):
        """
        Get a distribution archive from any of the available caches.

        :param package: The name of the package (a string).
        :param version: The version of the package (a string).
        :param url: The URL of the requirement (a string or ``None``).
        :returns: The absolute pathname of a local file or ``None`` when the
                  distribution archive is missing from all available caches.
        """
        filename = self.generate_filename(package, version, url)
        for backend in list(self.backends):
            try:
                pathname = backend.get(filename)
                if pathname is not None:
                    return pathname
            except CacheBackendDisabledError as e:
                logger.debug("Disabling %s because it requires configuration (%s).", backend, e)
                self.backends.remove(backend)
            except Exception as e:
                logger.exception("Disabling %s because it failed: %s", backend, e)
                self.backends.remove(backend)

    def put(self, package, version, url, handle):
        """
        Store a distribution archive in all of the available caches.

        :param package: The name of the package (a string).
        :param version: The version of the package (a string).
        :param url: The URL of the requirement (a string or ``None``).
        :param handle: A file-like object that provides access to the
                       distribution archive.
        """
        filename = self.generate_filename(package, version, url)
        for backend in list(self.backends):
            handle.seek(0)
            try:
                backend.put(filename, handle)
            except CacheBackendDisabledError as e:
                logger.debug("Disabling %s because it requires configuration (%s).", backend, e)
                self.backends.remove(backend)
            except Exception as e:
                logger.exception("Disabling %s because it failed: %s", backend, e)
                self.backends.remove(backend)

    def generate_filename(self, package, version, url=None):
        """
        Generate a distribution archive filename for a package.

        :param package: The name of the package (a string).
        :param version: The version of the package (a string).
        :param url: The URL of the requirement (a string or ``None``).
        :returns: The filename of the distribution archive (a string)
                  including a single leading directory component to indicate
                  the cache format revision.
        """
        if url and url.startswith('file://'):
            # Ignore the URL if it is a file:// URL because those frequently
            # point to temporary directories whose pathnames change with every
            # invocation of pip-accel. If we would include the file:// URL in
            # the cache key we would be generating a unique cache key on
            # every run (not good for performance ;-).
            url = None
        tag = hashlib.sha1(str(version + url).encode()).hexdigest() if url else version
        return 'v%i/%s:%s:%s.tar.gz' % (cache_format_revision, package, tag, get_python_version())

class CacheBackendError(Exception):

    """Exception raised by cache backends when they fail in a controlled manner."""

    def __init__(self, *args, **kw):
        """Takes the same arguments as :py:func:`pip_accel.utils.compact()`."""
        super(CacheBackendError, self).__init__(compact(*args, **kw))

class CacheBackendDisabledError(Exception):
    """Exception raised by cache backends when they require configuration."""
