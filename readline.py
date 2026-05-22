"""No-op readline shim for local pytest startup.

Pytest imports ``readline`` during capture setup. In this sandboxed macOS
environment the platform readline extension can segfault before tests collect.
The homework code does not depend on readline behavior, so this module keeps
local checks deterministic.
"""

