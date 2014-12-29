#!/bin/bash -e

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
