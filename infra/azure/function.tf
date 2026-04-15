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

# Container for the function deployment package
resource "azurerm_storage_container" "function_releases" {
  name               = "function-releases"
  storage_account_id = azurerm_storage_account.function_storage.id
}

# Build function code with dependencies locally, then zip it.
# This mirrors what `func azure functionapp publish` does.
resource "null_resource" "build_function" {
  triggers = {
    source_hash = sha256(join("", [
      filesha256("${path.module}/function/function_app.py"),
      filesha256("${path.module}/function/host.json"),
      filesha256("${path.module}/function/requirements.txt"),
    ]))
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      BUILD_DIR="${path.module}/.build/function_pkg"
      rm -rf "$BUILD_DIR"
      mkdir -p "$BUILD_DIR"
      cp ${path.module}/function/function_app.py ${path.module}/function/host.json ${path.module}/function/requirements.txt "$BUILD_DIR/"
      grep -v '^azure-functions' ${path.module}/function/requirements.txt > "$BUILD_DIR/requirements-deploy.txt"
      python3 -m pip install -r "$BUILD_DIR/requirements-deploy.txt" -t "$BUILD_DIR/.python_packages/lib/site-packages" --quiet --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12
      rm "$BUILD_DIR/requirements-deploy.txt"
    EOT
  }
}

# Zip the built function (source + installed dependencies)
data "archive_file" "function_code" {
  type        = "zip"
  source_dir  = "${path.module}/.build/function_pkg"
  output_path = "${path.module}/.build/function.zip"
  depends_on  = [null_resource.build_function]
}

# Upload the zip to blob storage
resource "azurerm_storage_blob" "function_zip" {
  name                   = "function-${data.archive_file.function_code.output_base64sha256}.zip"
  storage_account_name   = azurerm_storage_account.function_storage.name
  storage_container_name = azurerm_storage_container.function_releases.name
  type                   = "Block"
  source                 = data.archive_file.function_code.output_path
  content_md5            = data.archive_file.function_code.output_md5
}

# SAS token for the Function App to read the package from blob storage
data "azurerm_storage_account_sas" "function_sas" {
  connection_string = azurerm_storage_account.function_storage.primary_connection_string
  https_only        = true
  signed_version    = "2022-11-02"

  start  = "2026-01-01T00:00:00Z"
  expiry = "2028-01-01T00:00:00Z"

  resource_types {
    service   = false
    container = false
    object    = true
  }

  services {
    blob  = true
    queue = false
    table = false
    file  = false
  }

  permissions {
    read    = true
    write   = false
    delete  = false
    list    = false
    add     = false
    create  = false
    update  = false
    process = false
    tag     = false
    filter  = false
  }
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
    "STORAGE_ACCOUNT_NAME"               = azurerm_storage_account.workflows.name
    "CONTAINER_NAME"                     = local.container_name
    "ACR_LOGIN_SERVER"                   = azurerm_container_registry.agent.login_server
    "AGENT_IMAGE_TAG"                    = var.agent_image_tag
    "RESOURCE_GROUP_NAME"                = azurerm_resource_group.main.name
    "AZURE_REGION"                       = var.azure_region
    "KEYVAULT_URI"                       = azurerm_key_vault.main.vault_uri
    "CONTAINER_CPU"                      = tostring(var.container_cpu)
    "CONTAINER_MEMORY_GB"                = tostring(var.container_memory_gb)
    "FUNCTION_IDENTITY_CLIENT_ID"        = azurerm_user_assigned_identity.function_identity.client_id
    "MANAGED_IDENTITY_ID"                = azurerm_user_assigned_identity.container_identity.id
    "MANAGED_IDENTITY_CLIENT_ID"         = azurerm_user_assigned_identity.container_identity.client_id
    "SUBSCRIPTION_ID"                    = var.subscription_id
    "LOG_ANALYTICS_WORKSPACE_ID"         = azurerm_log_analytics_workspace.main.workspace_id
    "LOG_ANALYTICS_WORKSPACE_KEY"        = azurerm_log_analytics_workspace.main.primary_shared_key
    "APPINSIGHTS_INSTRUMENTATIONKEY"     = azurerm_application_insights.main.instrumentation_key
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main.connection_string
    "AGENT_RUNTIME"                      = var.agent_runtime
    "LLM_MODEL"                          = var.llm_model
    "AzureWebJobsStorage"                = azurerm_storage_account.function_storage.primary_connection_string
    "FUNCTIONS_WORKER_RUNTIME"           = "python"
    "FUNCTIONS_EXTENSION_VERSION"        = "~4"
    "AzureWebJobsFeatureFlags"           = "EnableWorkerIndexing"
    "WEBSITE_RUN_FROM_PACKAGE"           = "https://${azurerm_storage_account.function_storage.name}.blob.core.windows.net/${azurerm_storage_container.function_releases.name}/${azurerm_storage_blob.function_zip.name}${data.azurerm_storage_account_sas.function_sas.sas}"
  }

  tags = azurerm_resource_group.main.tags
}

# Wait for Azure to mount the package and index the function
resource "null_resource" "wait_for_function_registration" {
  triggers = {
    code_hash = data.archive_file.function_code.output_base64sha256
  }

  depends_on = [azurerm_linux_function_app.router]

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      echo "Waiting for function to register..."
      for i in $(seq 1 20); do
        RESULT=$(az functionapp function list \
          --name ${azurerm_linux_function_app.router.name} \
          --resource-group ${azurerm_resource_group.main.name} \
          -o json 2>/dev/null)
        COUNT=$(echo "$RESULT" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
        if [ "$COUNT" -gt 0 ]; then
          echo "Function registered after $((i * 10))s"
          exit 0
        fi
        echo "Attempt $i/20: function not yet registered, waiting 10s..."
        sleep 10
      done
      echo "ERROR: Function did not register after 200s"
      exit 1
    EOT
  }
}
