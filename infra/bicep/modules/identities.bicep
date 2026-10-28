param location string
param namePrefix string

resource workloads 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = [for role in ['collector', 'attribution', 'content', 'api']: {
  name: '${namePrefix}-${role}'
  location: location
  tags: { project: 'AgentTrace', purpose: role }
}]

// No Microsoft Graph grant, role assignment, secret or sender identity is created.
output apiIdentityId string = workloads[3].id
