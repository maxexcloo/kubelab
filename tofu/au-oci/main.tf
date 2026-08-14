data "oci_core_instances" "hsp" {
  compartment_id = var.compartment_ocid
  display_name   = "hsp"
}

locals {
  hsp_instances = [
    for instance in data.oci_core_instances.hsp.instances : instance
    if instance.state != "TERMINATED"
  ]
}

check "one_hsp_instance" {
  assert {
    condition     = length(local.hsp_instances) == 1
    error_message = "Expected exactly one non-terminated OCI instance named hsp."
  }
}

check "hsp_shape" {
  assert {
    condition = length(local.hsp_instances) != 1 || (
      one(local.hsp_instances).shape == "VM.Standard.A1.Flex" &&
      one(local.hsp_instances).shape_config[0].ocpus == 2 &&
      one(local.hsp_instances).shape_config[0].memory_in_gbs == 12
    )
    error_message = "hsp must remain an Ampere A1 instance with 2 OCPUs and 12 GB RAM."
  }
}
