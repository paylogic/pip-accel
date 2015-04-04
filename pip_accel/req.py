# Simple wrapper for pip and pkg_resources Requirement objects.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: April 4, 2015
# URL: https://github.com/paylogic/pip-accel

"""
:py:mod:`pip_accel.req` - Requirement objects
=============================================

After downloading the specified requirement(s) pip reports a "requirement set"
to pip-accel. In the past pip-accel would summarize this requirement set into a
list of tuples, where each tuple would contain a requirement's project name,
version and source directory (basically only the information required by
pip-accel remained).

Recently I've started using pip-accel as a library in another project I'm
working on (not yet public) and in that project I am very interested in whether
a given requirement is a direct or transitive requirement. Unfortunately
pip-accel did not preserve this information.

That's when I decided that next to pip's :py:class:`pip.req.InstallRequirement`
and setuptools' :py:class:`pkg_resources.Requirement` I would introduce yet
another type of requirement object... It's basically just a summary of the
other two types of requirement objects and it also provides access to the
original requirement objects (for those who are interested; the interfaces are
basically undocumented AFAIK).
"""

# Standard library modules.
import glob
import os

# Modules included in our package.
from pip_accel.exceptions import UnknownDistributionFormat
from pip._vendor.pkg_resources import find_distributions

# External dependencies.
from cached_property import cached_property
from pip.req import InstallRequirement

class Requirement(object):

    """Simple wrapper for the requirement objects defined by pip and setuptools."""

    def __init__(self, requirement):
        """
        Initialize a requirement object.

        :param requirement: A :py:class:`pip.req.InstallRequirement` object.
        """
        self.pip_requirement = requirement
        self.setuptools_requirement = requirement.req
        if self.name == 'paver' and 0:
            import ipdb
            ipdb.set_trace()

    @cached_property
    def name(self):
        """
        The name of the Python package (a string). This is the name used to
        register a package on PyPI and the name reported by commands like ``pip
        freeze``. Based on :py:attr:`pkg_resources.Requirement.project_name`.
        """
        return self.setuptools_requirement.project_name

    @cached_property
    def version(self):
        """
        The version of the package that ``pip`` wants to install based on the
        command line options that were given to ``pip`` (a string).
        """
        if self.is_wheel:
            return self.wheel_metadata.version
        else:
            return self.sdist_metadata['Version']

    @cached_property
    def url(self):
        """
        The URL of the package. Based on :py:attr:`pip.req.InstallRequirement.url`.
        """
        return self.pip_requirement.url

    @cached_property
    def source_directory(self):
        """
        The pathname of the directory containing the unpacked source
        distribution. This is the directory that contains a ``setup.py``
        script. Based on :py:attr:`pip.req.InstallRequirement.source_dir`.
        """
        return self.pip_requirement.source_dir

    @cached_property
    def is_wheel(self):
        """
        ```True`` when the requirement is a wheel, ``False`` otherwise.

        .. note:: To my surprise it seems to be non-trivial to determine
                  whether a given :py:class:`pip.req.InstallRequirement` object
                  produced by pip's internal Python API concerns a source
                  distribution or a wheel distribution.

                  There's a :py:class:`pip.req.InstallRequirement.is_wheel`
                  property but I'm currently looking at a wheel distribution
                  whose ``is_wheel`` property returns ``None``, apparently
                  because the requirement's ``url`` property is also ``None``.

                  Whether this is an obscure implementation detail of pip or
                  caused by the way pip-accel invokes pip, I really can't tell
                  (yet).
        """
        probably_sdist = os.path.isfile(os.path.join(self.source_directory, 'setup.py'))
        probably_wheel = len(glob.glob(os.path.join(self.source_directory, '*.dist-info', 'WHEEL'))) > 0
        if probably_wheel and not probably_sdist:
            return True
        elif probably_sdist and not probably_wheel:
            return False
        elif probably_sdist and probably_wheel:
            raise UnknownDistributionFormat("""
                The unpacked distribution of {requirement} in {directory} looks
                like a source distribution and a wheel distribution, I'm
                confused!
            """, requirement=self.setuptools_requirement,
                 directory=self.source_directory)
        else:
            raise UnknownDistributionFormat("""
                The unpacked distribution of {requirement} in {directory}
                doesn't look like a source distribution and also doesn't look
                like a wheel distribution, I'm confused!
            """, requirement=self.setuptools_requirement,
                 directory=self.source_directory)

    @cached_property
    def is_installed(self):
        """
        ``True`` when the requirement is already installed, ``False``
        otherwise.
        """
        # Gotcha: We need to call check_if_exists() here because pip-accel uses
        # pip's --download=... option which automatically enables the
        # --ignore-installed option (this is documented behavior of pip).
        self.pip_requirement.check_if_exists()
        return bool(self.pip_requirement.satisfied_by)

    @cached_property
    def is_transitive(self):
        """
        ``True`` when the requirement is a transitive dependency (a dependency
        of a dependency) or ``False`` when the requirement is a direct
        dependency (specified on pip's command line or in a
        ``requirements.txt`` file). Based on
        :py:attr:`pip.req.InstallRequirement.comes_from`.
        """
        return isinstance(self.pip_requirement.comes_from, InstallRequirement)

    @cached_property
    def is_direct(self):
        """
        The opposite of :py:attr:`Requirement.is_transitive`.
        """
        return not self.is_transitive

    @cached_property
    def is_editable(self):
        """
        ``True`` when the requirement is to be installed in editable mode (i.e.
        setuptools "develop mode"). Based on
        :py:attr:`pip.req.InstallRequirement.editable`.
        """
        return self.pip_requirement.editable

    @cached_property
    def sdist_metadata(self):
        """
        Get the distribution metadata of an unpacked source distribution.
        """
        if self.is_wheel:
            raise TypeError("Requirement is not a source distribution!")
        return self.pip_requirement.pkg_info()

    @cached_property
    def wheel_metadata(self):
        """
        Get the distribution metadata of an unpacked wheel distribution.
        """
        if not self.is_wheel:
            raise TypeError("Requirement is not a wheel distribution!")
        try:
            return next(find_distributions(self.source_directory))
        except StopIteration:
            raw_input(" --> Please inspect the %s wheel distribution's contents, press <Enter> when done .. " % self.source_directory)
            raise Exception("Wheel metadata missing")

    def __str__(self):
        """
        Render a human friendly string describing the requirement.
        """
        return "%s (%s)" % (self.name, self.version)
