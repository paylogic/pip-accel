#!/usr/bin/env python

# Tests for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: June 6, 2013
# URL: https://github.com/paylogic/pip-accel
#
# TODO Test successful installation of iPython, because it used to break! (nested /lib/ directory)

# Standard library modules.
import os
import shutil
import tempfile
import unittest

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
        # Create a temporary working directory.
        self.working_directory = tempfile.mkdtemp()
        # Create a temporary virtual environment.
        self.virtual_environment = os.path.join(self.working_directory, 'environment')
        assert os.system('virtualenv "%s"' % self.virtual_environment) == 0
        # Make sure pip-accel uses the pip in the temporary virtual environment.
        os.environ['PATH'] = '%s:%s' % (os.path.join(self.virtual_environment, 'bin'), os.environ['PATH'])
        os.environ['VIRTUAL_ENV'] = self.virtual_environment
        # Make pip and pip-accel use the temporary working directory.
        os.environ['PIP_DOWNLOAD_CACHE'] = os.path.join(self.working_directory, 'download-cache')
        os.environ['PIP_ACCEL_CACHE'] = self.working_directory
        # Enable verbose output from pip-accel.
        os.environ['PIP_ACCEL_VERBOSE'] = 'yes, please'
        # Initialize the required subdirectories.
        print "pip_accel_tests 1: PIP_ACCEL_CACHE=%r" % os.environ.get('PIP_ACCEL_CACHE', '?')
        self.pip_accel = __import__('pip_accel')
        self.pip_accel.initialize_directories()
        print "pip_accel_tests 2: PIP_ACCEL_CACHE=%r" % os.environ.get('PIP_ACCEL_CACHE', '?')

    def runTest(self):
        """
        A very basic test of the functions that make up the pip-accel command
        using the `virtualenv` package as a test case.
        """
        # We will test the downloading, conversion to binary distribution and
        # installation of the virtualenv package (we simply need a package we
        # know is available from PyPi).
        arguments = ['install', '--ignore-installed', '--build=%s' % self.working_directory, 'virtualenv==1.8.4']
        # First we do a simple sanity check.
        from pip.exceptions import DistributionNotFound
        try:
            requirements = self.pip_accel.unpack_source_dists(arguments)
            # This line should never be reached.
            self.assertTrue(False)
        except Exception, e:
            self.assertTrue(isinstance(e, DistributionNotFound))
        # Download the source distribution from PyPi.
        self.pip_accel.download_source_dists(arguments)
        # Implicitly verify that the download was successful.
        requirements = self.pip_accel.unpack_source_dists(arguments)
        # self.assertIsInstance(requirements, list)
        self.assertTrue(isinstance(requirements, list))
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0][0], 'virtualenv')
        self.assertEqual(requirements[0][1], '1.8.4')
        self.assertTrue(os.path.isdir(requirements[0][2]))
        # Test the build and installation of the binary package. We have to
        # pass "install_prefix" explicitly here because the Python process
        # running this test is not inside the virtual environment created to
        # run the tests...
        self.assertTrue(self.pip_accel.build_binary_dists(requirements))
        self.assertTrue(self.pip_accel.install_requirements(requirements, install_prefix=self.virtual_environment))
        # Check that the virtualenv command was installed.
        self.assertTrue(os.path.isfile(os.path.join(self.virtual_environment, 'bin', 'virtualenv')))

    def tearDown(self):
        """
        Cleanup the temporary working directory that was used during the test.
        """
        shutil.rmtree(self.working_directory)

if __name__ == '__main__':
    unittest.main()
