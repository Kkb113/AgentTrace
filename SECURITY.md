# Security reporting and boundaries

Keep reports free of customer mail, credentials, tokens and raw tenant identifiers. Use the repository's private vulnerability-reporting capability when available; a public issue should contain only sanitized reproduction details. No client-specific certification is asserted by this POC.

Runtime mail-send/write rights and agent execution are excluded. The current foundation is synthetic-only and loopback-only. Production authentication, scoped source identities, private connectivity, retention deletion and deployment authorization are required in later milestones. The retired feasibility identity must not be reused without new authorized access.

Gitleaks, public-data checks, dependency/license checks and negative CI controls enforce repository hygiene. Dependency and artifact licenses require recorded evidence; an upstream repository license is not a substitute for weight/data rights. Treat email, source exports and model artifacts as untrusted input.
