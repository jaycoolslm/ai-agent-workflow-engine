# =============================================================================
# PHASE 1: Broad permissions to validate e2e pipeline.
# Every broad assignment is marked with "PHASE 2: tighten" for scoping down.
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

# PHASE 2: tighten to custom role with only Microsoft.ContainerInstance/* actions
resource "azurerm_role_assignment" "function_aci_contributor" {
  scope                = azurerm_resource_group.main.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.function_identity.principal_id
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

# PHASE 2: scope down to specific container only
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
