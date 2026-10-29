targetScope = 'resourceGroup'

@allowed(['kb-agentdemo'])
param expectedResourceGroup string = 'kb-agentdemo'
@allowed(['eastus'])
param location string = 'eastus'
param enableProvisioning bool = false
param workspaceName string
param operatorPrincipalId string
param metricsPublisherRoleId string

var permitted = enableProvisioning && resourceGroup().name == expectedResourceGroup
var ruleName = 'agenttrace-route-${uniqueString(resourceGroup().id)}'

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}
resource table 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = if (permitted) {
  parent: workspace
  name: 'AgentTraceRouteCanary_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 7
    totalRetentionInDays: 7
    schema: {
      name: 'AgentTraceRouteCanary_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'CanaryId', type: 'string' }
        { name: 'ProbeKind', type: 'string' }
      ]
    }
  }
}
resource rule 'Microsoft.Insights/dataCollectionRules@2023-03-11' = if (permitted) {
  name: ruleName
  location: location
  kind: 'Direct'
  tags: { project: 'AgentTrace', purpose: 'synthetic-route-canary' }
  properties: {
    streamDeclarations: {
      'Custom-AgentTraceRouteCanary': {
        columns: [
          { name: 'TimeGenerated', type: 'datetime' }
          { name: 'CanaryId', type: 'string' }
          { name: 'ProbeKind', type: 'string' }
        ]
      }
    }
    destinations: { logAnalytics: [{ name: 'canaryWorkspace', workspaceResourceId: workspace.id }] }
    dataFlows: [{ streams: ['Custom-AgentTraceRouteCanary'], destinations: ['canaryWorkspace'], transformKql: 'source | project TimeGenerated, CanaryId, ProbeKind', outputStream: 'Custom-AgentTraceRouteCanary_CL' }]
  }
  dependsOn: [table]
}
resource publisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted) {
  name: guid(rule.id, operatorPrincipalId, 'synthetic-canary-publish')
  scope: rule
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: metricsPublisherRoleId
  }
}
output ruleResourceId string = permitted ? rule.id : ''
output publisherGrantId string = permitted ? publisher.id : ''
