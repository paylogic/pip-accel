Documentation for the pip accelerator API
=========================================

On this page you can find the complete API documentation of pip-accel
|release|. Please note that pip-accel has not yet reached a 1.0 version and
until that time arbitrary changes to the API can be made. To clarify that
statement:

- On the one hand I value API stability and I've built a dozen tools on top of
  pip-accel myself so I don't think too lightly about breaking backwards
  compatibility :-)

- On the other hand if I see opportunities to simplify the code base or make
  things more robust I will go ahead and do it. Furthermore the implementation
  of pip-accel is dictated (to a certain extent) by pip and this certainly
  influences the API. For example API changes may be necessary to facilitate
  the upgrade to pip 1.5.x (the current version of pip-accel is based on pip
  1.4.x).

Here are the relevant Python modules that make up pip-accel:

.. contents::
   :local:

.. automodule:: pip_accel
   :members:

.. automodule:: pip_accel.req
   :members:

.. automodule:: pip_accel.bdist
   :members:

.. automodule:: pip_accel.caches
   :members:

.. automodule:: pip_accel.caches.local
   :members:

.. automodule:: pip_accel.caches.s3
   :members:

.. automodule:: pip_accel.deps
   :members:

.. automodule:: pip_accel.utils
   :members:
