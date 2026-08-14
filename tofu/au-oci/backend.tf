terraform {
  backend "gcs" {
    bucket = "homelab-opentofu"
    prefix = "states/kubelab-au-oci"
  }
}
