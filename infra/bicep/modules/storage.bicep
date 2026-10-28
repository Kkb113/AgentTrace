param location string
param storageName string

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
  }
}
resource service 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: account
  name: 'default'
}
resource queues 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = [for name in ['agent-evidence', 'agent-evidence-poison', 'content-analysis', 'content-analysis-poison']: {
  parent: service
  name: name
}]
output storageId string = account.id
