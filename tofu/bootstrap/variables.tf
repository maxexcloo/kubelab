variable "gcp_project_id" {
  description = "GCP project containing the existing state bucket."
  type        = string
}

variable "state_bucket_location" {
  description = "Existing bucket location; it must match before import."
  type        = string
}

variable "state_bucket_name" {
  default     = "homelab-opentofu"
  description = "Existing GCS state bucket name."
  type        = string
}

variable "state_retention_seconds" {
  default     = 2592000
  description = "Minimum retention for state object versions (30 days)."
  type        = number

  validation {
    condition     = var.state_retention_seconds >= 604800
    error_message = "State retention must be at least seven days."
  }
}
