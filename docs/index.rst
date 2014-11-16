Documentation for the pip accelerator
=====================================

The pip accelerator makes `pip <http://www.pip-installer.org/>`_ (the Python
package manager) faster by keeping pip off the internet when possible and by
caching compiled binary distributions. It can bring a 10 minute run of ``pip``
down to less than a minute. You can find the pip accelerator in the following
places:

- The source code lives on `GitHub <https://github.com/paylogic/pip-accel>`_
- Downloads are available in the `Python Package Index <https://pypi.python.org/pypi/pip-accel>`_
- Online documentation is hosted by `Read The Docs <https://pip-accel.readthedocs.org/>`_

This is the documentation for version |release| of the pip accelerator. The
documentation consists of two parts:

- The documentation for users of the ``pip-accel`` command
- The documentation for developers who wish to extend and/or embed the
  functionality of ``pip-accel``

Introduction & usage
--------------------

The first part of the documentation is the readme which is targeted at users of
the ``pip-accel`` command. Here are the topics discussed in the readme:

.. toctree::
   :maxdepth: 2

   users.rst

Internal API documentation
--------------------------

The second part of the documentation is targeted at developers who wish to
extend and/or embed the functionality of ``pip-accel``. Here are the contents
of the API documentation:

.. toctree::
   :maxdepth: 3

   developers.rst
