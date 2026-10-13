# Staged native installation

A packaging host can capture the complete declared native payload without Venus
OS, SetupHelper, root privileges, network access or service activation:

```sh
DESTDIR="$PWD/stage" python3 install.py install
# Equivalent entry points:
DESTDIR="$PWD/stage" bash setup INSTALL
DESTDIR="$PWD/stage" sh update.sh
DESTDIR="$PWD/stage" python3 install.py uninstall
```

Files are installed below `$DESTDIR/data/dbus-emporia-vue`. The existing live
installer still uses `/data/dbus-emporia-vue` because boot hooks and service
commands require that prefix. `DESTDIR` adds a staging root; it does not rewrite
the runtime prefix. An empty `DESTDIR` or `/` is rejected by `install.py`.
Do not set `DESTDIR` when intentionally activating a package on a device.

Use a private directory with no concurrent writers. Symlinks, hardlinked files
and special files in source or destination paths are rejected. All source and
destination files are validated before copying starts. Executable bits are
preserved with normalized `0755`/`0644` modes. Dependency installation and live
boot/service changes are never performed by this staging path.

The fixed `PAYLOAD` list mirrors `.release-package.json` and the tracked native
files; its contract test fails if a package change is not reflected in the
staging list. Keep both declarations updated when changing the native payload.
Only example configuration is included. Local credentials, real configuration,
untracked files, caches, and live supervisor state are excluded. Uninstall reads
an allowlisted ownership manifest and removes only package files; operator-added
files and nonempty directories are preserved. This supports package inspection,
repackaging and static analysis without touching a running device.
