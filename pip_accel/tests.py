#!/usr/bin/env python

# Tests for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 28, 2014
# URL: https://github.com/paylogic/pip-accel
#
# TODO Test successful installation of iPython, because it used to break! (nested /lib/ directory)

# Standard library modules.
import logging
import os
import pipes
import shutil
import sys
import tempfile
import unittest

# External dependencies.
import coloredlogs
from humanfriendly import coerce_boolean
from pip.exceptions import DistributionNotFound

# Modules included in our package.
from pip_accel import PipAccelerator
from pip_accel.cli import main
from pip_accel.config import Config

# Initialize a logger for this module.
logger = logging.getLogger(__name__)

class PipAccelTestCase(unittest.TestCase):

    def setUp(self):
        """
        Create a temporary working directory and a virtual environment where
        pip-accel can be tested in isolation (starting with an empty download
        cache, source index and binary index and no installed modules) and make
        sure pip and pip-accel use the directory. Also creates the directories
        for the download cache, the source index and the binary index (normally
        this is done from pip_accel.main).
        """
        coloredlogs.install(level=logging.DEBUG)
        # Create a temporary working directory.
        self.working_directory = tempfile.mkdtemp()
        self.download_cache = os.path.join(self.working_directory, 'download-cache')
        # Create a temporary build directory.
        self.build_directory = os.path.join(self.working_directory, 'build')
        # Create a temporary virtual environment.
        self.virtual_environment = os.path.join(self.working_directory, 'environment')
        python = 'python%i.%i' % (sys.version_info[0], sys.version_info[1])
        assert os.system('virtualenv --python=%s %s' % (pipes.quote(python), pipes.quote(self.virtual_environment))) == 0
        # Make sure pip-accel uses the pip in the temporary virtual environment.
        os.environ['PATH'] = '%s:%s' % (os.path.join(self.virtual_environment, 'bin'), os.environ['PATH'])
        os.environ['VIRTUAL_ENV'] = self.virtual_environment
        # Make pip and pip-accel use the temporary working directory.
        os.environ['PIP_DOWNLOAD_CACHE'] = self.download_cache
        os.environ['PIP_ACCEL_CACHE'] = self.working_directory

    def runTest(self):
        """
        A very basic test of the functions that make up the pip-accel command
        using the `virtualenv` package as a test case.
        """
        accelerator = PipAccelerator(Config(), validate=False)
        # We will test the downloading, conversion to binary distribution and
        # installation of the virtualenv package (we simply need a package we
        # know is available from PyPI).
        arguments = ['--ignore-installed', 'virtualenv==1.8.4']
        # First we do a simple sanity check that unpack_source_dists() does NOT
        # connect to PyPI when it's missing source distributions (it should
        # raise a DistributionNotFound exception instead).
        try:
            accelerator.unpack_source_dists(arguments)
            # This line should never be reached.
            self.assertTrue(False)
        except Exception as e:
            # We expect a `DistributionNotFound' exception.
            self.assertTrue(isinstance(e, DistributionNotFound))
        # Download the source distribution from PyPI.
        requirements = accelerator.download_source_dists(arguments)
        self.assertTrue(isinstance(requirements, list))
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0].name, 'virtualenv')
        self.assertEqual(requirements[0].version, '1.8.4')
        self.assertTrue(os.path.isdir(requirements[0].source_directory))
        # Test the build and installation of the binary package. We have to
        # pass `prefix' explicitly here because the Python process running this
        # test is not inside the virtual environment created to run the
        # tests...
        accelerator.install_requirements(requirements,
                                         prefix=self.virtual_environment,
                                         python=os.path.join(self.virtual_environment, 'bin', 'python'))
        # Validate that the `virtualenv' package was properly installed.
        logger.debug("Checking that `virtualenv' executable was installed ..")
        self.assertTrue(os.path.isfile(os.path.join(self.virtual_environment, 'bin', 'virtualenv')))
        logger.debug("Checking that `virtualenv' command works ..")
        command = '%s --help' % pipes.quote(os.path.join(self.virtual_environment, 'bin', 'virtualenv'))
        self.assertEqual(os.system(command), 0)
        # We now have a non-empty download cache and source index so this
        # should not raise an exception (it should use the source index).
        accelerator.unpack_source_dists(arguments)
        # Verify that pip-accel properly deals with broken symbolic links
        # pointing from the source index to the download cache.
        os.unlink(os.path.join(self.download_cache, os.listdir(self.download_cache)[0]))
        accelerator = PipAccelerator(Config(), validate=False)
        accelerator.install_from_arguments(arguments)
        # Verify that pip-accel properly handles setup.py scripts that break
        # the `bdist_dumb' action but support the `bdist' action as a fall
        # back.
        accelerator = PipAccelerator(Config(), validate=False)
        accelerator.install_from_arguments(['paver==1.2.3'])
        # I'm not yet sure how to effectively test the command line interface,
        # because this test suite abuses validate=False which the command line
        # interface does not expose. That's why the following will report an
        # error message. For now at least we're running the code and making
        # sure there are no syntax errors / incompatibilities.
        try:
            sys.argv = ['pip-accel', 'install', 'virtualenv==1.8.4']
            main()
            # This should not be reached.
            self.assertTrue(False)
        except BaseException as e:
            # For now the main() function is expected to fail and exit with a
            # nonzero status code (explained above).
            self.assertTrue(isinstance(e, SystemExit))
        # Test system package dependency handling.
        if coerce_boolean(os.environ.get('PIP_ACCEL_TEST_AUTO_INSTALL')):
            # Force the removal of a system package required by `lxml' without
            # removing any (reverse) dependencies (we don't actually want to
            # break the system, thank you very much :-). Disclaimer: you opt in
            # to this with $PIP_ACCEL_TEST_AUTO_INSTALL...
            os.system('sudo dpkg --remove --force-depends libxslt1-dev')
            os.environ['PIP_ACCEL_AUTO_INSTALL'] = 'true'
            accelerator = PipAccelerator(Config(), validate=False)
            accelerator.install_from_arguments(arguments=['--ignore-installed', 'lxml==3.2.1'],
                                               prefix=self.virtual_environment,
                                               python=os.path.join(self.virtual_environment, 'bin', 'python'))

    def tearDown(self):
        """Cleanup the temporary working directory that was used during the test."""
        shutil.rmtree(self.working_directory)

if __name__ == '__main__':
    unittest.main()
