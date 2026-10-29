targetScope = 'resourceGroup'

@allowed(['kb-agentdemo'])
param expectedResourceGroup string = 'kb-agentdemo'
@allowed(['eastus'])
param location string = 'eastus'
param enableProvisioning bool = false
@minLength(7)
@maxLength(15)
param operatorIpv4 string
param operatorPrincipalId string
param blobReaderRoleId string

var permitted = enableProvisioning && resourceGroup().name == expectedResourceGroup && !contains(operatorIpv4, '/') && operatorIpv4 != '0.0.0.0'
var accountName = 'atgraphdiag${uniqueString(resourceGroup().id)}'

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = if (permitted) {
  name: accountName
  location: location
  tags: { project: 'AgentTrace', purpose: 'owner-approved-raw-graph-diagnostic' }
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowCrossTenantReplication: false
    publicNetworkAccess: 'Enabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices', ipRules: [{ action: 'Allow', value: operatorIpv4 }] }
  }
}
resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = if (permitted) {
  parent: account
  name: 'default'
  properties: {
    isVersioningEnabled: false
    deleteRetentionPolicy: { enabled: false }
    containerDeleteRetentionPolicy: { enabled: false }
  }
}
resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = if (permitted) {
  parent: blobs
  name: 'insights-logs-microsoftgraphactivitylogs'
  properties: { publicAccess: 'None' }
}
resource expiry 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = if (permitted) {
  parent: account
  name: 'default'
  properties: {
    policy: {
      rules: [{ name: 'expire-graph-diagnostic-evidence', enabled: true, type: 'Lifecycle', definition: {
        filters: { blobTypes: ['blockBlob', 'appendBlob'], prefixMatch: ['insights-logs-microsoftgraphactivitylogs/'] }
        actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 7 } } }
      } }]
    }
  }
}
resource reader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted) {
  name: guid(container.id, operatorPrincipalId, 'graph-diagnostic-read')
  scope: container
  properties: { principalId: operatorPrincipalId, principalType: 'User', roleDefinitionId: blobReaderRoleId }
}
output storageAccountId string = permitted ? account.id : ''
output storageAccountName string = permitted ? account.name : ''
