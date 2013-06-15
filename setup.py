#!/usr/bin/env python

import re
from os.path import abspath, dirname, join
from setuptools import setup, find_packages

# Find the directory where the source distribution was unpacked.
source_directory = dirname(abspath(__file__))

# Find the current version.
module = join(source_directory, 'pip_accel', '__init__.py')
for line in open(module, 'r'):
    match = re.match(r'^__version__\s*=\s*["\']([^"\']+)["\']$', line)
    if match:
        version_string = match.group(1)
        break
else:
    raise Exception, "Failed to extract version from pip_accel/__init__.py!"

# Fill in the long description (for the benefit of PyPI)
# with the contents of README.rst (rendered by GitHub).
readme_file = join(source_directory, 'README.rst')
readme_text = open(readme_file, 'r').read()

setup(name='pip-accel',
      version=version_string,
      description='Accelerator for pip, the Python package manager',
      long_description=readme_text,
      author='Peter Odding',
      author_email='peter.odding@paylogic.eu',
      url='https://github.com/paylogic/pip-accel',
      packages=find_packages(),
      py_modules=['pip_accel_tests'],
      entry_points={'console_scripts': ['pip-accel = pip_accel:main']},
      install_requires=['pip >= 1.3', 'coloredlogs'],
      tests_require=['virtualenv'],
      test_suite='pip_accel_tests')
