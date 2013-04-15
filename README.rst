pip-accel: Accelerator for pip, the Python package manager
==========================================================

**Usage: pip-accel [ARGUMENTS TO PIP]**

The ``pip-accel`` program is a wrapper for `pip <http://www.pip-installer.org/>`_, the Python package manager. It accelerates the usage of ``pip`` to initialize `Python virtual environments <http://www.virtualenv.org/en/latest/>`_ given one or more `requirements <http://www.pip-installer.org/en/latest/cookbook.html#requirements-files>`_ files. It does so by combining the following two approaches:

1. Source distribution downloads are cached and used to generate a `local index of source distribution archives <http://www.pip-installer.org/en/latest/cookbook.html#fast-local-installs>`_. If all your dependencies are pinned to absolute versions whose source distribution downloads were previously cached, ``pip-accel`` won't need a network connection at all! This is one of the reasons why ``pip`` can be so slow: given absolute pinned dependencies available in the download cache it will still scan `PyPi <http://pypi.python.org/>`_ and distribution websites.

2. `Binary distributions <http://docs.python.org/2/distutils/builtdist.html>`_ are used to speed up the process of installing dependencies with binary components (like `M2Crypto <https://pypi.python.org/pypi/M2Crypto>`_ and `LXML <https://pypi.python.org/pypi/lxml>`_). Instead of recompiling these dependencies again for every virtual environment we compile them once and cache the result as a binary ``*.tar.gz`` distribution.

The ``pip-accel`` command supports all subcommands and options supported by ``pip``, however it is of course only useful for the ``pip install`` subcommand.

How fast is it?
---------------

To give you an idea of how effective ``pip-accel`` is, below are the results of a test to build a virtual environment for one of the internal codebases of `Paylogic <http://www.paylogic.com/>`_. This code base requires more than 40 dependencies including several packages that need compilation with SWIG and a C compiler:

=========  ================================  ===========  ===============
Program    Description                       Duration     Percentage
=========  ================================  ===========  ===============
pip        Default configuration             434 seconds  100% (baseline)
pip        With download cache (first run)   423 seconds  97%
pip        With download cache (second run)  332 seconds  76%
pip-accel  First run                         375 seconds  86%
pip-accel  Second run                        34 seconds   8%
=========  ================================  ===========  ===============

Control flow of pip-accel
-------------------------

The way ``pip-accel`` works is not very intuitive but it is very effective. Below is an overview of the control flow. Once you take a look at the code you'll notice that the steps below are all embedded in a loop that retries several times. This is mostly because of step 2 (downloading the source distributions).

1. Run ``pip install --no-index --no-install -r requirements.txt`` to unpack source distributions available in the local source index. This is the first step because ``pip-accel`` should accept ``requirements.txt`` files as input but it will manually install dependencies from cached binary distributions (without using ``pip`` or ``easy_install``):

  -  If the command succeeds it means all dependencies are already available as downloaded source distributions. We'll parse the verbose pip output of step 1 to find the direct and transitive dependencies (names and versions) defined in ``requirements.txt`` and use them as input for step 3. Go to step 3.

  -  If the command fails it probably means not all dependencies are available as local source distributions yet so we should download them. Go to step 2.

2. Run ``pip install --no-install -r requirements.txt`` to download missing source distributions to the download cache:

  -  If the command fails it means that pip encountered errors while scanning `PyPi <http://pypi.python.org/>`_, scanning a distribution website, downloading a source distribution or unpacking a source distribution. Usually these kinds of errors are intermittent so retrying a few times is worth a shot. Go to step 2.

  -  If the command succeeds it means all dependencies are now available as local source distributions; we don't need the network anymore! Go to step 1.

3. Run ``python setup.py bdist`` for each dependency that doesn't have a cached binary distribution yet (taking version numbers into account). Go to step 4.

4. Install all dependencies from binary distributions based on the list of direct and transitive dependencies obtained in step 1. We have to do these installations manually because ``easy_install`` nor ``pip`` support binary ``*.tar.gz`` distributions.

Contact
-------

If you have questions, bug reports, suggestions, etc. please create an issue on the `GitHub project page <https://github.com/paylogic/pip-accel>`_. The latest version of ``pip-accel`` will always be available on GitHub.

License
-------

This software is licensed under the `MIT license <http://en.wikipedia.org/wiki/MIT_License>`_ just like `pip <http://www.pip-installer.org/>`_ (on which ``pip-accel`` is based).

© 2013 Peter Odding and Paylogic International.
