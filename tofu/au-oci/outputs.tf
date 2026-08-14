output "hsp" {
  description = "Read-only identity used to review the future state transfer."
  value = length(local.hsp_instances) == 1 ? {
    availability_domain = one(local.hsp_instances).availability_domain
    id                  = one(local.hsp_instances).id
    shape               = one(local.hsp_instances).shape
  } : null
}
