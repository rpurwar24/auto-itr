"""Provider plugins.

Each provider is ONE module in this package exposing a module-level `PROVIDER = Provider(...)`.
The registry auto-discovers them, so adding a new bank/broker/employer integration is a matter
of dropping a new file here - nothing else needs editing. See base.py for the contract.
"""
