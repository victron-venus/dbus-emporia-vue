# Roadmap

This ordered maintenance plan covers the next twelve months. It is not a
delivery-date commitment. Changes are
proposed and prioritized using the issue/review process in GOVERNANCE.md.

1. Preserve source freshness, D-Bus lifecycle and independent channel recovery. Keep negative tests for invalid data and
   unavailable dependencies alongside every behavior change.
2. Maintain a source inventory and measured coverage for application code and
   locally maintained tooling; assess reused release tooling separately and
   retain the exact upstream revision and test evidence.
3. Maintain the awarded Passing level and complete the remaining Silver
   requirements, including a real continuity arrangement. Reassess governance,
   regression history and assurance evidence without asserting unverified criteria.
4. Repeat source/artifact signature verification and applicable target acceptance
   for each release. [Stable v1.0.9 evidence](docs/release-acceptance.md) records
   the first completed signed stable in this process; preserve its limitations.
5. Keep dependencies updated, preserve the documented Venus OS/Python compatibility
   boundary, and record evidence for each supported environment.

Revisit this plan when a release changes a trust boundary or supported interface.
Progress is recorded in CHANGELOG.md and the evidence documents; an unchecked item
is intentionally unfinished.
