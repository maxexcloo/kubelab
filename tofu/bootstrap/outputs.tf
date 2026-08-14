output "state_bucket" {
  description = "The protected GCS bucket used by independent OpenTofu states."
  value       = google_storage_bucket.state.name
}
