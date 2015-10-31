Documentation for the pip accelerator API
=========================================

On this page you can find the complete API documentation of pip-accel
|release|.

A note about backwards compatibility
------------------------------------

Please note that pip-accel has not yet reached a 1.0 version and until that
time arbitrary changes to the API can be made. To clarify that statement:

- On the one hand I value API stability and I've built a dozen tools on top of
  pip-accel myself so I don't think too lightly about breaking backwards
  compatibility :-)

- On the other hand if I see opportunities to simplify the code base or make
  things more robust I will go ahead and do it. Furthermore the implementation
  of pip-accel is dictated (to a certain extent) by pip and this certainly
  influences the API. For example API changes may be necessary to facilitate
  the upgrade to pip 1.5.x (the current version of pip-accel is based on pip
  1.4.x).

In pip-accel 0.16 a completely new API was introduced and support for the old
"API" was dropped. The goal of the new API is to last for quite a while but of
course only time will tell if that plan is going to work out :-)

The Python API of pip-accel
---------------------------

Here are the relevant Python modules that make up pip-accel:

.. contents::
   :local:

:mod:`pip_accel`
~~~~~~~~~~~~~~~~

.. automodule:: pip_accel
   :members:

:mod:`pip_accel.config`
~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.config
   :members:

:mod:`pip_accel.req`
~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.req
   :members:

:mod:`pip_accel.bdist`
~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.bdist
   :members:

:mod:`pip_accel.caches`
~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.caches
   :members:

:mod:`pip_accel.caches.local`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.caches.local
   :members:

:mod:`pip_accel.caches.s3`
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.caches.s3
   :members:

:mod:`pip_accel.deps`
~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.deps
   :members:

:mod:`pip_accel.utils`
~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.utils
   :members:

:mod:`pip_accel.exceptions`
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.exceptions
   :members:

:mod:`pip_accel.tests`
~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: pip_accel.tests
   :members:
