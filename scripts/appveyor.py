# Simple Python script that helps to understand the AppVeyor environment.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: November 11, 2015
# URL: https://github.com/paylogic/pip-accel

"""Introspection of the AppVeyor CI environment ..."""

# Standard library modules.
import os

# External dependencies.
from humanfriendly import concatenate

# Test dependencies.
from executor import get_search_path, which

print("FakeS3 executables:\n%r" % which('fakes3'))
print("Executable search path:\n\n%s" % "\n\n".join(
    "%s:\n%s" % (d, concatenate(sorted(os.listdir(d))))
    for d in get_search_path()
))
