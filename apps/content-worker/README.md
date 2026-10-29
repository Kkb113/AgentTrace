# Content worker host

**Legacy component:** AI-generated-content detection was removed from the active release on 29 October 2026. The existing v1 worker/profile is retained until compatibility migration; do not deploy or schedule it in the new sender-only profile. The commands below describe historical behavior, not a current release requirement.

Run `agenttrace-foundation worker --role content`. Its separate SQL role cannot read agent decisions or the agent queue. The running container has no external route and receives only its own database secret, with no Microsoft 365/history/signing credential. It reports health and stays in standby without a reviewed scorer, leaving content jobs unacknowledged. The stable port is `agenttrace_content_detection.ContentScorer`; actual statistical scoring remains the bounded later experiment.
