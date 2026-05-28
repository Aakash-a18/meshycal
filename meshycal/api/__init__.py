"""HTTP surface for the MeshyCal web renderer.

This package is the BACKEND a Delegation #1 renderer (the Next.js app in
`web/`) talks to. It is intentionally NOT part of the Mesherra trust
layer — it's a thin domain adapter that, in later steps, will reach into
a per-principal SchedulingAgent + ObjectStore + ProvenanceLedger.

In the skeleton step the responses are synthetic. Each endpoint's TODO
points at the substrate it will eventually be backed by.
"""

from meshycal.api.app import create_app

__all__ = ["create_app"]
