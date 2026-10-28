# Reproducible validation and protected releases

Status: GitHub Actions selected explicitly by the project owner.

Azure DevOps organization access exists, but creating the dedicated project returned TF50309 for missing Create new projects permission. The owner selected GitHub Actions for active PR checks and equivalent Azure Pipelines YAML. No organization permission or unrelated project was changed. Both definitions call the same checked-in Python gate commands. Azure YAML is retained and syntax/command checked; an Azure run is not claimed.

Quality, security, infrastructure, integration and negative-gate controls run on pull requests. Official Actions are pinned by commit; external validators are pinned by official release hash. PR jobs have contents:read only, no Azure token, no secrets, and checkout does not persist credentials. No pull_request_target code execution is configured.

Main must require these actual check contexts and a pull request, with force pushes/deletion disabled and administrators subject to checks. A solo-owner repository uses zero mandatory external approvals to avoid inventing a reviewer. If protection is unavailable, use a documented maintainer gate with recorded checks rather than claiming enforcement. Workload identity federation belongs to a separately authorized protected Azure connection: no PAT, client secret or broad cloud grant is needed for compile/test CI. The optional Azure what-if template is not connected or executed by default.
