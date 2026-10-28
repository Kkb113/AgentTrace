targetScope = 'resourceGroup'

@allowed(['kb-agentdemo'])
param expectedResourceGroup string = 'kb-agentdemo'
@allowed(['eastus'])
param location string = 'eastus'
param enableProvisioning bool = false
param operatorIpv4 string = ''
param operatorPrincipalId string = ''
param collectorPrincipalId string = ''
param auditPrincipalId string = ''
param attributionPrincipalId string = ''
param contentPrincipalId string = ''
param apiPrincipalId string = ''
param roleIds object = {}
param logWorkspaceId string = ''
param signingKeyExpiry int = 0
param assignKeyRoles bool = false

var permitted = enableProvisioning && resourceGroup().name == expectedResourceGroup && !empty(operatorIpv4) && !empty(roleIds) && signingKeyExpiry > 0
var suffix = uniqueString(resourceGroup().id, 'agenttrace-secure-access')
var tags = { project: 'AgentTrace', environment: 'synthetic-sandbox', milestone: 'secure-access' }

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = if (permitted) {
  name: 'agenttrace${suffix}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled'
    networkAcls: { bypass: 'None', defaultAction: 'Deny', ipRules: [{ value: operatorIpv4, action: 'Allow' }], virtualNetworkRules: [] }
  }
}
resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = if (permitted) {
  parent: storage
  name: 'default'
  properties: { isVersioningEnabled: false, deleteRetentionPolicy: { enabled: false }, containerDeleteRetentionPolicy: { enabled: false } }
}
resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for name in ['raw-evidence', 'scope-control']: if (permitted) {
  parent: blob
  name: name
  properties: { publicAccess: 'None' }
}]
resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = if (permitted) {
  parent: storage
  name: 'default'
}
resource queues 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = [for name in ['agent-evidence', 'content-analysis', 'agent-evidence-poison', 'content-analysis-poison']: if (permitted) {
  parent: queueService
  name: name
}]
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = if (permitted) {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [{
        name: 'expire-synthetic-raw-evidence'
        enabled: true
        type: 'Lifecycle'
        definition: { filters: { blobTypes: ['blockBlob'], prefixMatch: ['raw-evidence/'] }, actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 7 } } } }
      }]
    }
  }
}
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = if (permitted) {
  name: 'agenttrace-${suffix}'
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
    accessPolicies: []
    networkAcls: { bypass: 'None', defaultAction: 'Deny', ipRules: [{ value: '${operatorIpv4}/32' }], virtualNetworkRules: [] }
  }
}
resource operatorKeys 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted) {
  scope: vault
  name: guid(vault.id, operatorPrincipalId, 'key-bootstrap')
  properties: { principalId: operatorPrincipalId, principalType: 'User', roleDefinitionId: roleIds.?cryptoOfficer ?? '' }
}
// Key creation uses the operator data-plane call so the IP firewall is never bypassed.
resource signingKey 'Microsoft.KeyVault/vaults/keys@2023-07-01' existing = {
  parent: vault
  name: 'evidence-signing'
}
resource signerRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (permitted) {
  name: guid(resourceGroup().id, 'agenttrace-evidence-signer')
  properties: {
    roleName: 'AgentTrace Evidence Signer ${suffix}'
    description: 'Read public key and sign/verify evidence digests; no key administration or export.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{ actions: [], notActions: [], dataActions: ['Microsoft.KeyVault/vaults/keys/read', 'Microsoft.KeyVault/vaults/keys/sign/action', 'Microsoft.KeyVault/vaults/keys/verify/action'], notDataActions: [] }]
  }
}
resource verifierRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (permitted) {
  name: guid(resourceGroup().id, 'agenttrace-evidence-verifier')
  properties: {
    roleName: 'AgentTrace Evidence Verifier ${suffix}'
    description: 'Read public key and verify signatures; cannot sign or administer keys.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{ actions: [], notActions: [], dataActions: ['Microsoft.KeyVault/vaults/keys/read', 'Microsoft.KeyVault/vaults/keys/verify/action'], notDataActions: [] }]
  }
}
resource signerGrant 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted && assignKeyRoles) {
  scope: signingKey
  name: guid(signingKey.id, attributionPrincipalId, 'sign')
  properties: { principalId: attributionPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: signerRole.id }
}
resource verifierGrant 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted && assignKeyRoles) {
  scope: signingKey
  name: guid(signingKey.id, apiPrincipalId, 'verify')
  properties: { principalId: apiPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: verifierRole.id }
}
resource blobReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted) {
  scope: containers[0]
  name: guid(containers[0].id, attributionPrincipalId, 'read')
  properties: { principalId: attributionPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: roleIds.?blobReader ?? '' }
}
resource blobWriters 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principal in [collectorPrincipalId, auditPrincipalId]: if (permitted) {
  scope: containers[0]
  name: guid(containers[0].id, principal, 'write')
  properties: { principalId: principal, principalType: 'ServicePrincipal', roleDefinitionId: roleIds.?blobContributor ?? '' }
}]
var producers = [
  { principal: collectorPrincipalId, index: 0 }
  { principal: collectorPrincipalId, index: 1 }
  { principal: auditPrincipalId, index: 0 }
  { principal: attributionPrincipalId, index: 2 }
  { principal: contentPrincipalId, index: 3 }
]
resource queueSenders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for item in producers: if (permitted) {
  scope: queues[item.index]
  name: guid(queues[item.index].id, item.principal, 'enqueue')
  properties: { principalId: item.principal, principalType: 'ServicePrincipal', roleDefinitionId: roleIds.?queueSender ?? '' }
}]
resource queueConsumers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for item in [{ principal: attributionPrincipalId, index: 0 }, { principal: contentPrincipalId, index: 1 }]: if (permitted) {
  scope: queues[item.index]
  name: guid(queues[item.index].id, item.principal, 'process')
  properties: { principalId: item.principal, principalType: 'ServicePrincipal', roleDefinitionId: roleIds.?queueProcessor ?? '' }
}]
resource vaultLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (permitted && !empty(logWorkspaceId)) {
  scope: vault
  name: 'AgentTraceAccess'
  properties: { workspaceId: logWorkspaceId, logs: [{ category: 'AuditEvent', enabled: true }] }
}
resource blobLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (permitted && !empty(logWorkspaceId)) {
  scope: blob
  name: 'AgentTraceAccess'
  properties: { workspaceId: logWorkspaceId, logs: [for category in ['StorageRead', 'StorageWrite', 'StorageDelete']: { category: category, enabled: true }] }
}
resource queueLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (permitted && !empty(logWorkspaceId)) {
  scope: queueService
  name: 'AgentTraceAccess'
  properties: { workspaceId: logWorkspaceId, logs: [for category in ['StorageRead', 'StorageWrite', 'StorageDelete']: { category: category, enabled: true }] }
}
output createsResources bool = permitted
output storageName string = permitted ? storage.name : ''
output vaultName string = permitted ? vault.name : ''
output signingKeyName string = permitted ? signingKey.name : ''
