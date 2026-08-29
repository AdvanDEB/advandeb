"""
tDEB — Dynamic Energy Budget modelling with transport networks.

Ported from the standalone ``sciom/advanDEB_tDEB_simulator`` prototype into the
AdvanDEB platform, where models are owned by a user and persisted rather than
held in process memory.

Deliberately re-exports nothing. ``app.tdeb.core`` is pure simulation — numpy,
scipy and asteval only — and re-exporting persistence here would drag app
settings and a MongoDB client in behind it, so the engine could not be exercised
or reused without a configured environment. Import what you need directly::

    from app.tdeb.core import Solver, build_template   # simulation
    from app.tdeb.service import TDebModelService      # persistence
"""
