# Pardus Domain Joiner library

Shared library used by the Pardus Domain Joiner GUI and CLI.

## Tests

The join validation tests run without root access, a domain controller, or an
installed package:

```sh
LANG=C.UTF-8 python3 -m unittest discover -s tests -v
```

They check that invalid organizational units are rejected before service, PAM,
discovery, or configuration operations. They also cover direct backend handler
calls, the default container, valid OU arguments, and existing error results.
Privileged operations, network operations, and file logging are substituted;
these are not end-to-end domain membership tests.

Meson runs the same tests, including during the Debian package build:

```sh
meson setup build
meson test -C build --print-errorlogs
```

To run the tests against another source revision, set
`PARDUS_DOMAIN_JOINER_SOURCE` to its absolute `src` directory.
