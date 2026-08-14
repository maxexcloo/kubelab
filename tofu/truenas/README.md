# TrueNAS Substrate

Create the first `au` Talos VM manually. This directory deliberately has no
provider configuration until the VM passes reboot and rebuild tests.

After the trial, evaluate the pinned `PjSalty/truenas` 2.x provider against the
installed TrueNAS release. Import the existing VM, add `prevent_destroy`, and
require a zero-drift plan before this stack becomes its owner. Storage datasets
and shares remain separate from VM lifecycle so a compute change cannot delete
application data.
