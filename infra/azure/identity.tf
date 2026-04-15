# =============================================================================
# PHASE 2: Least-privilege IAM — every assignment scoped to specific resources.
# =============================================================================

# -----------------------------------------------------------------------------
# Identity 1: Function Identity (equivalent to Lambda execution role)
# Needs: read/write blobs, create ACI container groups, read Key Vault secrets
# -----------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "function_identity" {
  name                = "${var.project_name}-function-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

resource "azurerm_role_assignment" "function_blob_contributor" {
  scope                = azurerm_storage_account.workflows.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.function_identity.principal_id
}

# Custom role: only ACI container-group operations (replaces Contributor on RG)
resource "azurerm_role_definition" "aci_operator" {
  name        = "${var.project_name}-aci-operator"
  scope       = azurerm_resource_group.main.id
  description = "Least-privilege role for creating and managing ACI container groups"

  permissions {
    actions = [
      "Microsoft.ContainerInstance/containerGroups/read",
      "Microsoft.ContainerInstance/containerGroups/write",
      "Microsoft.ContainerInstance/containerGroups/delete",
      "Microsoft.ContainerInstance/containerGroups/start/action",
      "Microsoft.ContainerInstance/containerGroups/stop/action",
      "Microsoft.ContainerInstance/containerGroups/restart/action",
      "Microsoft.ContainerInstance/containerGroups/containers/logs/read",
    ]
    not_actions = []
  }

  assignable_scopes = [
    azurerm_resource_group.main.id,
  ]
}

resource "azurerm_role_assignment" "function_aci_operator" {
  scope              = azurerm_resource_group.main.id
  role_definition_id = azurerm_role_definition.aci_operator.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.function_identity.principal_id
}

resource "azurerm_role_assignment" "function_keyvault_reader" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.function_identity.principal_id
}

# -----------------------------------------------------------------------------
# Identity 2: Container Identity (equivalent to ECS task + execution roles)
# Needs: read/write blobs, pull from ACR, read Key Vault secrets
# -----------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "container_identity" {
  name                = "${var.project_name}-container-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

resource "azurerm_role_assignment" "container_blob_contributor" {
  scope                = azurerm_storage_account.workflows.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.container_identity.principal_id
}

resource "azurerm_role_assignment" "container_acr_pull" {
  scope                = azurerm_container_registry.agent.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.container_identity.principal_id
}

resource "azurerm_role_assignment" "container_keyvault_reader" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.container_identity.principal_id
}
