# Static-analysis review notes

Keep executable source in the analysis scope. Investigate findings individually;
a documented assessment does not close an issue in the scanning service or waive
a required check. The following reviews concern the exact reported data flows.

## Release preparation: `pythonsecurity:S8707`

[This finding](https://sonarcloud.io/project/issues?id=victron-venus_dbus-emporia-vue&open=AaEbp_t9m35GeKIG6ytg)
tracks CLI `--version` through `prepare_version.prepare()` to `body.write_text()`.
The reviewed flow is a false positive: `choose_version()` accepts an explicit
version only when it fully matches the ASCII numeric `X.Y.Z` expression
`version_plan.BASE`. The accepted version enters the document **contents**.
The receiver is `Path(temp) / "pr-body.md"`, with `temp` created independently by
`TemporaryDirectory`; no version-derived component selects that path.

The preparation regression rejects traversal, absolute-path, option-like,
control-character and Unicode version inputs before synchronization or
preparation-branch handling. It checks that files, refs, worktrees, pushes and
PR creation remain unchanged. The existing success cases use real local Git
repositories and worktrees with simulated GitHub transport.

## Versioned publication: `pythonsecurity:S2083`

[This finding](https://sonarcloud.io/project/issues?id=victron-venus_dbus-emporia-vue&open=AaEbp_oUm35GeKIG6ytd)
tracks the parsed release plan to `(stage / rc.MANIFEST).write_bytes(content)` in
`release_versioned.publish_versioned()`. The reviewed flow is a false positive:
plan fields enter a manifest mapping and are serialized by `rc.json_bytes()` as
file **contents**. The receiver uses a newly created private temporary directory
and the literal `release-manifest.json`. Neither the plan nor the `--assets`
argument selects that filename. Asset staging rejects symlinks and the reserved
manifest filename and creates staged payload files exclusively.

The versioned-release lifecycle tests exercise real local manifest writes with
simulated GitHub transport, preserving plan, source and artifact identity.
Run both focused suites from a development environment:

```sh
python3 -m unittest discover -s .github/release-tests -p test_prepare_version.py
python3 -m unittest discover -s .github/release-tests -p test_versioned_release.py
```

These conclusions do not establish the safety of every release-policy path,
arbitrary imported code, hostile same-user filesystem changes, or external tools.
Reassess the findings if the receivers or their construction change.
