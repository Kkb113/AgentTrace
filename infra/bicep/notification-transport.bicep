targetScope = 'resourceGroup'

@allowed(['kb-agentdemo'])
param expectedResourceGroup string = 'kb-agentdemo'
@allowed(['eastus'])
param location string = 'eastus'


@description('Explicitly opt in to the accepted metadata-only transport.')
param enableProvisioning bool = false
param operatorIpv4 string
param operatorPrincipalId string
param collectorPrincipalId string
param queueContributorRoleId string
param queueProcessorRoleId string
param blobContributorRoleId string
param graphPartnerRegistrationId string
param partnerAuthorizationExpiry string

var permitted = enableProvisioning && resourceGroup().name == expectedResourceGroup && !empty(operatorIpv4)
var storageName = 'atnotify${uniqueString(resourceGroup().id)}'
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = if (permitted) {
  name: storageName
  location: location
  tags: { project: 'AgentTrace', purpose: 'synthetic-notification-metadata' }
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: [{ value: operatorIpv4, action: 'Allow' }]
      virtualNetworkRules: []
    }
  }
}
resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = if (permitted) {
  parent: storage
  name: 'default'
}
resource notifications 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = if (permitted) {
  parent: queueService
  name: 'mail-notifications'
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = if (permitted) {
  parent: storage
  name: 'default'
  properties: { isVersioningEnabled: false, deleteRetentionPolicy: { enabled: false }, containerDeleteRetentionPolicy: { enabled: false } }
}
resource deadLetters 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = if (permitted) {
  parent: blobService
  name: 'notification-deadletters'
  properties: { publicAccess: 'None' }
}
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = if (permitted) {
  parent: storage
  name: 'default'
  properties: {
    policy: { rules: [{ name: 'expire-notification-deadletters', enabled: true, type: 'Lifecycle', definition: { filters: { blobTypes: ['blockBlob'], prefixMatch: ['notification-deadletters/'] }, actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 7 } } } } }] }
  }
}
resource operatorQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted) {
  name: guid(notifications.id, operatorPrincipalId, queueContributorRoleId)
  scope: notifications
  properties: { principalId: operatorPrincipalId, principalType: 'User', roleDefinitionId: queueContributorRoleId }
}
resource collectorQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted) {
  name: guid(notifications.id, collectorPrincipalId, queueProcessorRoleId)
  scope: notifications
  properties: { principalId: collectorPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: queueProcessorRoleId }
}
resource operatorDeadLetters 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted) {
  name: guid(deadLetters.id, operatorPrincipalId, blobContributorRoleId)
  scope: deadLetters
  properties: { principalId: operatorPrincipalId, principalType: 'User', roleDefinitionId: blobContributorRoleId }
}
resource partner 'Microsoft.EventGrid/partnerConfigurations@2022-06-15' = if (permitted) {
  name: 'default'
  location: 'global'
  tags: { project: 'AgentTrace', purpose: 'synthetic-notification-metadata' }
  properties: { partnerAuthorization: { defaultMaximumExpirationTimeInDays: 1, authorizedPartnersList: [{ partnerRegistrationImmutableId: graphPartnerRegistrationId, authorizationExpirationTimeInUtc: partnerAuthorizationExpiry }] } }
}
output storageAccountName string = permitted ? storage.name : ''
output queueResourceId string = permitted ? notifications.id : ''
output deadLetterResourceId string = permitted ? deadLetters.id : ''
