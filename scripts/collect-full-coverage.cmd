:: Windows batch script to prepare for the pip-accel test suite.
::
:: Author: Peter Odding <peter.odding@paylogic.com>
:: Last Change: October 31, 2015
:: URL: https://github.com/paylogic/pip-accel
::
:: This Windows batch script is used to run the pip-accel test suite on
:: AppVeyor CI with increased coverage collection (which requires some
:: preparations). It installs/upgrades/removes several Python packages whose
:: installation, upgrade and/or removal is tested in the test suite to make
:: sure that the test suite starts from a known state.

:: Downgrade setuptools so that the test suite can verify that setuptools is
:: upgraded to >= 0.8 when a binary wheel is installed. Performing this
:: downgrade inside the test suite process doesn't work as expected because pip
:: (pkg_resources) will still think the newer version is installed (due to
:: caching without proper cache invalidation by pkg_resources).
"%PYTHON%\Scripts\pip.exe" install --no-binary=:all: "setuptools < 0.8"

:: Install requests==2.6.0 so the test suite can downgrade to requests==2.2.1
:: (to verify that downgrading of packages works). Ideally the test suite
:: should just be able to install requests==2.6.0 and then downgrade to
:: requests==2.2.1 but unfortunately this doesn't work reliably in the same
:: Python process due to (what looks like) caching in the pkg_resources module
:: bundled with pip (which in turn causes a variety of confusing internal
:: errors in pip and pip-accel).
"%PYTHON%\Scripts\pip.exe" install requests==2.6.0

:: Remove iPython so the test suite can install iPython in a clean environment,
:: allowing the test suite to compare the files installed and removed by pip
:: and pip-accel.
"%PYTHON%\Scripts\pip.exe" uninstall --yes ipython

:: If iPython wasn't installed to begin with, the previous command will have
:: returned with a nonzero exit code. We don't want this to terminate the
:: AppVeyor CI build.
exit /b 0
