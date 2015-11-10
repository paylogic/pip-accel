#!/bin/bash -e

# Shell script to initialize a pip-accel test environment.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: November 10, 2015
# URL: https://github.com/paylogic/pip-accel
#
# This shell script is used in tox.ini and .travis.yml to prepare
# virtual environments for running the pip-accel test suite.

main () {

  # Install the dependencies of pip-accel.
  msg "Installing dependencies .."
  pip install --quiet --requirement=requirements.txt

  # Install pip-accel in editable mode. The LC_ALL=C trick makes sure that the
  # setup.py script works regardless of the user's locale (this is all about
  # that little copyright symbol at the bottom of README.rst :-).
  msg "Installing pip-accel (in editable mode) .."
  LC_ALL=C pip install --quiet --editable .

  # Install the test suite's dependencies. We ignore py.test wheels because of
  # an obscure issue that took me hours to debug and I really don't want to get
  # into it here :-(.
  msg "Installing test dependencies .."
  pip install --no-binary=pytest --quiet --requirement=$PWD/requirements-testing.txt

  # Make it possible to install local working copies of selected dependencies.
  install_working_copies

  # Downgrade setuptools so the test suite can verify that setuptools
  # is upgraded to >= 0.8 when a binary wheel is installed.
  downgrade_setuptools

  # Install requests==2.6.0 so the test suite can downgrade to requests==2.2.1
  # (to verify that downgrading of packages works).
  install_requests

  # Remove iPython so the test suite can install iPython in a clean environment.
  remove_ipython

}

install_working_copies () {
  # Once in a while I find myself working on multiple Python projects at the same
  # time, context switching between the projects and running each project's tests
  # in turn. Out of the box `tox' will not be able to locate and install my
  # unreleased working copies, but using this ugly hack it works fine :-).
  if hostname | grep -q peter; then
    for PROJECT in coloredlogs executor humanfriendly; do
      DIRECTORY="$HOME/projects/python/$PROJECT"
      if [ -e "$DIRECTORY" ]; then
        msg "Installing working copy of $PROJECT .."
        pip install --quiet "$DIRECTORY"
      fi
    done
  fi
}

downgrade_setuptools () {
  # FWIW: Performing this downgrade inside the test suite's Python process
  # doesn't work as expected because pip (pkg_resources) will still think the
  # newer version is installed (due to caching without proper cache
  # invalidation by pkg_resources).
  if python -c 'import sys; sys.exit(0 if sys.version_info[0] == 2 else 1)'; then
    # The downgrade of setuptools fails on Travis CI Python 3.x builds, but as
    # long as the test suite runs the automatic upgrade at least once (on
    # Python 2.6 and/or Python 2.7) I'm happy :-).
    msg "Downgrading setuptools (so the test suite can upgrade it) .."
    # FYI: Binary wheels disabled to reduce test suite noise.
    pip install --quiet --no-binary=:all: 'setuptools >= 0.7.8, < 0.8'
  fi
}

install_requests () {
  # FWIW: Ideally the test suite should just be able to install requests==2.6.0
  # and then downgrade to requests==2.2.1 but unfortunately this doesn't work
  # reliably in the same Python process due to (what looks like) caching in the
  # pkg_resources module bundled with pip (which in turn causes a variety of
  # confusing internal errors in pip and pip-accel).
  msg "Installing requests (so the test suite can downgrade it) .."
  pip install --quiet requests==2.6.0
}

remove_ipython () {
  # Remove iPython so the test suite can install iPython in a clean
  # environment, allowing the test suite to compare the files installed and
  # removed by pip and pip-accel.
  msg "Removing iPython (so the test suite can install and remove it) .."
  pip uninstall --yes ipython &>/dev/null || true
}

msg () {
  echo "[prepare-test-environment]" "$@" >&2
}

main "$@"
