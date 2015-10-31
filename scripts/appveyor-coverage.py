# Python wrapper for coverage reporting from AppVeyor to Coveralls.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: October 31, 2015
# URL: https://github.com/paylogic/pip-accel

"""
An attempt to integrate coverage from AppVeyor and Travis on Coveralls.

Since version 0.33 (released on October 30, 2015) pip-accel supports the
Windows platform and runs its test suite on Windows using AppVeyor CI. Coverage
is also collected on Windows and reported to Coveralls. As mentioned in `the
pull request`_ where all of this was implemented the coverage collection kind
of works but it's not exactly ideal!

This Python script is an experiment (work in progress!) in getting AppVeyor
builds to *correctly* submit coverage statistics to Coveralls so that the
coverage of the Linux and Windows builds is merged into one overview by
Coveralls. I'm not even sure if that is possible (it's clearly not a supported
use case out of the box :-) but I guess this experiment will tell me one way or
the other.

.. _the pull request: https://github.com/paylogic/pip-accel/pull/61#issuecomment-152356508
"""

# Standard library modules.
import logging
import os
import pprint
import subprocess
import sys

# External dependencies.
import coloredlogs

# Initialize a logger for this script.
logger = logging.getLogger('appveyor-coverage-hack')


def main():
    """Command line interface for AppVeyor Coverage hack."""
    coloredlogs.install(level=logging.DEBUG)
    fix_branch_name()
    returncode = subprocess.call(sys.argv[1:])
    sys.exit(returncode)


def fix_branch_name():
    """
    Fix the name of the branch on which coverage is reported.

    AppVeyor test coverage on Coveralls is showing up on the branch name
    ``HEAD`` instead of ``master`` which (I'm guessing) makes it impossible for
    Coveralls to merge coverage statistics into one overview.

    According to the AppVeyor documentation on `environment variables`_ the
    environment variable ``$APPVEYOR_REPO_BRANCH`` should tell us whether we're
    operating on the ``master`` branch.

    Judging by `the source code`_ of the Python integration for Coveralls the
    ``$CI_BRANCH`` environment variable can be used to change the branch name
    that's reported to Coveralls.

    This hack was confirmed to work in `build 1.0.57`_.

    .. _environment variables: http://www.appveyor.com/docs/environment-variables
    .. _the source code: https://github.com/coagulant/coveralls-python/blob/master/coveralls/api.py
    .. _build 1.0.57: https://ci.appveyor.com/project/xolox/pip-accel/build/1.0.57
    """
    logger.debug("Existing environment variables (sanitized): %s", dump_environment())
    if os.environ.get('APPVEYOR_REPO_BRANCH') == 'master' and os.environ.get('CI_BRANCH') != 'master':
        logger.debug("Fixing $CI_BRANCH environment variable ..")
        os.environ['CI_BRANCH'] = os.environ['APPVEYOR_REPO_BRANCH']
        logger.debug("Modified environment variables (sanitized): %s", dump_environment())
    else:
        logger.debug("Not fixing $CI_BRANCH environment variable ..")


def dump_environment():
    """Get pretty printed environment dictionary without Coveralls repository token."""
    variables = dict(os.environ)
    variables['COVERALLS_REPO_TOKEN'] = '[secure]'
    return pprint.pformat(variables)


if __name__ == '__main__':
    main()
