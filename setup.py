#!/usr/bin/env python

# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: October 30, 2015
# URL: https://github.com/paylogic/pip-accel

"""Setup script for the `pip-accel` package."""

# Standard library modules.
import codecs
import os
import re

# De-facto standard solution for Python packaging.
from setuptools import setup, find_packages

# Find the directory where the source distribution was unpacked.
source_directory = os.path.dirname(os.path.abspath(__file__))

# Find the current version.
module = os.path.join(source_directory, 'pip_accel', '__init__.py')
with open(module) as handle:
    for line in handle:
        match = re.match(r'^__version__\s*=\s*["\']([^"\']+)["\']$', line)
        if match:
            version_string = match.group(1)
            break
    else:
        raise Exception("Failed to extract version from %s!" % module)

# Fill in the long description (for the benefit of PyPI)
# with the contents of README.rst (rendered by GitHub).
readme_file = os.path.join(source_directory, 'README.rst')
with codecs.open(readme_file, 'r', 'utf-8') as handle:
    readme_text = handle.read()

# Fill in the "install_requires" field based on requirements.txt.
with open(os.path.join(source_directory, 'requirements.txt')) as handle:
    requirements = [line.strip() for line in handle]

setup(name='pip-accel',
      version=version_string,
      description='Accelerator for pip, the Python package manager',
      long_description=readme_text,
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
      install_requires=requirements,
      test_suite='pip_accel.tests',
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
          'Topic :: Software Development :: Build Tools',
          'Topic :: Software Development :: Libraries :: Python Modules',
          'Topic :: System :: Archiving :: Packaging',
          'Topic :: System :: Installation/Setup',
          'Topic :: System :: Software Distribution',
      ])
