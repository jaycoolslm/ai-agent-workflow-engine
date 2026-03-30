resource "azurerm_eventgrid_system_topic" "storage" {
  name                   = "${var.project_name}-storage-events"
  resource_group_name    = azurerm_resource_group.main.name
  location               = azurerm_resource_group.main.location
  source_arm_resource_id = azurerm_storage_account.workflows.id
  topic_type             = "Microsoft.Storage.StorageAccounts"

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_eventgrid_system_topic_event_subscription" "manifest_trigger" {
  name                = "manifest-created"
  system_topic        = azurerm_eventgrid_system_topic.storage.name
  resource_group_name = azurerm_resource_group.main.name

  azure_function_endpoint {
    function_id                       = "${azurerm_linux_function_app.router.id}/functions/router"
    max_events_per_batch              = 1
    preferred_batch_size_in_kilobytes = 64
  }

  included_event_types = [
    "Microsoft.Storage.BlobCreated",
  ]

  subject_filter {
    subject_ends_with = "manifest.json"
  }
}
