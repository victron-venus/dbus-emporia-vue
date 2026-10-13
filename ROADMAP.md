# Roadmap

This is an ordered maintenance plan, not a delivery-date commitment. Changes are
proposed and prioritized using the issue/review process in GOVERNANCE.md.

1. Preserve source freshness, D-Bus lifecycle and independent channel recovery. Keep negative tests for invalid data and
   unavailable dependencies alongside every behavior change.
2. Maintain a source inventory and measured coverage for application code and
   locally maintained tooling; assess reused release tooling separately and
   retain the exact upstream revision and test evidence.
3. Finish the OpenSSF Passing assessment with project-specific owner facts.
   Complete Silver governance, continuity, regression-history and assurance
   evidence without asserting unverified criteria.
4. Add cryptographically verifiable source/artifact release signatures and
   recipient verification through the reviewed common release implementation.
   Checksums alone do not satisfy that work.
5. Keep dependencies updated, preserve the documented Venus OS/Python compatibility
   boundary, and record evidence for each supported environment.

Revisit this plan when a release changes a trust boundary or supported interface.
Progress is recorded in CHANGELOG.md and the evidence documents; an unchecked item
is intentionally unfinished.
