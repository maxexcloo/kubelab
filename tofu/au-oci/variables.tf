variable "compartment_ocid" {
  description = "OCI compartment containing the existing hsp instance."
  type        = string

  validation {
    condition     = can(regex("^ocid1\\.compartment\\.", var.compartment_ocid))
    error_message = "The compartment OCID must start with ocid1.compartment."
  }
}
