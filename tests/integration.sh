#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# This fails instead of running against the host if unshare is unavailable.
exec unshare --user --map-root-user --mount --net sh -ec '
  mount --make-rprivate /
  export APPWIRE_TEST_ISOLATED=1
  exec python tests/integration.py
'
