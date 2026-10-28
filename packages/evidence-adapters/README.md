# Read-only evidence adapters

`EvidenceReader` exposes only reading an existing evidence bundle. `AuthoredExampleReader` resolves one allowlisted public example; it cannot open a caller-supplied file path or invoke a source tool. Future authenticated Graph/audit collectors must implement separate scoped read adapters.
