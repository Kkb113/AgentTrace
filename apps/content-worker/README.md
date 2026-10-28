# Content worker host

Run `agenttrace-foundation worker --role content`. Its separate SQL role cannot read agent decisions or the agent queue. The running container has no external route and receives only its own database secret, with no Microsoft 365/history/signing credential. It reports health and stays in standby without a reviewed scorer, leaving content jobs unacknowledged. The stable port is `agenttrace_content_detection.ContentScorer`; actual statistical scoring remains the bounded later experiment.
