targetScope = 'resourceGroup'

@description('Foundation validation defaults to creating no resources.')
param enableProvisioning bool = false

@allowed(['kb-agentdemo'])
param expectedResourceGroup string = 'kb-agentdemo'

@allowed(['eastus'])
param location string = 'eastus'

@minLength(3)
@maxLength(14)
param namePrefix string = 'agenttrace'

param deployDatabase bool = false
param deployRuntime bool = false
param containerImage string = ''
param managedEnvironmentId string = ''

@secure()
param databaseAdministratorPassword string = ''

var permitted = enableProvisioning && resourceGroup().name == expectedResourceGroup

module identities 'modules/identities.bicep' = if (permitted) {
  name: '${namePrefix}-identities'
  params: { location: location, namePrefix: namePrefix }
}

module storage 'modules/storage.bicep' = if (permitted) {
  name: '${namePrefix}-storage'
  params: { location: location, storageName: take('${namePrefix}${uniqueString(resourceGroup().id)}', 24) }
}

module secrets 'modules/secrets.bicep' = if (permitted) {
  name: '${namePrefix}-secrets'
  params: { location: location, vaultName: take('${namePrefix}-${uniqueString(resourceGroup().id)}', 24) }
}

module database 'modules/database.bicep' = if (permitted && deployDatabase) {
  name: '${namePrefix}-database'
  params: {
    location: location
    serverName: '${namePrefix}-${uniqueString(resourceGroup().id)}'
    administratorPassword: databaseAdministratorPassword
  }
}

module runtime 'modules/runtime.bicep' = if (permitted && deployRuntime && !empty(containerImage) && !empty(managedEnvironmentId)) {
  name: '${namePrefix}-runtime'
  params: {
    location: location
    namePrefix: namePrefix
    image: containerImage
    environmentId: managedEnvironmentId
    apiIdentityId: identities!.outputs.apiIdentityId
  }
}

output resourceGroupAccepted bool = resourceGroup().name == expectedResourceGroup
output createsResources bool = permitted
