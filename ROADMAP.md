# Roadmap

This ordered maintenance plan covers the next twelve months. It is not a
delivery-date commitment. Changes are
proposed and prioritized using the issue/review process in GOVERNANCE.md.

1. Preserve source freshness, D-Bus lifecycle and independent channel recovery. Keep negative tests for invalid data and
   unavailable dependencies alongside every behavior change.
2. Maintain a source inventory and measured coverage for application code and
   locally maintained tooling; assess reused release tooling separately and
   retain the exact upstream revision and test evidence.
3. Finish the OpenSSF Passing assessment with project-specific owner facts.
   Complete Silver governance, continuity, regression-history and assurance
   evidence without asserting unverified criteria.
4. Publish and independently verify a release using the configured source/artifact
   signatures and recipient verifier. The implementation is present; a successful
   workflow configuration alone does not establish signed release evidence.
5. Keep dependencies updated, preserve the documented Venus OS/Python compatibility
   boundary, and record evidence for each supported environment.

Revisit this plan when a release changes a trust boundary or supported interface.
Progress is recorded in CHANGELOG.md and the evidence documents; an unchecked item
is intentionally unfinished.
