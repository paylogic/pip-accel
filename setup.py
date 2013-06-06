#!/usr/bin/env python

from os.path import abspath, dirname, join
from setuptools import setup, find_packages

# Fill in the long description (for the benefit of PyPi)
# with the contents of README.rst (rendered by GitHub).
readme_file = join(dirname(abspath(__file__)), 'README.rst')
readme_text = open(readme_file, 'r').read()

setup(name='pip-accel',
      version='0.8.9',
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
