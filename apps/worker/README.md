# Attribution worker host

Run `agenttrace-foundation worker --role attribution`. The process consumes only the agent-evidence development queue and atomically records a decision with job acknowledgement. It uses a separate SQL role with queue row security and an individual secret mount. Its current runtime adapter replays the authored public evidence contract. Separately verified Azure evidence/signing permissions are reserved for later ingestion integration. It cannot read Microsoft 365, send mail or operate an external agent.
