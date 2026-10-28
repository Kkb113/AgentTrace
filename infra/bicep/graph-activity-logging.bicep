targetScope = 'resourceGroup'

@allowed(['kb-agentdemo'])
param expectedResourceGroup string = 'kb-agentdemo'
@allowed(['eastus'])
param location string = 'eastus'
param enableProvisioning bool = false
param readerPrincipalId string
param logDataReaderRoleId string
param transformationKql string
param attachExistingTransformation bool = false

var permitted = enableProvisioning && resourceGroup().name == expectedResourceGroup && !empty(transformationKql)
var suffix = uniqueString(resourceGroup().id, 'agenttrace-graph-activity')
var workspaceName = 'agenttrace-graph-${suffix}'
var ruleId = resourceId('Microsoft.Insights/dataCollectionRules', 'agenttrace-graph-${suffix}')
var tags = { project: 'AgentTrace', purpose: 'filtered-graph-activity', environment: 'synthetic-sandbox' }

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (permitted) {
  name: workspaceName
  location: location
  tags: tags
  properties: union({
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json('0.1') }
    features: { enableLogAccessUsingOnlyResourcePermissions: false }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }, attachExistingTransformation ? { defaultDataCollectionRuleResourceId: ruleId } : {})
}
resource graphTable 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = if (permitted) {
  parent: workspace
  name: 'MicrosoftGraphActivityLogs'
  properties: {
    plan: 'Analytics'
    retentionInDays: 7
    totalRetentionInDays: 7
    schema: { name: 'MicrosoftGraphActivityLogs' }
  }
}
resource rule 'Microsoft.Insights/dataCollectionRules@2023-03-11' = if (permitted) {
  name: 'agenttrace-graph-${suffix}'
  location: location
  tags: tags
  kind: 'WorkspaceTransforms'
  properties: {
    destinations: { logAnalytics: [{ name: 'filteredGraphWorkspace', workspaceResourceId: workspace.id }] }
    dataFlows: [{ streams: ['Microsoft-Table-MicrosoftGraphActivityLogs'], destinations: ['filteredGraphWorkspace'], transformKql: transformationKql }]
  }
}
resource readerGrant 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (permitted) {
  name: guid(workspace.id, readerPrincipalId, 'graph-table-read')
  scope: workspace
  properties: {
    principalId: readerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: logDataReaderRoleId
    conditionVersion: '2.0'
    condition: '((!(ActionMatches{\'Microsoft.OperationalInsights/workspaces/tables/data/read\'})) OR (@Resource[Microsoft.OperationalInsights/workspaces/tables:name] StringEquals \'MicrosoftGraphActivityLogs\'))'
  }
}
output workspaceResourceId string = permitted ? workspace.id : ''
output workspaceCustomerId string = permitted ? workspace!.properties.customerId : ''
output workspaceName string = permitted ? workspace.name : ''
output transformationRuleId string = permitted ? rule.id : ''
