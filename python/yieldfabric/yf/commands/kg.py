"""
`yf kg count|retrieve` — the workspace knowledge endpoints on the agents host.

    yf kg count --workspace <working_group_id> --term T [--term T2 …]
                [--mode exact|phrase|fuzzy] [--kg <id> …] [--as-of <RFC 3339>]
    yf kg retrieve --workspace <working_group_id> --query Q
                   [--kg <id> …] [--set <set_id>] [--top-k N] [--min-score F]
                   [--as-of <RFC 3339>] [--effort standard|hard]

``count`` is exhaustive: a tally per term (``documents``, ``frames``),
never a rank. A ``*_capped`` tally is a floor ("at least"), and the
union is then unavailable. ``mode`` is ``exact`` by default (no
stemming — names, identifiers, clause numbers); ``phrase`` stems;
``fuzzy`` is a substring scan and must not be presented as a finding.

``retrieve`` is ranked: passages with citations, no synthesis. Read
``lanes.any_degraded`` before treating the results as everything the
corpus holds; ``--effort hard`` re-runs with a larger budget.

Knowledge is not chain-scoped: only the agents host is called, the
envelope carries no ``chain_id``/``mode``, the live guard does not run
(a session last minted on a live chain works without ``--live``), and no
payments host is needed for the resolved chain.
"""

from .. import errors
from ..context import Context
from ..output import error_from_rest

NAME = "kg"
#: Agents host only — no live guard, no payments host.
NEEDS_CHAIN = False
MODES = ("exact", "phrase", "fuzzy")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="knowledge: exhaustive counts and ranked retrieval in a workspace")
    sub = p.add_subparsers(dest="subcommand", metavar="<count|retrieve>")
    sub.required = True

    c = sub.add_parser("count", help="exhaustive per-term document counts in a workspace")
    c.add_argument("--workspace", "--group", dest="workspace", required=True, metavar="WORKING_GROUP_ID", help="workspace (working group) id")
    c.add_argument("--term", action="append", required=True, metavar="TERM", help="term to count (repeatable)")
    c.add_argument("--mode", choices=MODES, default="exact", help="match mode for every term (default exact)")
    c.add_argument("--kg", action="append", metavar="KG_ID", help="restrict to these knowledge graphs (repeatable)")
    c.add_argument("--as-of", metavar="RFC3339", help="pin the count to a corpus state")

    r = sub.add_parser("retrieve", help="ranked passages for a query in a workspace")
    r.add_argument("--workspace", "--group", dest="workspace", required=True, metavar="WORKING_GROUP_ID", help="workspace (working group) id")
    r.add_argument("--query", required=True, help="the question or phrase to retrieve for")
    r.add_argument("--kg", action="append", metavar="KG_ID", help="restrict to these knowledge graphs (repeatable)")
    r.add_argument("--set", dest="set_id", metavar="SET_ID", help="restrict to a frozen set (exclusive with --kg)")
    r.add_argument("--top-k", type=int, metavar="N", help="number of passages")
    r.add_argument("--min-score", type=float, metavar="F", help="minimum score")
    r.add_argument("--as-of", metavar="RFC3339", help="pin retrieval to a corpus state")
    r.add_argument("--effort", choices=("standard", "hard"), help="retrieval budget (hard = search harder re-run)")


def _run_count(ctx: Context, args) -> int:
    terms = [{"term": t, "mode": args.mode} for t in args.term if t and t.strip()]
    if not terms:
        raise errors.usage("term_required", "at least one non-empty --term is required")
    result = ctx.agents().count_documents(
        ctx.token,
        working_group_id=args.workspace,
        terms=terms,
        kg_ids=args.kg,
        as_of=args.as_of,
    )
    if not result.get("ok"):
        raise error_from_rest(result)
    body = result.get("body") if isinstance(result.get("body"), dict) else {}
    capped = [t.get("term") for t in body.get("terms") or [] if t.get("documents_capped") or t.get("frames_capped")]
    data = dict(body)
    data["workspace"] = args.workspace
    if capped or body.get("union_capped"):
        data["warning"] = (
            "capped tallies are floors (at least this many), not exact counts: "
            + ", ".join(str(t) for t in capped)
            if capped
            else "the union is capped: it is a floor, not an exact count"
        )
    return ctx.ok(data, chain=False)


def _run_retrieve(ctx: Context, args) -> int:
    if args.kg and args.set_id:
        raise errors.usage("scope_conflict", "--kg and --set are mutually exclusive")
    result = ctx.agents().retrieve_documents(
        ctx.token,
        working_group_id=args.workspace,
        query=args.query,
        kg_ids=args.kg,
        set_id=args.set_id,
        top_k=args.top_k,
        min_score=args.min_score,
        as_of=args.as_of,
        effort=args.effort,
    )
    if not result.get("ok"):
        raise error_from_rest(result)
    body = result.get("body") if isinstance(result.get("body"), dict) else {}
    data = dict(body)
    data["workspace"] = args.workspace
    lanes = body.get("lanes") if isinstance(body.get("lanes"), dict) else {}
    if lanes.get("any_degraded"):
        data["warning"] = "at least one retrieval lane did not finish: these results are partial; re-run with --effort hard"
    return ctx.ok(data, chain=False)


def run(ctx: Context, args) -> int:
    if args.subcommand == "count":
        return _run_count(ctx, args)
    if args.subcommand == "retrieve":
        return _run_retrieve(ctx, args)
    raise errors.usage("unknown_subcommand", f"unknown kg subcommand {args.subcommand!r}")
