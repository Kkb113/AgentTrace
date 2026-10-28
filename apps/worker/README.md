# Attribution worker host

Run `agenttrace-foundation worker --role attribution`. The process consumes only the agent-evidence development queue and atomically records a decision with job acknowledgement. Its current adapter replays the authored public evidence contract. It cannot send mail or operate an external agent.
