param location string
param namePrefix string
param environmentId string
param apiIdentityId string
param image string

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-api'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${apiIdentityId}': {} } }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: false, targetPort: 8080, transport: 'http', allowInsecure: false }
    }
    template: {
      containers: [{
        name: 'api'
        image: image
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
        // Fail closed until the later identity/network/configuration stage.
        env: [{ name: 'AGENTTRACE_ENVIRONMENT', value: 'unconfigured' }]
      }]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}
output apiId string = api.id
