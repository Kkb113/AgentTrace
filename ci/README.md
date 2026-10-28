# Shared CI validation

Active PR validation uses .github/workflows/validation.yml per the owner's explicit choice after Azure project creation was denied. azure-pipelines.yml retains equivalent jobs and calls the same scripts/ci-checks.py gates. Azure source integration/hosted parallelism must be authorized before enabling it; no Azure run is claimed.

The optional templates/azure-what-if.yml requires a protected, narrowly group-scoped workload-identity-federated service connection. Create no secret or tenant application for compile-only CI. Do not authorize all pipelines or fork PRs to use that connection. Obtain the current issuer/subject from the actual connection rather than guessing a legacy issuer. All Azure operations must explicitly select the intended subscription and kb-agentdemo.
