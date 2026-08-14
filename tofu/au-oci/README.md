# au-oci Substrate

This stack is intentionally read-only. The existing `hsp` VM and its network
are still owned by the `homelab` state, so declaring resources here would risk
two owners or a duplicate host.

Run a plan to verify that exactly one non-terminated `hsp` exists in Sydney and
still uses the expected Always Free A1 shape. Before this stack manages it:

1. pass the complete `au` home-cluster exit gate;
2. save and review the old and new state backups;
3. add the exact desired Talos image, boot volume, VNIC, NSG, and network
   resources here with `prevent_destroy` on persistent substrate;
4. transfer each resource out of the old state and import it here; and
5. require a zero-drift plan before changing or resetting the instance.

Resetting `hsp` is destructive and remains a separate, explicit approval.
