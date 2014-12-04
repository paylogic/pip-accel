#!/bin/bash -e

# We define the following environment variables to force Boto to use these
# credentials instead of falling back to the Amazon EC2 instance metadata
# server (which is obviously not available on a Travis CI worker running on
# OpenVZ :-). It doesn't matter to what values the environment variables are
# set because FakeS3 ignores the credentials given to it :-)
export AWS_ACCESS_KEY_ID=foo
export AWS_SECRET_ACCESS_KEY=bar

# These environment variables are used to configure pip-accel and its tests.
PIP_ACCEL_S3_PORT=12345
export PIP_ACCEL_S3_CREATE_BUCKET=true
export PIP_ACCEL_S3_URL="http://localhost:$PIP_ACCEL_S3_PORT"
export PIP_ACCEL_TEST_AUTO_INSTALL=true

# Start the FakeS3 server in the background.
fakes3 --root=/tmp/fakes3 --port=$PIP_ACCEL_S3_PORT &
FAKES3_PID=$!

# Give the FakeS3 server a moment to initialize.
sleep 10

# Run the test suite and collect coverage statistics.
coverage run --source=pip_accel setup.py test

# Kill the FakeS3 server.
kill -9 $FAKES3_PID
