output "storage_account_name" {
  description = "Storage account for workflow manifests and data"
  value       = azurerm_storage_account.workflows.name
}

output "acr_login_server" {
  description = "ACR login server for the agent image"
  value       = azurerm_container_registry.agent.login_server
}

output "function_app_name" {
  description = "Azure Function router app name (for viewing logs)"
  value       = azurerm_linux_function_app.router.name
}

output "resource_group_name" {
  description = "Resource group containing all resources"
  value       = azurerm_resource_group.main.name
}

output "next_steps" {
  description = "Post-deployment instructions"
  value       = <<-EOT
    Deployment complete! Next: build and push the agent image, then trigger a workflow.

    # 1. Login to ACR
    az acr login --name ${azurerm_container_registry.agent.name}

    # 2. Build and push agent image for linux/amd64 (run from repo root)
    docker build --platform linux/amd64 -f Dockerfile.agent -t ${azurerm_container_registry.agent.login_server}/agent-workflow-engine/agent:${var.agent_image_tag} .
    docker push ${azurerm_container_registry.agent.login_server}/agent-workflow-engine/agent:${var.agent_image_tag}

    # 3. Trigger a workflow
    az storage blob upload --account-name ${azurerm_storage_account.workflows.name} --container-name ${local.container_name} --name runs/run_001/manifest.json --file sample-manifest.json --auth-mode login
  EOT
}
