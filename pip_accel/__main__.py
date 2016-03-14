# Accelerator for pip, the Python package manager.
#
# Author: Peter Odding <peter.odding@paylogic.com>
# Last Change: March 14, 2016
# URL: https://github.com/paylogic/pip-accel

"""
Enable running `pip-accel` as ``python -m pip_accel ...``.

This module provides a uniform (platform independent) syntax for invoking
`pip-accel`, that is to say the command line ``python -m pip_accel ...`` works
the same on Windows, Linux and Mac OS X.

This requires Python 2.7 or higher (it specifically doesn't work on Python
2.6). The way ``__main__`` modules work is documented under the documentation
of the `python -m`_ construct.

.. _python -m: https://docs.python.org/2/using/cmdline.html#cmdoption-m
"""

from pip_accel.cli import main

if __name__ == '__main__':
    main()
