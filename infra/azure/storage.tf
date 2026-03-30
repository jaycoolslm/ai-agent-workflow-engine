resource "azurerm_storage_account" "workflows" {
  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  blob_properties {
    versioning_enabled = true
  }

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_storage_container" "workflows" {
  name                  = local.container_name
  storage_account_id    = azurerm_storage_account.workflows.id
  container_access_type = "private"
}
