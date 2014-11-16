#!/usr/bin/env python

# Setup script for the pip accelerator.
#
# Author: Peter Odding <peter.odding@paylogic.eu>
# Last Change: November 16, 2014
# URL: https://github.com/paylogic/pip-accel

import re
from os.path import abspath, dirname, join
from setuptools import setup, find_packages

# Find the directory where the source distribution was unpacked.
source_directory = dirname(abspath(__file__))

# Find the current version.
module = join(source_directory, 'pip_accel', '__init__.py')
for line in open(module):
    match = re.match(r'^__version__\s*=\s*["\']([^"\']+)["\']$', line)
    if match:
        version_string = match.group(1)
        break
else:
    raise Exception("Failed to extract version from %s!" % module)

# Fill in the long description (for the benefit of PyPI)
# with the contents of README.rst (rendered by GitHub).
readme_file = join(source_directory, 'README.rst')
readme_text = open(readme_file).read()

# Fill in the "install_requires" field based on requirements.txt.
requirements = [l.strip() for l in open(join(source_directory, 'requirements.txt'))]

setup(name='pip-accel',
      version=version_string,
      description='Accelerator for pip, the Python package manager',
      long_description=readme_text,
      author='Peter Odding',
      author_email='peter.odding@paylogic.eu',
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
      tests_require=['virtualenv'],
      test_suite='pip_accel.tests')
