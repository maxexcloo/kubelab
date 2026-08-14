resource "google_storage_bucket" "state" {
  name                        = var.state_bucket_name
  location                    = var.state_bucket_location
  project                     = var.gcp_project_id
  force_destroy               = false
  public_access_prevention    = "enforced"
  uniform_bucket_level_access = true

  retention_policy {
    retention_period = var.state_retention_seconds
  }

  versioning {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}
