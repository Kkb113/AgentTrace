# Fictional signed evidence contract

This is an authored, offline contract example. No email was sent. All identities use fictional aliases and `.invalid` addresses. A one-use private key was generated in memory to sign these example records and was not retained. The included public key is a test trust root, not a production issuer or a Claude/Microsoft key.

The example tests the conditional rule: if a trusted, valid source supplies an actor-specific completed send and an exact authorized message/digest mapping, the primary finding is verified-agent while content remains unknown. It does not demonstrate that the current live Claude connector exports such records, independent creation history, or measured detection accuracy.

The CLI reads only `observations.json`, `evidence.json`, referenced EML and the explicitly supplied trust profile. Tests keep their expected outcomes separate. Replaying identical evidence does not create independent statistical samples. Do not copy this profile into a live environment or sign reconstructed operator assertions and call them vendor evidence.
