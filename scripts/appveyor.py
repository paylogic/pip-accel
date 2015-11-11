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
from executor import ExternalCommandFailed, execute, get_search_path, which

print("FakeS3 executables:\n%r" % which('fakes3'))

for program in which('fakes3'):
    with open(program) as handle:
        contents = handle.read()
        delimiter = "-" * 40
        vertical_whitespace = "\n\n"
        padding = vertical_whitespace + delimiter + vertical_whitespace
        print(padding + ("%s:" % program) + padding + contents + padding)

for program in ['fakes3', 'fakes3.bat'] + which('fakes3'):
    try:
        execute(program, '--help')
    except ExternalCommandFailed:
        print("%s doesn't work?!" % program)

print("Executable search path:\n\n%s" % "\n\n".join(
    "%s:\n%s" % (d, concatenate(sorted(os.listdir(d))))
    for d in get_search_path() if os.path.isdir(d)
))
