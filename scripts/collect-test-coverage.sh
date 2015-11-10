#!/bin/bash -e

# Shell script to run the pip-accel test suite.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: November 11, 2015
# URL: https://github.com/paylogic/pip-accel
#
# This shell script is used in tox.ini and .travis.yml to run
# the pip-accel test suite with coverage collection enabled.

main () {

  # The following environment variable is needed to collect coverage about
  # automatic installation of dependencies on system packages. Please review
  # the notes in the test suite (pip_accel/tests.py) if you're not sure whether
  # you want to run this on your system :-).
  if [ -n "$CI" ] || (hostname | grep -q peter); then
    export PIP_ACCEL_TEST_AUTO_INSTALL=true
  fi

  # Don't silence the Boto logger because it can be interesting to see how Boto
  # deals with FakeS3 dropping out in the middle of the test suite.
  export PIP_ACCEL_SILENCE_BOTO=false

  # Run the test suite under py.test with coverage collection enabled?
  if [ "$COVERAGE" != no ]; then
    py.test --cov "$@"
  else
    py.test "$@"
  fi

}

main "$@"
