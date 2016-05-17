#!/usr/bin/env python

# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: May 17, 2016
# URL: https://github.com/paylogic/pip-accel

"""Setup script for the `pip-accel` package."""

# Standard library modules.
import codecs
import os
import re

# De-facto standard solution for Python packaging.
from setuptools import setup, find_packages


def get_readme():
    """Get the contents of the ``README.rst`` file as a Unicode string."""
    with codecs.open(get_absolute_path('README.rst'), 'r', 'utf-8') as handle:
        return handle.read()


def get_version(*args):
    """Get the package's version (by extracting it from the source code)."""
    module_path = get_absolute_path(*args)
    with open(module_path) as handle:
        for line in handle:
            match = re.match(r'^__version__\s*=\s*["\']([^"\']+)["\']$', line)
            if match:
                return match.group(1)
    raise Exception("Failed to extract version from %s!" % module_path)


def get_requirements(*args):
    """Get requirements from pip requirement files."""
    requirements = set()
    with open(get_absolute_path(*args)) as handle:
        for line in handle:
            # Strip comments.
            line = re.sub(r'^#.*|\s#.*', '', line)
            # Ignore empty lines
            if line and not line.isspace():
                requirements.add(re.sub(r'\s+', '', line))
    return sorted(requirements)


def get_absolute_path(*args):
    """Transform relative pathnames into absolute pathnames."""
    directory = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(directory, *args)


setup(name='pip-accel',
      version=get_version('pip_accel', '__init__.py'),
      description='Accelerator for pip, the Python package manager',
      long_description=get_readme(),
      author='Peter Odding',
      author_email='peter.odding@paylogic.com',
      url='https://github.com/paylogic/pip-accel',
      packages=find_packages(),
      entry_points={
          'console_scripts': ['pip-accel = pip_accel.cli:main'],
          'pip_accel.cache_backends': [
              # The default cache backend (uses the local file system).
              'local = pip_accel.caches.local',
              # An optional cache backend that uses Amazon S3.
              's3 = pip_accel.caches.s3 [s3]',
          ],
      },
      extras_require={'s3': 'boto >= 2.32'},
      package_data={'pip_accel.deps': ['*.ini']},
      install_requires=get_requirements('requirements.txt'),
      test_suite='pip_accel.tests',
      tests_require=get_requirements('requirements-testing.txt'),
      classifiers=[
          'Development Status :: 5 - Production/Stable',
          'Environment :: Console',
          'Intended Audience :: Developers',
          'Intended Audience :: Information Technology',
          'Intended Audience :: System Administrators',
          'License :: OSI Approved :: MIT License',
          'Operating System :: MacOS :: MacOS X',
          'Operating System :: Microsoft :: Windows',
          'Operating System :: POSIX :: Linux',
          'Operating System :: Unix',
          'Programming Language :: Python :: 2.6',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3.4',
          'Programming Language :: Python :: 3.5',
          'Topic :: Software Development :: Build Tools',
          'Topic :: Software Development :: Libraries :: Python Modules',
          'Topic :: System :: Archiving :: Packaging',
          'Topic :: System :: Installation/Setup',
          'Topic :: System :: Software Distribution',
      ])
