"""
`yf` — the YieldFabric command-line client.

A thin, scriptable front end over the service clients in
``yieldfabric.services`` (auth, payments, agents). It is distinct from
the YAML harness driver exposed as the ``yieldfabric`` script
(``yieldfabric.cli``): that one runs command files against a backend,
this one runs a single operation per invocation and speaks a stable
``--json`` contract for agents and shell pipelines.

Configuration comes from ``YF_*`` environment variables and flags only —
never from a ``.env`` in the working directory.
"""
