# Service Plan: Consumption (serverless, equivalent to Lambda pay-per-invocation)
resource "azurerm_service_plan" "router" {
  name                = "${var.project_name}-router-plan"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "Y1"

  tags = azurerm_resource_group.main.tags
}

# Dedicated storage account for the Function App's internal state (required by Azure Functions)
resource "azurerm_storage_account" "function_storage" {
  name                     = "${replace(substr(var.project_name, 0, 16), "-", "")}func"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_linux_function_app" "router" {
  name                       = "${var.project_name}-router"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  service_plan_id            = azurerm_service_plan.router.id
  storage_account_name       = azurerm_storage_account.function_storage.name
  storage_account_access_key = azurerm_storage_account.function_storage.primary_access_key

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.function_identity.id]
  }

  site_config {
    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    "STORAGE_ACCOUNT_NAME"              = azurerm_storage_account.workflows.name
    "CONTAINER_NAME"                    = local.container_name
    "ACR_LOGIN_SERVER"                  = azurerm_container_registry.agent.login_server
    "AGENT_IMAGE_TAG"                   = var.agent_image_tag
    "RESOURCE_GROUP_NAME"               = azurerm_resource_group.main.name
    "AZURE_REGION"                      = var.azure_region
    "KEYVAULT_URI"                      = azurerm_key_vault.main.vault_uri
    "CONTAINER_CPU"                     = tostring(var.container_cpu)
    "CONTAINER_MEMORY_GB"               = tostring(var.container_memory_gb)
    "MANAGED_IDENTITY_ID"               = azurerm_user_assigned_identity.container_identity.id
    "MANAGED_IDENTITY_CLIENT_ID"        = azurerm_user_assigned_identity.container_identity.client_id
    "SUBSCRIPTION_ID"                   = var.subscription_id
    "LOG_ANALYTICS_WORKSPACE_ID"        = azurerm_log_analytics_workspace.main.workspace_id
    "AGENT_RUNTIME"                     = "claude"
    "LLM_MODEL"                         = ""
    "AzureWebJobsStorage"               = azurerm_storage_account.function_storage.primary_connection_string
    "FUNCTIONS_WORKER_RUNTIME"           = "python"
    "FUNCTIONS_EXTENSION_VERSION"        = "~4"
    "WEBSITE_RUN_FROM_PACKAGE"           = "1"
    "AzureWebJobsFeatureFlags"           = "EnableWorkerIndexing"
  }

  tags = azurerm_resource_group.main.tags
}
