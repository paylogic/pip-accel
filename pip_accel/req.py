# Simple wrapper for pip and pkg_resources Requirement objects.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 16, 2014
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
        # In pip-accel 0.10.4 and earlier the list of requirements returned by
        # unpack_source_dists() contained tuples in the following format.
        self.old_interface = (self.name, self.version, self.source_directory)

    def __iter__(self):
        """
        Implemented so that :py:class:`Requirement` objects can be used as a
        (project_name, installed_version, source_dir) tuple, for compatibility
        with callers of pip-accel 0.10.4 and earlier.
        """
        return iter(self.old_interface)

    def __getitem__(self, index):
        """
        Implemented so that :py:class:`Requirement` objects can be used as a
        (project_name, installed_version, source_dir) tuple, for compatibility
        with callers of pip-accel 0.10.4 and earlier.
        """
        return self.old_interface[index]

    @property
    def name(self):
        """
        The name of the Python package (a string). This is the name used to
        register a package on PyPI and the name reported by commands like ``pip
        freeze``. Based on :py:attr:`pkg_resources.Requirement.project_name`.
        """
        return self.setuptools_requirement.project_name

    @property
    def version(self):
        """
        The version of the package that ``pip`` wants to install based on the
        command line options that were given to ``pip`` (a string). Based on
        :py:attr:`pip.req.InstallRequirement.installed_version`.
        """
        return self.pip_requirement.installed_version

    @property
    def url(self):
        """
        The URL of the package. Based on :py:attr:`pip.req.InstallRequirement.url`.
        """
        return self.pip_requirement.url

    @property
    def source_directory(self):
        """
        The pathname of the directory containing the unpacked source
        distribution. This is the directory that contains a ``setup.py``
        script. Based on :py:attr:`pip.req.InstallRequirement.source_dir`.
        """
        return self.pip_requirement.source_dir

    @property
    def is_installed(self):
        """
        ``True`` when the requirement is already installed, ``False``
        otherwise.
        """
        return bool(self.pip_requirement.satisfied_by)

    @property
    def is_transitive(self):
        """
        ``True`` when the requirement is a transitive dependency (a dependency
        of a dependency) or ``False`` when the requirement is a direct
        dependency (specified on pip's command line or in a
        ``requirements.txt`` file). Based on
        :py:attr:`pip.req.InstallRequirement.comes_from`.
        """
        return isinstance(self.pip_requirement.comes_from, InstallRequirement)

    @property
    def is_direct(self):
        """
        The opposite of :py:attr:`Requirement.is_transitive`.
        """
        return not self.is_transitive

    @property
    def is_editable(self):
        """
        ``True`` when the requirement is to be installed in editable mode (i.e.
        setuptools "develop mode"). Based on
        :py:attr:`pip.req.InstallRequirement.editable`.
        """
        return self.pip_requirement.editable
