# Content worker host

Run `agenttrace-foundation worker --role content`. This separate process reports database/worker health and remains in standby while no reviewed scorer is installed. It does not consume or acknowledge content jobs in that state. The stable inference port is `agenttrace_content_detection.ContentScorer`; actual statistical scoring remains the bounded later experiment.
