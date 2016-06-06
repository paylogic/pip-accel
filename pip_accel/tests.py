# Tests for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: June 6, 2016
# URL: https://github.com/paylogic/pip-accel

"""
Test suite for the pip accelerator.

I've decided to include the test suite in the online documentation of the pip
accelerator and I realize this may be somewhat unconventional... My reason for
this is to enforce the same level of code quality (which obviously includes
documentation) for the test suite that I require from myself and contributors
for the other parts of the pip-accel project (and my other open source
projects).

A second and more subtle reason is because of a tendency I've noticed in a lot
of my projects: Useful "miscellaneous" functionality is born in test suites and
eventually makes its way to the public API of the project in question. By
writing documentation up front I'm saving my future self time. That may sound
silly, but consider that writing documentation is a lot easier when you *don't*
have to do so retroactively.
"""

# Standard library modules.
import fnmatch
import glob
import json
import logging
import operator
import os
import platform
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

# External dependencies.
import coloredlogs
from cached_property import cached_property
from humanfriendly import coerce_boolean, compact, concatenate, dedent
from pip.commands.install import InstallCommand
from pip.exceptions import DistributionNotFound

# Modules included in our package.
from pip_accel import PatchedAttribute, PipAccelerator
from pip_accel.cli import main
from pip_accel.compat import WINDOWS, StringIO
from pip_accel.config import Config
from pip_accel.deps import DependencyInstallationRefused, SystemPackageManager
from pip_accel.exceptions import EnvironmentMismatchError
from pip_accel.req import escape_name
from pip_accel.utils import create_file_url, makedirs, requirement_is_installed, uninstall

# Test dependencies.
from executor import CommandNotFound, execute, which
from executor.ssh.server import EphemeralTCPServer
from portalocker import Lock

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

# A list of temporary directories created by the test suite.
TEMPORARY_DIRECTORIES = []


def setUpModule():
    """Initialize verbose logging to the terminal."""
    coloredlogs.install(level=logging.INFO)


def tearDownModule():
    """Cleanup any temporary directories created by :func:`create_temporary_directory()`."""
    while TEMPORARY_DIRECTORIES:
        directory = TEMPORARY_DIRECTORIES.pop(0)
        logger.debug("Cleaning up temporary directory: %s", directory)
        try:
            shutil.rmtree(directory, onerror=delete_read_only)
        except Exception:
            logger.exception("Failed to cleanup temporary directory!")


def delete_read_only(action, pathname, exc_info):
    """
    Force removal of read only files on Windows.

    Based on http://stackoverflow.com/a/21263493/788200.
    Needed because of https://ci.appveyor.com/project/xolox/pip-accel/build/1.0.24.
    """
    if action in (os.remove, os.rmdir):
        # Mark the directory or file as writable.
        os.chmod(pathname, stat.S_IWUSR)
        # Retry the action.
        action(pathname)


def create_temporary_directory(**kw):
    """
    Create a temporary directory that will be cleaned up when the test suite ends.

    :param kw: Any keyword arguments are passed on to
               :func:`tempfile.mkdtemp()`.
    :returns: The pathname of a directory created using
              :func:`tempfile.mkdtemp()` (a string).
    """
    directory = tempfile.mkdtemp(**kw)
    logger.debug("Created temporary directory: %s", directory)
    TEMPORARY_DIRECTORIES.append(directory)
    return directory


class PipAccelTestCase(unittest.TestCase):

    """Container for the tests in the pip-accel test suite."""

    def setUp(self):
        """Reset logging verbosity before each test."""
        coloredlogs.set_level(logging.INFO)

    def skipTest(self, text, *args, **kw):
        """
        Enable backwards compatible "marking of tests to skip".

        By calling this method from a return statement in the test to be
        skipped the test can be marked as skipped when possible, without
        breaking the test suite when unittest.TestCase.skipTest() isn't
        available.
        """
        reason = compact(text, *args, **kw)
        try:
            super(PipAccelTestCase, self).skipTest(reason)
        except AttributeError:
            # unittest.TestCase.skipTest() isn't available in Python 2.6.
            logger.warning("%s", reason)

    def initialize_pip_accel(self, load_environment_variables=False, **overrides):
        """
        Construct an isolated pip accelerator instance.

        The pip-accel instance will not load configuration files but it may
        load environment variables because that's how FakeS3 is enabled on
        Travis CI (and in my local tests).

        :param load_environment_variables: If :data:`True` the pip-accel instance
                                           will load environment variables (not
                                           the default).
        :param overrides: Any keyword arguments are set as properties on the
                          :class:`~.Config` instance (overrides for
                          configuration defaults).
        """
        config = Config(load_configuration_files=False,
                        load_environment_variables=load_environment_variables)
        if not overrides.get('data_directory'):
            # Always use a data directory isolated to the current test.
            overrides['data_directory'] = create_temporary_directory(prefix='pip-accel-', suffix='-profile')
        for name, value in overrides.items():
            setattr(config, name, value)
        accelerator = PipAccelerator(config)
        return accelerator

    def test_related_archives_logic(self):
        """
        Test filename translation logic used by :attr:`pip_accel.req.Requirement.related_archives`.

        The :func:`pip_accel.req.escape_name()` function generates regular
        expression patterns that match the given requirement name literally
        while treating dashes and underscores as equivalent. This test ensures
        that the generated regular expression patterns work as expected.
        """
        pattern = re.compile(escape_name('cached-property'))
        for delimiter in '-', '_':
            name = 'cached%sproperty' % delimiter
            assert pattern.match(name), \
                ("Pattern generated by escape_name() doesn't match %r!" % name)

    def test_environment_validation(self):
        """
        Test the validation of :data:`sys.prefix` versus ``$VIRTUAL_ENV``.

        This tests the :func:`~pip_accel.PipAccelerator.validate_environment()` method.
        """
        original_value = os.environ.get('VIRTUAL_ENV', None)
        try:
            os.environ['VIRTUAL_ENV'] = generate_nonexisting_pathname()
            self.assertRaises(EnvironmentMismatchError, self.initialize_pip_accel)
        finally:
            if original_value is not None:
                os.environ['VIRTUAL_ENV'] = original_value
            else:
                del os.environ['VIRTUAL_ENV']

    def test_config_object_handling(self):
        """Test that configuration options can be overridden in the Python API."""
        config = Config()
        # Create a unique value that compares equal only to itself.
        unique_value = object()
        # Check the default value of a configuration option.
        assert config.cache_format_revision != unique_value
        # Override the default value.
        config.cache_format_revision = unique_value
        # Ensure that the override is respected.
        assert config.cache_format_revision == unique_value
        # Test that environment variables can set configuration options.
        os.environ['PIP_ACCEL_AUTO_INSTALL'] = 'true'
        os.environ['PIP_ACCEL_MAX_RETRIES'] = '41'
        os.environ['PIP_ACCEL_S3_TIMEOUT'] = '51'
        os.environ['PIP_ACCEL_S3_RETRIES'] = '61'
        config = Config()
        assert config.auto_install is True
        assert config.max_retries == 41
        assert config.s3_cache_timeout == 51
        assert config.s3_cache_retries == 61

    def test_config_file_handling(self):
        """
        Test error handling during loading of configuration files.

        This tests the :func:`~pip_accel.config.Config.load_configuration_file()` method.
        """
        directory = create_temporary_directory(prefix='pip-accel-', suffix='-profile')
        config_file = os.path.join(directory, 'pip-accel.ini')
        # Create a dummy configuration object.
        config = Config(load_configuration_files=False, load_environment_variables=False)
        # Check that loading of non-existing configuration files raises the expected exception.
        self.assertRaises(Exception, config.load_configuration_file, generate_nonexisting_pathname())
        # Check that loading of invalid configuration files raises the expected exception.
        with open(config_file, 'w') as handle:
            handle.write('[a-section-not-called-pip-accel]\n')
            handle.write('name = value\n')
        self.assertRaises(Exception, config.load_configuration_file, config_file)
        # Check that valid configuration files are successfully loaded.
        with open(config_file, 'w') as handle:
            handle.write('[pip-accel]\n')
            handle.write('data-directory = %s\n' % directory)
        os.environ['PIP_ACCEL_CONFIG'] = config_file
        config = Config()
        assert config.data_directory == directory

    def test_cleanup_of_broken_links(self):
        """
        Verify that broken symbolic links in the source index are cleaned up.

        This tests the :func:`~pip_accel.PipAccelerator.clean_source_index()` method.
        """
        if WINDOWS:
            return self.skipTest("Skipping broken symbolic link cleanup test (Windows doesn't support symbolic links).")
        source_index = create_temporary_directory(prefix='pip-accel-', suffix='-source-index')
        broken_link = os.path.join(source_index, 'this-is-a-broken-link')
        os.symlink(generate_nonexisting_pathname(), broken_link)
        assert os.path.islink(broken_link), "os.symlink() doesn't work, what the?!"
        self.initialize_pip_accel(source_index=source_index)
        assert not os.path.islink(broken_link), "pip-accel didn't clean up a broken link in its source index!"

    def test_empty_download_cache(self):
        """
        Verify pip-accel's "keeping pip off the internet" logic using an empty cache.

        This test downloads, builds and installs pep8 1.6.2 to verify that
        pip-accel keeps pip off the internet when intended.
        """
        pip_install_args = ['--ignore-installed', 'pep8==1.6.2']
        # Initialize an instance of pip-accel with an empty cache.
        accelerator = self.initialize_pip_accel()
        # First we do a simple sanity check that unpack_source_dists() does not
        # connect to PyPI when it's missing distributions (it should raise a
        # DistributionNotFound exception instead).
        try:
            accelerator.unpack_source_dists(pip_install_args)
            assert False, ("This line should not be reached! (unpack_source_dists()"
                           " is expected to raise DistributionNotFound)")
        except Exception as e:
            # We expect a `DistributionNotFound' exception.
            if not isinstance(e, DistributionNotFound):
                # If we caught a different type of exception something went
                # wrong so we want to propagate the original exception, not
                # obscure it!
                raise
        # Download the source distribution from PyPI and validate the resulting requirement object.
        requirements = accelerator.download_source_dists(pip_install_args)
        assert isinstance(requirements, list), "Unexpected return value type from download_source_dists()!"
        assert len(requirements) == 1, "Expected download_source_dists() to return one requirement!"
        assert requirements[0].name == 'pep8', "Requirement has unexpected name!"
        assert requirements[0].version == '1.6.2', "Requirement has unexpected version!"
        assert os.path.isdir(requirements[0].source_directory), "Requirement's source directory doesn't exist!"
        # Test the build and installation of the binary package.
        num_installed = accelerator.install_requirements(requirements)
        assert num_installed == 1, "Expected pip-accel to install exactly one package!"
        # Make sure the `pep8' module can be imported after installation.
        __import__('pep8')
        # We now have a non-empty download cache and source index so this
        # should not raise an exception (it should use the source index).
        accelerator.unpack_source_dists(pip_install_args)

    def test_package_upgrade(self):
        """Test installation of newer versions over older versions."""
        accelerator = self.initialize_pip_accel()
        # Install version 1.6 of the `pep8' package.
        num_installed = accelerator.install_from_arguments([
            '--ignore-installed', '--no-binary=:all:', 'pep8==1.6',
        ])
        assert num_installed == 1, "Expected pip-accel to install exactly one package!"
        # Install version 1.6.2 of the `pep8' package.
        num_installed = accelerator.install_from_arguments([
            '--ignore-installed', '--no-binary=:all:', 'pep8==1.6.2',
        ])
        assert num_installed == 1, "Expected pip-accel to install exactly one package!"

    def test_package_downgrade(self):
        """Test installation of older versions over newer version (package downgrades)."""
        if find_installed_version('requests') != '2.6.0':
            return self.skipTest("""
                Skipping package downgrade test because requests==2.6.0 should be
                installed beforehand (see `scripts/prepare-test-environment.sh'
                in the git repository of pip-accel).
            """)
        accelerator = self.initialize_pip_accel()
        # Downgrade to requests 2.2.1.
        accelerator.install_from_arguments(['requests==2.2.1'])
        # Make sure requests was downgraded.
        assert find_installed_version('requests') == '2.2.1', \
            "pip-accel failed to (properly) downgrade requests to version 2.2.1!"

    def test_s3_backend(self):
        """
        Verify the successful usage of the S3 cache backend.

        This test downloads, builds and installs pep8 1.6.2 several times to
        verify that the S3 cache backend works. It depends on FakeS3.

        This test uses a temporary binary index which it wipes after a
        successful installation and then it installs the exact same package
        again to test the code path that gets a cached binary distribution
        archive from the S3 cache backend.

        .. warning:: This test *abuses* FakeS3 in several ways to simulate the
                     handling of error conditions (it's not pretty but it is
                     effective because it significantly increases the coverage
                     of the S3 cache backend):

                     1. **First the FakeS3 root directory is made read only**
                        to force an error when uploading to S3. This is to test
                        the automatic fall back to a read only S3 bucket.

                     2. **Then FakeS3 is terminated** to force a failure in the
                        S3 cache backend. This verifies that pip-accel handles
                        the failure of an "optional" cache backend gracefully.

        """
        try:
            # Start a FakeS3 server on a temporary port and make sure we shut
            # it down before we return to the caller (context manager magic).
            with FakeS3Server() as fakes3:
                # Initialize an instance of pip-accel with an empty cache.
                accelerator = self.initialize_pip_accel(**fakes3.client_options)
                # Run the installation four times.
                for i in [1, 2, 3, 4]:
                    if i > 1:
                        logger.debug("Resetting binary index to force binary distribution download from S3 ..")
                        wipe_directory(accelerator.config.binary_cache)
                    if i == 3 and not WINDOWS:
                        logger.warning("Making FakeS3 directory (%s) read only"
                                       " to emulate read only S3 bucket ..",
                                       fakes3.root)
                        wipe_directory(fakes3.root)
                        os.chmod(fakes3.root, 0o555)
                    if i == 4:
                        logger.warning("Killing FakeS3 process to force S3 cache backend failure ..")
                        fakes3.kill()
                    # Install the pep8 package using the S3 cache backend.
                    num_installed = accelerator.install_from_arguments([
                        '--ignore-installed', '--no-binary=:all:', 'pep8==1.6.2',
                    ])
                    assert num_installed == 1, "Expected pip-accel to install exactly one package!"
                    # Check the state of the S3 cache backend.
                    if i < 3:
                        assert not accelerator.config.s3_cache_readonly, \
                            "S3 cache backend is unexpectedly in read only state!"
                    elif not WINDOWS:
                        assert accelerator.config.s3_cache_readonly, \
                            "S3 cache backend is unexpectedly not in read only state!"
        except CommandNotFound:
            self.skipTest("Skipping S3 cache backend test because FakeS3 isn't installed.")

    def test_wheel_install(self):
        """
        Test the installation of a package from a wheel distribution.

        This test installs Paver 1.2.4 (a random package without dependencies
        that I noticed is available as a Python 2.x and Python 3.x compatible
        wheel archive on PyPI).
        """
        accelerator = self.initialize_pip_accel()
        wheels_already_supported = accelerator.setuptools_supports_wheels()
        # Test the installation of Paver (and the upgrade of Setuptools?).
        num_installed = accelerator.install_from_arguments([
            # We force pip to install from a wheel archive.
            '--ignore-installed', '--only-binary=:all:', 'Paver==1.2.4',
        ])
        if wheels_already_supported:
            assert num_installed == 1, "Expected pip-accel to install exactly one package!"
        else:
            assert num_installed == 2, "Expected pip-accel to install exactly two packages!"
        # Make sure the Paver program works after installation.
        try_program('paver')

    def test_bdist_fallback(self):
        """
        Verify that fall back from ``bdist_dumb`` to ``bdist`` action works.

        This test verifies that pip-accel properly handles ``setup.py`` scripts
        that break ``python setup.py bdist_dumb`` but support ``python setup.py
        bdist`` as a fall back. This issue was originally reported based on
        ``Paver==1.2.3`` in `issue 37`_, so that's the package used for this
        test.

        .. _issue 37: https://github.com/paylogic/pip-accel/issues/37
        """
        # Install Paver 1.2.3 using pip-accel.
        accelerator = self.initialize_pip_accel()
        num_installed = accelerator.install_from_arguments([
            '--ignore-installed', '--no-binary=:all:', 'paver==1.2.3'
        ])
        assert num_installed == 1, "Expected pip-accel to install exactly one package!"
        # Make sure the Paver program works after installation.
        try_program('paver')

    def test_installed_files_tracking(self):
        """
        Verify that tracking of installed files works correctly.

        This tests the :func:`~pip_accel.bdist.BinaryDistributionManager.update_installed_files()`
        method.

        When pip installs a Python package it also creates a file called
        ``installed-files.txt`` that contains the pathnames of the files that
        were installed. This file enables pip to uninstall Python packages
        later on. Because pip-accel implements its own package installation it
        also creates the ``installed-files.txt`` file, in order to enable the
        user to uninstall a package with pip even if the package was installed
        using pip-accel.
        """
        if not hasattr(sys, 'real_prefix'):
            # Prevent unsuspecting users from accidentally running the find_files()
            # tests below on their complete `/usr' or `/usr/local' tree :-).
            return self.skipTest("""
                Skipping installed files tracking test because the test suite
                isn't running in a recognized virtual environment.
            """)
        elif platform.python_implementation() == 'PyPy':
            return self.skipTest("""
                Skipping installed files tracking test because iPython can't be
                properly installed on PyPy (in my experience).
            """)
        # Install the iPython 1.0 source distribution using pip.
        command = InstallCommand()
        opts, args = command.parse_args([
            '--ignore-installed', '--no-binary=:all:', 'ipython==1.0'
        ])
        command.run(opts, args)
        # Make sure the iPython program works after installation using pip.
        try_program('ipython3' if sys.version_info[0] == 3 else 'ipython')
        # Find the iPython related files installed by pip.
        files_installed_using_pip = set(find_files(sys.prefix, '*ipython*'))
        assert len(files_installed_using_pip) > 0, \
            "It looks like pip didn't install iPython where we expected it to do so?!"
        logger.debug("Found %i files installed using pip: %s",
                     len(files_installed_using_pip), files_installed_using_pip)
        # Remove the iPython installation.
        uninstall('ipython')
        # Install the iPython 1.0 source distribution using pip-accel.
        accelerator = self.initialize_pip_accel()
        num_installed = accelerator.install_from_arguments([
            '--ignore-installed', '--no-binary=:all:', 'ipython==1.0'
        ])
        assert num_installed == 1, "Expected pip-accel to install exactly one package!"
        # Make sure the iPython program works after installation using pip-accel.
        try_program('ipython3' if sys.version_info[0] == 3 else 'ipython')
        # Find the iPython related files installed by pip-accel.
        files_installed_using_pip_accel = set(find_files(sys.prefix, '*ipython*'))
        assert len(files_installed_using_pip_accel) > 0, \
            "It looks like pip-accel didn't install iPython where we expected it to do so?!"
        logger.debug("Found %i files installed using pip-accel: %s",
                     len(files_installed_using_pip_accel), files_installed_using_pip_accel)
        # Test that pip and pip-accel installed exactly the same files.
        assert files_installed_using_pip == files_installed_using_pip_accel, \
            "It looks like pip and pip-accel installed different files for iPython!"
        # Test that pip knows how to uninstall iPython installed by pip-accel
        # due to the installed-files.txt file generated by pip-accel.
        uninstall('ipython')
        # Make sure all files related to iPython were uninstalled by pip.
        assert len(list(find_files(sys.prefix, '*ipython*'))) == 0, \
            "It looks like pip didn't properly uninstall iPython after installation using pip-accel!"

    def test_setuptools_injection(self):
        """
        Test that ``setup.py`` scripts are always evaluated using setuptools.

        This test installs ``docutils==0.12`` as a sample package whose
        ``setup.py`` script uses `distutils` instead of `setuptools`. Because
        pip and pip-accel unconditionally evaluate ``setup.py`` scripts using
        `setuptools` instead of `distutils` the resulting installation should
        have an ``*.egg-info`` metadata directory instead of a file (which is
        what this test verifies).
        """
        # Install the docutils 0.12 source distribution using pip-accel.
        accelerator = self.initialize_pip_accel()
        num_installed = accelerator.install_from_arguments([
            '--ignore-installed', '--no-binary=:all:', 'docutils==0.12'
        ])
        assert num_installed == 1, "Expected pip-accel to install exactly one package!"
        # Import docutils to find the site-packages directory.
        docutils_module = __import__('docutils')
        init_file = docutils_module.__file__
        docutils_directory = os.path.dirname(init_file)
        site_packages_directory = os.path.dirname(docutils_directory)
        # Find the *.egg-info metadata created by the installation.
        egg_info_matches = glob.glob(os.path.join(site_packages_directory, 'docutils-*.egg-info'))
        assert len(egg_info_matches) == 1, "Expected to find one *.egg-info record for docutils!"
        # Make sure the *.egg-info metadata is stored in a directory.
        assert os.path.isdir(egg_info_matches[0]), \
            "Installation of docutils didn't create expected *.egg-info metadata directory!"

    def test_requirement_objects(self):
        """
        Test the public properties of :class:`pip_accel.req.Requirement` objects.

        This test confirms (amongst other things) that the logic which
        distinguishes transitive requirements from non-transitive (direct)
        requirements works correctly (and keeps working as expected :-).
        """
        # Download and unpack rotate-backups.
        accelerator = self.initialize_pip_accel()
        requirements = accelerator.get_requirements([
            '--ignore-installed', 'rotate-backups==0.1.1'
        ])
        # Separate direct from transitive requirements.
        direct_requirements = [r for r in requirements if r.is_direct]
        transitive_requirements = [r for r in requirements if r.is_transitive]
        # Enable remote debugging of test suite failures (should they ever happen).
        logger.debug("Direct requirements: %s", direct_requirements)
        logger.debug("Transitive requirements: %s", transitive_requirements)
        # Validate the direct requirements (there should be just one; rotate-backups).
        assert len(direct_requirements) == 1, \
            "pip-accel reported more than one direct requirement! (I was expecting only one)"
        assert direct_requirements[0].name == 'rotate-backups', \
            "pip-accel reported a direct requirement with an unexpected name!"
        # Validate the transitive requirements.
        expected_transitive_requirements = set([
            'coloredlogs', 'executor', 'humanfriendly', 'naturalsort',
            'python-dateutil', 'six'
        ])
        actual_transitive_requirements = set(r.name for r in transitive_requirements)
        assert expected_transitive_requirements.issubset(actual_transitive_requirements), \
            "Requirement set reported by pip-accel is missing expected transitive requirements!"
        # Make sure Requirement.wheel_metadata raises the expected exception
        # when the requirement isn't a wheel distribution.
        self.assertRaises(TypeError, operator.attrgetter('wheel_metadata'), direct_requirements[0])
        # Make sure Requirement.sdist_metadata raises the expected exception
        # when the requirement isn't a source distribution.
        requirements = accelerator.get_requirements([
            # We force pip to install from a wheel archive.
            '--ignore-installed', '--only-binary=:all:', 'Paver==1.2.4',
        ])
        self.assertRaises(TypeError, operator.attrgetter('sdist_metadata'), requirements[0])

    def test_editable_install(self):
        """
        Test the installation of editable packages using ``pip install --editable``.

        This test clones the git repository of the Python package `pycodestyle`
        and installs the package as an editable package.

        We want to import the `pycodestyle` module to confirm that it was
        properly installed but we can't do that in the process that's running
        the test suite because it will fail with an import error. Python
        subprocesses however will import the `pycodestyle` module just fine.

        This happens because ``easy-install.pth`` (used for editable packages)
        is loaded once during startup of the Python interpreter and never
        refreshed. There's no public, documented way that I know of to refresh
        :data:`sys.path` (see `issue 402 in the Gunicorn issue tracker`_ for
        a related discussion).

        .. _issue 402 in the Gunicorn issue tracker: https://github.com/benoitc/gunicorn/issues/402
        """
        # Make sure pycodestyle isn't already installed when this test starts.
        uninstall_through_subprocess('pycodestyle')
        if not self.pycodestyle_git_repo:
            return self.skipTest("""
                Skipping editable installation test (git clone of pycodestyle
                repository from GitHub seems to have failed).
            """)
        # Install the package from the checkout as an editable package.
        accelerator = self.initialize_pip_accel()
        num_installed = accelerator.install_from_arguments([
            '--ignore-installed', '--editable', self.pycodestyle_git_repo,
        ])
        assert num_installed == 1, "Expected pip-accel to install exactly one package!"
        # Importing pycodestyle here fails even though the package is properly
        # installed. We start a Python interpreter in a subprocess to verify
        # that pycodestyle is properly installed to work around this.
        python = subprocess.Popen(
            [sys.executable, '-c', 'print(__import__("pycodestyle").__file__)'],
            stdout=subprocess.PIPE,
        )
        stdout, stderr = python.communicate()
        python_module = stdout.decode().strip()
        # Under Mac OS X the following startswith() check will fail if we don't
        # resolve symbolic links (under Mac OS X /var is a symbolic link to
        # /private/var).
        git_checkout = os.path.realpath(self.pycodestyle_git_repo)
        python_module = os.path.realpath(python_module)
        assert python_module.startswith(git_checkout), \
            "Editable Python module not located under git checkout of project!"
        # Cleanup after ourselves so that unrelated tests involving the
        # pycodestyle package don't get confused when they're run after
        # this test and encounter an editable package.
        uninstall_through_subprocess('pycodestyle')

    def test_setup_requires_caching(self):
        """
        Test that :class:`pip_accel.SetupRequiresPatch` works as expected.

        This test is a bit convoluted because I haven't been able to find a
        simpler way to ensure that setup requirements can be re-used from the
        ``.eggs`` directory managed by pip-accel. A side effect inside the
        setup script seems to be required, but the setuptools sandbox forbids
        writing to files outside the build directory so an external command
        needs to be used ...
        """
        if not requirement_is_installed('setuptools >= 7.0'):
            return self.skipTest("""
                skipping setup requires caching test
                (setuptools >= 7.0 isn't available)
            """)
        # Initialize pip-accel with an isolated working tree.
        root = create_temporary_directory(prefix='pip-accel-', suffix='-setup-requires-test')
        accelerator = self.initialize_pip_accel(data_directory=root)
        # In this test we'll generate the following two Python packages.
        setup_requires_provider = 'setup-requires-provider'
        setup_requires_user = 'setup-requires-user'
        # Create a data file to track setup script invocations.
        tracker_datafile = os.path.join(root, 'setup-invocations.json')
        with open(tracker_datafile, 'w') as handle:
            json.dump({setup_requires_provider: {}, setup_requires_user: {}}, handle)
        # Create a Python script to track setup script invocations.
        tracker_script = os.path.join(root, 'setup-invocation-tracker')
        with open(tracker_script, 'w') as handle:
            handle.write(dedent('''
                import json, sys
                package_name = sys.argv[1]
                command_name = next(a for a in sys.argv[2:] if not a.startswith('-'))
                with open({filename}) as handle:
                    invocations = json.load(handle)
                counter = invocations[package_name].get(command_name, 0)
                invocations[package_name][command_name] = counter + 1
                with open({filename}, 'w') as handle:
                    json.dump(invocations, handle)
            ''', filename=repr(tracker_datafile)))
        # Generate the package that provides a setup requirement.
        self.generate_package(
            name=setup_requires_provider,
            version='1.0',
            source_index=accelerator.config.source_index,
            tracker_script=tracker_script,
        )
        # Generate the package that needs a setup requirement.
        self.generate_package(
            name=setup_requires_user,
            version='1.0',
            setup_requires=[setup_requires_provider],
            find_links=accelerator.config.source_index,
            source_index=accelerator.config.source_index,
            tracker_script=tracker_script,
        )
        # Install the package that needs a setup requirement two times.
        state = []
        for i in 1, 2:
            # Install the package that needs a setup requirement.
            num_installed = accelerator.install_from_arguments(['--ignore-installed', setup_requires_user])
            # Even though two packages are *involved*, only one should be *installed*.
            assert num_installed == 1, "Expected pip-accel to install exactly one package!"
            # Load the data file with setup invocations.
            with open(tracker_datafile) as handle:
                state.append(json.load(handle))
        # Sanity check our invocation tracking machinery by making sure that
        # the `egg_info' command of the package that needs a setup requirement
        # was called once for each iteration.
        assert state[0][setup_requires_user]['egg_info'] == 1
        assert state[1][setup_requires_user]['egg_info'] == 2
        # Also make sure the `bdist_dumb' command was called once in total.
        assert state[1][setup_requires_user]['bdist_dumb'] == 1
        # Now we can finally check what this whole test is about: The
        # `bdist_egg' command (used for setup requirements) should only have
        # been called on the first iteration because the second iteration was
        # able to use the `.eggs' symbolic link.
        assert state[0][setup_requires_provider]['bdist_egg'] == state[1][setup_requires_provider]['bdist_egg']

    def generate_package(self, name, version, source_index, tracker_script, find_links=None, setup_requires=[]):
        """Helper for :func:`test_setup_requires_caching()` to generate temporary Python packages."""
        directory = create_temporary_directory(prefix='pip-accel-', suffix='-generated-package')
        makedirs(directory)
        with open(os.path.join(directory, 'setup.py'), 'w') as handle:
            setup_params = [
                'name=%r' % name,
                'version=%r' % version,
                'packages=find_packages()',
            ]
            if setup_requires:
                setup_params.append('setup_requires=%r' % setup_requires)
            handle.write(dedent('''
                import subprocess, sys
                subprocess.check_call([sys.executable, {script}, {package}] + sys.argv[1:])
                from setuptools import setup, find_packages
                setup({params})
            ''', script=repr(tracker_script), package=repr(name), params=', '.join(setup_params)))
        if find_links:
            with open(os.path.join(directory, 'setup.cfg'), 'w') as handle:
                handle.write(dedent('''
                    [easy_install]
                    allow_hosts = ''
                    find_links = {file_url}/
                ''', file_url=create_file_url(find_links)))
        shutil.move(create_source_dist(directory), source_index)

    def test_time_based_cache_invalidation(self):
        """
        Test default cache invalidation logic (based on modification times).

        When a source distribution archive is changed the cached binary
        distribution archive is invalidated and rebuilt. This test ensures that
        the default cache invalidation logic (based on modification times of
        files) works as expected.
        """
        self.check_cache_invalidation(trust_mod_times=True)

    def test_checksum_based_cache_invalidation(self):
        """
        Test alternate cache invalidation logic (based on checksums).

        When a source distribution archive is changed the cached binary
        distribution archive is invalidated and rebuilt. This test ensures that
        the alternate cache invalidation logic (based on SHA1 checksums of
        files) works as expected.
        """
        self.check_cache_invalidation(trust_mod_times=False)

    def check_cache_invalidation(self, **overrides):
        """Test cache invalidation with the given option(s)."""
        if not self.pycodestyle_git_repo:
            return self.skipTest("""
                skipping cache invalidation test (git clone of `pycodestyle'
                repository from github seems to have failed).
            """)
        accelerator = self.initialize_pip_accel(**overrides)
        # Install the pycodestyle package.
        accelerator.install_from_arguments(['--ignore-installed', create_source_dist(self.pycodestyle_git_repo)])
        # Find the modification time of the source and binary distributions.
        sdist_mtime_1 = os.path.getmtime(find_one_file(accelerator.config.source_index, '*pycodestyle*'))
        bdist_mtime_1 = os.path.getmtime(find_one_file(accelerator.config.binary_cache, '*pycodestyle*.tar.gz'))
        # Install the pycodestyle package for the second time, using a newly
        # created source distribution archive with different contents.
        with open(os.path.join(self.pycodestyle_git_repo, 'MANIFEST.in'), 'w') as handle:
            handle.write("\n# An innocent comment to change the checksum ..\n")
        accelerator.install_from_arguments(['--ignore-installed', create_source_dist(self.pycodestyle_git_repo)])
        # Find the modification time of the source and binary distributions.
        sdist_mtime_2 = os.path.getmtime(find_one_file(accelerator.config.source_index, '*pycodestyle*'))
        bdist_mtime_2 = os.path.getmtime(find_one_file(accelerator.config.binary_cache, '*pycodestyle*.tar.gz'))
        # Check that the source distribution's modification time changed
        # (because we created it by running the `python setup.py sdist'
        # command a second time).
        assert sdist_mtime_2 > sdist_mtime_1, "Source distribution should have been refreshed!"
        # Check that the binary distribution's modification time has changed
        # (because we changed the contents of the source distribution).
        assert bdist_mtime_2 > bdist_mtime_1, "Binary distribution should have been refreshed!"

    def test_cli_install(self):
        """
        Test the pip-accel command line interface by installing a trivial package.

        This test provides some test coverage for the pip-accel command line
        interface, to make sure the command line interface works on all
        supported versions of Python.
        """
        returncode = test_cli('pip-accel', 'install',
                              # Make sure the -v, --verbose option is supported.
                              '-v', '--verbose',
                              # Make sure the -q, --quiet option is supported.
                              '-q', '--quiet',
                              # Ignore packages that are already installed.
                              '--ignore-installed',
                              # Install the naturalsort package.
                              'naturalsort')
        assert returncode == 0, "pip-accel command line interface exited with nonzero return code!"
        # Make sure the `natsort' module can be imported after installation.
        __import__('natsort')

    def test_cli_usage_message(self):
        """Test the pip-accel command line usage message."""
        with CaptureOutput() as stream:
            returncode = test_cli('pip-accel')
            assert returncode == 0, "pip-accel command line interface exited with nonzero return code!"
            assert 'Usage: pip-accel' in str(stream), "pip-accel command line interface didn't report usage message!"

    def test_cli_as_module(self):
        """Make sure ``python -m pip_accel ...`` works."""
        if sys.version_info[:2] <= (2, 6):
            return self.skipTest("""
                Skipping 'python -m pip_accel ...' test because this feature
                became supported on Python 2.7 while you are running an older
                version.
            """)
        else:
            output = execute(sys.executable, '-m', 'pip_accel', capture=True)
            assert 'Usage: pip-accel' in output, "'python -m pip_accel' didn't report usage message!"

    def test_constraint_file_support(self):
        """
        Test support for constraint files.

        With the pip 7.x upgrade support for constraint files was added to pip.
        Due to the way this was implemented in pip the use of constraint files
        would break pip-accel as reported in `issue 63`_. The issue was since
        fixed and this test makes sure constraint files remain supported.

        .. _issue 63: https://github.com/paylogic/pip-accel/issues/63
        """
        # Make sure pep8 isn't already installed when this test starts.
        uninstall_through_subprocess('pep8')
        # Prepare a temporary constraints file.
        constraint_file = os.path.join(create_temporary_directory(prefix='pip-accel-', suffix='-constraints-test'),
                                       'constraints-file.txt')
        with open(constraint_file, 'w') as handle:
            # Constrain the version of the pep8 package.
            handle.write('pep8==1.6.0\n')
            # Include a constraint that is not a requirement. Before pip-accel
            # version 0.37.1 this would raise an exception instead of being
            # ignored.
            handle.write('paver==1.2.4\n')
        # Install pep8 based on the constraints file.
        accelerator = self.initialize_pip_accel()
        num_installed = accelerator.install_from_arguments([
            '--ignore-installed',
            '--no-binary=:all:',
            '--constraint=%s' % constraint_file,
            'pep8',
        ])
        assert num_installed == 1, "Expected pip-accel to install exactly one package!"
        # Make sure the correct version was installed.
        assert find_installed_version('pep8') == '1.6.0', \
            "pip-accel failed to (properly) install pep8 version 1.6.0!"

    def test_empty_requirements_file(self):
        """
        Test handling of empty requirements files.

        Old versions of pip-accel would raise an internal exception when an
        empty requirements file was given. This was reported in `issue 47`_ and
        it was pointed out that pip reports a warning but exits with return
        code zero. This test makes sure pip-accel now handles empty
        requirements files the same way pip does.

        .. _issue 47: https://github.com/paylogic/pip-accel/issues/47
        """
        empty_file = os.path.join(create_temporary_directory(prefix='pip-accel-', suffix='-empty-requirements-test'),
                                  'empty-requirements-file.txt')
        open(empty_file, 'w').close()
        returncode = test_cli('pip-accel', 'install', '--requirement', empty_file)
        assert returncode == 0, "pip-accel command line interface failed on empty requirements file!"

    def test_system_package_dependency_installation(self):
        """
        Test the (automatic) installation of required system packages.

        This test installs cffi 0.8.6 to confirm that the system packages
        required by cffi are automatically installed by pip-accel to make the
        build of cffi succeed.

        .. warning:: This test forces the removal of the system package
                     ``libffi-dev`` before it tries to install cffi, because
                     without this nasty hack the test would only install
                     required system packages on the first run, because on
                     later runs the required system packages would already be
                     installed. Because of this very non conventional behavior
                     the test is skipped unless the environment variable
                     ``PIP_ACCEL_TEST_AUTO_INSTALL=yes`` is set (opt-in).
        """
        if WINDOWS:
            return self.skipTest("""
                Skipping system package dependency installation
                test (not supported on Windows).
            """)
        elif platform.python_implementation() == 'PyPy':
            return self.skipTest("""
                Skipping system package dependency installation test (cffi on
                PyPy doesn't depend on libffi-dev being installed so this won't
                work at all).
            """)
        elif not coerce_boolean(os.environ.get('PIP_ACCEL_TEST_AUTO_INSTALL')):
            return self.skipTest("""
                Skipping system package dependency installation test because
                you need to set $PIP_ACCEL_TEST_AUTO_INSTALL=true to allow the
                test suite to use `sudo'.
            """)
        # Never allow concurrent execution of this code path, because the last
        # thing I want is to ruin my system by spawning concurrent dpkg and
        # apt-get processes. By actually preventing this I get to use detox for
        # parallel testing :-).
        with AptLock():
            # Force the removal of a system package required by `cffi' without
            # removing any (reverse) dependencies (we don't actually want to
            # break the system, thank you very much :-). Disclaimer: you opt in
            # to this with $PIP_ACCEL_TEST_AUTO_INSTALL...
            cffi_dependency = 'libffi-dev'
            subprocess.call([
                'sudo', '-p', "\n Please provide sudo access to (temporarily) remove %s: " % cffi_dependency,
                'dpkg', '--remove', '--force-depends', cffi_dependency,
            ])
            cffi_requirement = 'cffi==0.8.6'
            # Make sure that when automatic installation is disabled the system
            # package manager refuses to install the missing dependency.
            accelerator = self.initialize_pip_accel(auto_install=False)
            self.assertRaises(DependencyInstallationRefused, accelerator.install_from_arguments, [
                '--ignore-installed', cffi_requirement,
            ])

            # A file-like object that always says no :-).
            class FakeStandardInput(object):
                def readline(self):
                    return 'no\n'

            # Try to ask for permission but refuse to give it.
            with PatchedAttribute(sys, 'stdin', FakeStandardInput()):
                accelerator = self.initialize_pip_accel(auto_install=None)
                self.assertRaises(DependencyInstallationRefused, accelerator.install_from_arguments, [
                    '--ignore-installed', cffi_requirement,
                ])
            # Install cffi while a system dependency is missing and automatic installation is allowed.
            accelerator = self.initialize_pip_accel(auto_install=True)
            num_installed = accelerator.install_from_arguments([
                '--ignore-installed', cffi_requirement,
            ])
            assert num_installed >= 1, "Expected pip-accel to install at least one package!"

    def test_system_package_dependency_failures(self):
        """Test that unsupported platforms are handled gracefully in system package dependency management."""
        this_script = os.path.abspath(__file__)
        pip_accel_directory = os.path.dirname(this_script)
        deps_directory = os.path.join(pip_accel_directory, 'deps')
        dummy_deps_config = os.path.join(deps_directory, 'unsupported-platform-test.ini')
        # Create an unsupported system package manager configuration.
        with open(dummy_deps_config, 'w') as handle:
            handle.write('[commands]\n')
            handle.write('supported = false\n')
            handle.write('list = false\n')
            handle.write('installed = false\n')
        try:
            # Validate that the unsupported configuration is ignored (gracefully).
            manager = SystemPackageManager(Config())
            assert manager.list_command != 'false' and manager.install_command != 'false', \
                "System package manager seems to have activated an unsupported configuration!"
        finally:
            # Never leave the dummy configuration file behind.
            os.remove(dummy_deps_config)

    @cached_property
    def pycodestyle_git_repo(self):
        """The pathname of a git clone of the `pycodestyle` (formerly `pep8`) package (:data:`None` if git fails)."""
        git_checkout = create_temporary_directory(prefix='pip-accel-', suffix='-pycodestyle-checkout')
        git_remote = 'https://github.com/PyCQA/pycodestyle.git'
        if subprocess.call(['git', 'clone', '--depth=1', git_remote, git_checkout]) == 0:
            return git_checkout
        else:
            return None


def wipe_directory(pathname):
    """
    Delete and recreate a directory.

    :param pathname: The directory's pathname (a string).
    """
    if os.path.isdir(pathname):
        shutil.rmtree(pathname)
    os.makedirs(pathname)


def create_source_dist(sources):
    """
    Create a source distribution archive from a Python package.

    :param sources: A dictionary containing a ``setup.py`` script (a string).
    :returns: The pathname of the generated archive (a string).
    """
    distributions_directory = os.path.join(sources, 'dist')
    wipe_directory(distributions_directory)
    assert subprocess.call(['python', 'setup.py', 'sdist'], cwd=sources) == 0
    return find_one_file(distributions_directory, '*')


def uninstall_through_subprocess(package_name):
    """
    Remove an installed Python package by running ``pip`` as a subprocess.

    :param package_name: The name of the package (a string).

    This function is specifically for use in the pip-accel test suite to
    reliably uninstall a Python package installed in the current environment
    while avoiding issues caused by stale data in pip and the packages it uses
    internally. Doesn't complain if the package isn't installed to begin with.
    """
    while True:
        returncode = subprocess.call([
            find_python_program('pip'),
            'uninstall', '--yes',
            package_name,
        ])
        if returncode != 0:
            break


def find_installed_version(package_name, encoding='UTF-8'):
    """
    Find the version of an installed package (in a subprocess).

    :param package_name: The name of the package (a string).
    :returns: The package's version (a string) or :data:`None` if the package can't
              be found.

    This function is specifically for use in the pip-accel test suite to
    reliably determine the installed version of a Python package in the current
    environment while avoiding issues caused by stale data in pip and the
    packages it uses internally.
    """
    interpreter = subprocess.Popen([sys.executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    snippet = dedent("""
        import pkg_resources
        for distribution in pkg_resources.working_set:
            if distribution.key.lower() == {name}:
                print(distribution.version)
                break
    """, name=repr(package_name.lower()))
    stdout, stderr = interpreter.communicate(snippet.encode(encoding))
    output = stdout.decode(encoding)
    if output and not output.isspace():
        return output.strip()


def find_one_file(directory, pattern):
    """
    Use :func:`find_files()` to find a file and make sure a single file is matched.

    :param directory: The pathname of the directory to be searched (a string).
    :param pattern: The filename pattern to match (a string).
    :returns: The matched pathname (a string).
    :raises: :exc:`~exceptions.AssertionError` when no file or more than one
             file is matched.
    """
    matches = list(find_files(directory, pattern))
    if len(matches) == 1:
        return matches[0]
    elif matches:
        msg = "More than one file matched %r pattern in directory %r! (matches: %s)"
        raise Exception(msg % (pattern, directory, concatenate(matches)))
    else:
        msg = "Failed to find file matching %r pattern in directory %r! (available files: %s)"
        raise Exception(msg % (pattern, directory, concatenate(find_files(directory, '*'))))


def find_files(directory, pattern):
    """
    Find files whose pathname contains the given substring.

    :param directory: The pathname of the directory to be searched (a string).
    :param pattern: The filename pattern to match (a string).
    :returns: A generator of pathnames (strings).
    """
    pattern = pattern.lower()
    for root, dirs, files in os.walk(directory):
        for filename in files:
            pathname = os.path.join(root, filename)
            if fnmatch.fnmatch(pathname.lower(), pattern):
                yield pathname


def try_program(program_name):
    """
    Test that a Python program (installed in the current environment) runs successfully.

    This assumes that the program supports the ``--help`` option, because the
    program is executed with the ``--help`` argument to verify that the program
    runs (``--help`` was chose because it implies a lack of side effects).

    :param program_name: The base name of the program to test (a string). The
                         absolute pathname will be calculated by combining
                         :data:`sys.prefix` and this argument.
    :raises: :exc:`~exceptions.AssertionError` when a test fails.
    """
    program_path = find_python_program(program_name)
    logger.debug("Making sure %s is installed ..", program_path)
    assert os.path.isfile(program_path), \
        ("Missing program file! (%s)" % program_path)
    logger.debug("Making sure %s is executable ..", program_path)
    assert os.access(program_path, os.X_OK), \
        ("Program file not executable! (%s)" % program_path)
    logger.debug("Making sure %s --help works ..", program_path)
    with open(os.devnull, 'wb') as null_device:
        # Redirect stdout to /dev/null and stderr to stdout.
        assert subprocess.call([program_path, '--help'], stdout=null_device, stderr=subprocess.STDOUT) == 0, \
            ("Program doesn't run! (%s --help failed)" % program_path)


def find_python_program(program_name):
    """
    Get the absolute pathname of a Python program installed in the current environment.

    :param name: The base name of the program (a string).
    :returns: The absolute pathname of the program (a string).
    """
    directory = 'Scripts' if WINDOWS else 'bin'
    pathname = os.path.join(sys.prefix, directory, program_name)
    if WINDOWS:
        pathname += '.exe'
    return pathname


def generate_nonexisting_pathname():
    """
    Generate a pathname that is expected not to exist.

    :returns: A pathname (string) that doesn't refer to an existing directory
              or file on the file system (assuming :func:`random.random()`
              does what it's documented to do :-).
    """
    return os.path.join(tempfile.gettempdir(),
                        'this-path-certainly-will-not-exist-%s' % random.random())


def test_cli(*arguments):
    """
    Test the pip-accel command line interface.

    Runs pip-accel's command line interface inside the current Python process
    by temporarily changing :data:`sys.argv`, invoking the
    :func:`pip_accel.cli.main()` function and catching
    :exc:`~exceptions.SystemExit`.

    :param arguments: The value that :data:`sys.argv` should be set to (a
                      list of strings).
    :returns: The exit code of ``pip-accel``.
    """
    original_argv = sys.argv
    try:
        sys.argv = list(arguments)
        main()
        return 0
    except SystemExit as e:
        return e.code
    finally:
        sys.argv = original_argv


class CaptureOutput(object):

    """Context manager that captures what's written to :data:`sys.stdout`."""

    def __init__(self):
        """Initialize a string IO object to be used as :data:`sys.stdout`."""
        self.stream = StringIO()

    def __enter__(self):
        """Start capturing what's written to :data:`sys.stdout`."""
        self.original_stdout = sys.stdout
        sys.stdout = self.stream
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Stop capturing what's written to :data:`sys.stdout`."""
        sys.stdout = self.original_stdout

    def __str__(self):
        """Get the text written to :data:`sys.stdout`."""
        return self.stream.getvalue()


class AptLock(Lock):

    """Cross-process locking for critical sections to enable parallel execution of the test suite."""

    def __init__(self):
        """Initialize an :class:`AptLock` object."""
        super(AptLock, self).__init__(
            filename=os.path.join(tempfile.gettempdir(), 'pip-accel-test-suite.lock'),
            fail_when_locked=False,
            timeout=(60 * 10),
        )


class FakeS3Server(EphemeralTCPServer):

    """Subclass of :class:`.ExternalCommand` that manages a temporary FakeS3 server."""

    def __init__(self, **options):
        """Initialize a :class:`FakeS3Server` object."""
        self.logger = logging.getLogger('pip_accel.tests.fakes3')
        self.root = create_temporary_directory(prefix='pip-accel-', suffix='-fakes3')
        """
        The pathname of the temporary directory used to store the files
        required to run the FakeS3 server (a string).
        """
        # Find the absolute pathname of FakeS3 (relevant on Windows).
        matches = which('fakes3')
        program = matches[0] if matches else ''
        # Initialize the superclass.
        command = [program, '--root=%s' % self.root, '--port=%s' % self.port_number]
        super(FakeS3Server, self).__init__(*command, scheme='s3', logger=logger, **options)

    @property
    def client_options(self):
        """
        Configuration options for pip-accel to connect with the FakeS3 server.

        This is a dictionary of keyword arguments for the :class:`.Config`
        initializer to make pip-accel connect with the FakeS3 server.
        """
        return dict(
            s3_cache_url=self.render_location(scheme='http'),
            s3_cache_bucket='pip-accel-test-bucket',
            s3_cache_create_bucket=True,
            s3_cache_timeout=10,
            s3_cache_retries=0,
        )


if __name__ == '__main__':
    unittest.main()
