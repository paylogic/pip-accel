pip-accel: Accelerator for pip, the Python package manager
==========================================================

.. image:: https://travis-ci.org/paylogic/pip-accel.svg?branch=master
   :target: https://travis-ci.org/paylogic/pip-accel

.. image:: https://coveralls.io/repos/paylogic/pip-accel/badge.svg?branch=master
   :target: https://coveralls.io/r/paylogic/pip-accel?branch=master

The pip-accel program is a wrapper for pip_, the Python package manager. It
accelerates the usage of pip to initialize `Python virtual environments`_ given
one or more `requirements files`_. It does so by combining the following two
approaches:

1. Source distribution downloads are cached and used to generate a `local index
   of source distribution archives`_. If all your dependencies are pinned to
   absolute versions whose source distribution downloads were previously
   cached, pip-accel won't need a network connection at all! This is one of the
   reasons why pip can be so slow: given absolute pinned dependencies available
   in the download cache it will still scan PyPI_ and distribution websites.

2. `Binary distributions`_ are used to speed up the process of installing
   dependencies with binary components (like M2Crypto_ and LXML_). Instead of
   recompiling these dependencies again for every virtual environment we
   compile them once and cache the result as a binary ``*.tar.gz``
   distribution.

In addition, since version 0.9 pip-accel contains a simple mechanism that
detects missing system packages when a build fails and prompts the user whether
to install the missing dependencies and retry the build.

The pip-accel program is currently tested on cPython 2.6, 2.7 and 3.4 and PyPy
(2.7). The automated test suite regularly runs on Ubuntu Linux but other Linux
variants (also those not based on Debian Linux) should work fine.

.. contents::

Status
------

Paylogic_ uses pip-accel to quickly and reliably initialize virtual
environments on its farm of continuous integration slaves which are constantly
running unit tests (this was one of the original use cases for which pip-accel
was developed). We also use it on our build servers.

When pip-accel was originally developed PyPI_ was sometimes very unreliable
(PyPI wasn't `behind a CDN`_ back then). Because of the CDN, PyPI is much more
reliable nowadays however pip-accel still has its place:

- The CDN doesn't help for distribution sites, which are as unreliably as they
  have always been.

- By using pip-accel you can make Python deployments completely independent
  from internet connectivity.

- Because pip-accel caches compiled binary packages it can still provide a nice
  speed boost over using plain pip.

Usage
-----

The pip-accel command supports all subcommands and options supported by pip,
however it is of course only useful for the ``pip install`` subcommand. So for
example:

.. code-block:: bash

   $ pip-accel install -r requirements.txt

If you pass a ``-v`` or ``--verbose`` option then pip and pip-accel will both
use verbose output. The ``-q`` or ``--quiet`` option is also supported.

Based on the user running pip-accel the following file locations are used by
default:

=============================  =========================  =======================================
Root user                      All other users            Purpose
=============================  =========================  =======================================
``/var/cache/pip-accel``       ``~/.pip-accel``           Used to store the source/binary indexes
=============================  =========================  =======================================

This default can be overridden by defining the environment variable
``PIP_ACCEL_CACHE``.

Configuration
~~~~~~~~~~~~~

For most users the default configuration of pip-accel should be fine. If you do
want to change pip-accel's defaults you do so by setting environment variables
and/or adding configuration options to a configuration file. This is because
pip-accel shares its command line interface with pip and adding support for
command line options specific to pip-accel is non trivial and may end up
causing more confusion than it's worth :-). For an overview of the available
configuration options and corresponding environment variables please refer to
the `documentation of the pip_accel.config module`_.

How fast is it?
---------------

To give you an idea of how effective pip-accel is, below are the results of a
test to build a virtual environment for one of the internal code bases of
Paylogic_. This code base requires more than 40 dependencies including several
packages that need compilation with SWIG and a C compiler:

=========  ================================  ===========  ===============
Program    Description                       Duration     Percentage
=========  ================================  ===========  ===============
pip        Default configuration             444 seconds  100% (baseline)
pip        With download cache (first run)   416 seconds  94%
pip        With download cache (second run)  318 seconds  72%
pip-accel  First run                         397 seconds  89%
pip-accel  Second run                        30 seconds   7%
=========  ================================  ===========  ===============

Alternative cache backends
--------------------------

Bundled with pip-accel are a local cache backend (which stores distribution
archives on the local file system) and an `Amazon S3`_ backend (see below).

Both of these cache backends are registered with pip-accel using a generic
pluggable cache backend registration mechanism. This mechanism makes it
possible to register additional cache backends without modifying pip-accel. If
you are interested in the details please refer to pip-accel's ``setup.py``
script and the two simple Python modules that define the bundled backends.

If you've written a cache backend that you think may be valuable to others,
please feel free to open an issue or pull request on GitHub in order to get
your backend bundled with pip-accel.

Storing the binary cache on Amazon S3
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can configure pip-accel to store its binary cache files in an `Amazon S3`_
bucket. In this case Amazon S3 is treated as a second level cache, only used if
the local file system cache can't satisfy a dependency. If the dependency is
not found in the Amazon S3 bucket, the package is built and cached locally (as
usual) but then also saved to the Amazon S3 bucket. This functionality can be
useful for continuous integration build worker boxes that are ephemeral and
don't have persistent local storage to store the pip-accel binary cache.

To get started you need to install pip-accel as follows:

.. code-block:: bash

   $ pip install 'pip-accel[s3]'

The ``[s3]`` part enables the Amazon S3 cache backend by installing the Boto_
package. Once installed you can use the following environment variables to
configure the Amazon S3 cache backend:

``$PIP_ACCEL_S3_BUCKET``
 The name of the Amazon S3 bucket in which binary distribution archives should
 be cached. This environment variable is required to enable the Amazon S3 cache
 backend.

``$PIP_ACCEL_S3_PREFIX``
 The optional prefix to apply to all Amazon S3 keys. This enables name spacing
 based on the environment in which pip-accel is running (to isolate the binary
 caches of ABI incompatible systems). *The user is currently responsible for
 choosing a suitable prefix.*

``$PIP_ACCEL_S3_READONLY``
 If this option is set pip-accel will skip uploading to the Amazon S3 bucket.
 This means pip-accel will use the configured Amazon S3 bucket to "warm up"
 your local cache but it will never write to the bucket, so you can use read
 only credentials. Of course you will need to run at least one instance of
 pip-accel that does have write permissions, so this setup is best suited to
 teams working around e.g. a continuous integration (CI) server, where the CI
 server primes the cache and developers use the cache in read only mode.

You can also set these options from a configuration file, please refer to the
`documentation of the pip_accel.config module`_. You will also need to set AWS
credentials, either in a `.boto file`_ or in the ``$AWS_ACCESS_KEY_ID`` and
``$AWS_SECRET_ACCESS_KEY`` environment variables (refer to the Boto
documentation for details).

Using S3 compatible storage services
````````````````````````````````````

If you want to point pip-accel at an `S3 compatible storage service`_ that is
*not* Amazon S3 you can `override the S3 API URL`_ using a configuration option
or environment variable. For example the pip-accel test suite first installs
and starts FakeS3_ and then sets ``PIP_ACCEL_S3_URL=http://localhost:12345`` to
point pip-accel at the FakeS3 server (in order to test the Amazon S3 cache
backend without actually having to pay for an Amazon S3 bucket :-). For more
details please refer to the documentation of the `Amazon S3 cache backend`_.

Dependencies on system packages
-------------------------------

Since version 0.9 pip-accel contains a simple mechanism that detects missing
system packages when a build fails and prompts the user whether to install the
missing dependencies and retry the build. Currently only Debian Linux and
derivative Linux distributions are supported, although support for other
platforms should be easy to add. This functionality currently works based on
configuration files that define dependencies of Python packages on system
packages. This means the results should be fairly reliable, but every single
dependency needs to be manually defined...

Here's what it looks like in practice::

 2013-06-16 01:01:53 wheezy-vm INFO Building binary distribution of python-mcrypt (1.1) ..
 2013-06-16 01:01:53 wheezy-vm ERROR Failed to build binary distribution of python-mcrypt! (version: 1.1)
 2013-06-16 01:01:53 wheezy-vm INFO Build output (will probably provide a hint as to what went wrong):

 gcc -pthread -fno-strict-aliasing -DNDEBUG -g -fwrapv -O2 -Wall -Wstrict-prototypes -fPIC -DVERSION="1.1" -I/usr/include/python2.7 -c mcrypt.c -o build/temp.linux-i686-2.7/mcrypt.o
 mcrypt.c:23:20: fatal error: mcrypt.h: No such file or directory
 error: command 'gcc' failed with exit status 1

 2013-06-16 01:01:53 wheezy-vm INFO python-mcrypt: Checking for missing dependencies ..
 2013-06-16 01:01:53 wheezy-vm INFO You seem to be missing 1 dependency: libmcrypt-dev
 2013-06-16 01:01:53 wheezy-vm INFO I can install it for you with this command: sudo apt-get install --yes libmcrypt-dev
 Do you want me to install this dependency? [y/N] y
 2013-06-16 01:02:05 wheezy-vm INFO Got permission to install missing dependency.

 The following extra packages will be installed:
   libmcrypt4
 Suggested packages:
   mcrypt
 The following NEW packages will be installed:
   libmcrypt-dev libmcrypt4
 0 upgraded, 2 newly installed, 0 to remove and 68 not upgraded.
 Unpacking libmcrypt4 (from .../libmcrypt4_2.5.8-3.1_i386.deb) ...
 Unpacking libmcrypt-dev (from .../libmcrypt-dev_2.5.8-3.1_i386.deb) ...
 Setting up libmcrypt4 (2.5.8-3.1) ...
 Setting up libmcrypt-dev (2.5.8-3.1) ...

 2013-06-16 01:02:13 wheezy-vm INFO Successfully installed 1 missing dependency.
 2013-06-16 01:02:13 wheezy-vm INFO Building binary distribution of python-mcrypt (1.1) ..
 2013-06-16 01:02:14 wheezy-vm INFO Copying binary distribution python-mcrypt-1.1.linux-i686.tar.gz to cache as python-mcrypt:1.1:py2.7.tar.gz.

Integrating with tox
--------------------

You can tell Tox_ to use pip-accel using a small shell script that first uses
pip to install pip-accel, then uses pip-accel to bootstrap the virtual
environment. You can find details about this in `issue #30 on GitHub`_.

Control flow of pip-accel
-------------------------

The way pip-accel works is not very intuitive but it is very effective. Below
is an overview of the control flow. Once you take a look at the code you'll
notice that the steps below are all embedded in a loop that retries several
times. This is mostly because of step 2 (downloading the source
distributions).

1. Run ``pip install --download=... --no-index -r requirements.txt`` to unpack
   source distributions available in the local source index. This is the first
   step because pip-accel should accept `requirements.txt` files as input but
   it will manually install dependencies from cached binary distributions
   (without using pip or easy_install):

  - If the command succeeds it means all dependencies are already available as
    downloaded source distributions. We'll parse the verbose pip output of step
    1 to find the direct and transitive dependencies (names and versions)
    defined in `requirements.txt` and use them as input for step 3.
    Go to step 3.

  - If the command fails it probably means not all dependencies are available
    as local source distributions yet so we should download them. Go to step 2.

2. Run ``pip install --download=... -r requirements.txt`` to download missing
   source distributions to the download cache:

  - If the command fails it means that pip encountered errors while scanning
    PyPI_, scanning a distribution website, downloading a source distribution
    or unpacking a source distribution. Usually these kinds of errors are
    intermittent so retrying a few times is worth a shot. Go to step 2.

  - If the command succeeds it means all dependencies are now available as
    local source distributions; we don't need the network anymore! Go to step 1.

3. Run ``python setup.py bdist_dumb --format=gztar`` for each dependency that
   doesn't have a cached binary distribution yet (taking version numbers into
   account). Go to step 4.

4. Install all dependencies from binary distributions based on the list of
   direct and transitive dependencies obtained in step 1. We have to do these
   installations manually because easy_install nor pip support binary
   ``*.tar.gz`` distributions.

Contact
-------

If you have questions, bug reports, suggestions, etc. please create an issue on
the `GitHub project page`_. The latest version of pip-accel will always be
available on GitHub. The internal API documentation is `hosted on Read The
Docs`_.

License
-------

This software is licensed under the `MIT license`_ just like pip_ (on which
pip-accel is based).

© 2014 Peter Odding and Paylogic_ International.


.. External references:
.. _.boto file: http://boto.readthedocs.org/en/latest/boto_config_tut.html
.. _Amazon S3 cache backend: http://pip-accel.readthedocs.org/en/latest/developers.html#module-pip_accel.caches.s3
.. _Amazon S3: http://aws.amazon.com/s3/
.. _behind a CDN: http://mail.python.org/pipermail/distutils-sig/2013-May/020848.html
.. _Binary distributions: http://docs.python.org/2/distutils/builtdist.html
.. _Boto: https://github.com/boto/boto
.. _documentation of the pip_accel.config module: http://pip-accel.readthedocs.org/en/latest/developers.html#module-pip_accel.config
.. _FakeS3: https://github.com/jubos/fake-s3
.. _GitHub project page: https://github.com/paylogic/pip-accel
.. _hosted on Read The Docs: https://pip-accel.readthedocs.org/
.. _issue #30 on GitHub: https://github.com/paylogic/pip-accel/issues/30
.. _local index of source distribution archives: http://www.pip-installer.org/en/latest/cookbook.html#fast-local-installs
.. _LXML: https://pypi.python.org/pypi/lxml
.. _M2Crypto: https://pypi.python.org/pypi/M2Crypto
.. _MIT license: http://en.wikipedia.org/wiki/MIT_License
.. _override the S3 API URL: http://pip-accel.readthedocs.org/en/latest/developers.html#pip_accel.config.Config.s3_cache_url
.. _Paylogic: http://www.paylogic.com/
.. _pip: http://www.pip-installer.org/
.. _PyPI: http://pypi.python.org/
.. _Python virtual environments: http://www.virtualenv.org/
.. _requirements files: http://www.pip-installer.org/en/latest/cookbook.html#requirements-files
.. _S3 compatible storage service: http://en.wikipedia.org/wiki/Amazon_S3#S3_API_and_competing_services
.. _Tox: https://tox.readthedocs.org/
