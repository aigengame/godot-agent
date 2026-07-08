"""The system-dynamics state model of the run's growth/economy (gADR-0011, #440).

The macro half of the Balancing pipeline: a first-order nonlinear ODE system
over the run's **stocks** (accumulating state) and **flows** (their rates),
integrated by the hand-rolled RK4 (``integrate``) across the Wave schedule to
predict the long-term growth/economy trajectory. Where the Monte-Carlo engine
(``encounter``) simulates ONE encounter at micro fidelity, this model is the
mean-field aggregate of the whole run — deterministic, no RNG.

Stocks (the state vector, in order):

- ``Q``    — the current Wave's remaining aggregate enemy HP (depletes to clear).
- ``HP``   — the Player's health, bounded ``[0, player_max_hp]`` (the survival
  stock; carried across Waves in the chained run, like the game).
- ``EXP``  — cumulative EXP (the growth stock; Level is its readout via the
  Leveling curve, gADR-0006).
- ``GOLD`` — cumulative Gold (economy inflow = the guaranteed Kill reward PLUS
  the expected gold Pickup drops; no sink in this demo — no shop — so it is an
  accumulator, documented).
- ``BUN``  — Bun Consumable count (economy in AND out: drops in, HP-restore use
  out — the balancing loop).
- ``WINE`` — Wine Consumable count (economy in only here: its MP-restore sink is
  the Gravity Gun, which is out of the combat model's scope — same honest
  scoping the targets file makes for the Gravity Gun; documented).

Flows (the ODE right-hand side), per Wave ``w`` with coefficients projected from
the JSON authority (``build_wave_dynamics``):

- ``dQ/dt   = -P``                      — the Player's effective damage rate
  ``P = player_dps_w * growth(EXP)`` drains the Wave's enemy HP.
- ``dHP/dt  = -enemy_dps_w + heal``     — incoming aggregate enemy DPS, offset by
  Bun healing (``heal``).
- ``dEXP/dt  = (exp_reward_w  / wave_hp_w) * P``   — reward accrues in proportion
- ``dGOLD/dt = (gold_reward_w / wave_hp_w) * P``     to the fraction of the
- ``dBUN/dt  = (bun_drops_w   / wave_hp_w) * P - consume``  Wave's HP destroyed,
- ``dWINE/dt = (wine_drops_w  / wave_hp_w) * P``     so integrating a fully
  cleared Wave yields EXACTLY its total reward (the conservation the unit tests
  pin) — the continuous mean-field of the game's discrete per-kill rewards.

The nonlinearities that make this a genuine first-order NONLINEAR ODE system —
the two coupled system-dynamics feedback loops plus the difficulty driver:

- **Reinforcing growth loop** — ``growth(EXP) = 1 + growth_gain * (Level(EXP) - 1)``
  feeds the growth stock back into the kill rate through the piecewise Leveling
  curve (more kills → more EXP → higher Level → faster kills). ``growth_gain``
  defaults to 0.0 (Phase-1 fidelity: level-up is readout-only today, gADR-0006),
  so it is an explicit, documented design lever; setting it > 0 predicts the
  INTENDED growth curve.
- **Balancing consumable loop** — Bun healing is a state-switched, supply-limited,
  saturating term: it engages only while ``HP < heal_threshold_frac * max`` AND
  ``BUN > 0``, restores toward ``player_max_hp`` (the cap — a ``min`` saturation),
  and drains the Bun stock. The threshold switch, the supply gate, and the cap
  are all nonlinear in the state.
- **Difficulty ramp** — the exogenous forcing: each Wave's ``enemy_dps_w`` /
  ``wave_hp_w`` step up across the schedule (the driving function the loops
  respond to).

Cross-validation overlap with the MC engine (``prediction``): in the reduced
"bare laser-brawl" scenario — ``growth_gain = 0`` and Bun healing off — the
system collapses to the same constant-coefficient combat attrition the MC sim
runs, so per-Wave clear time ↔ MC median TTK and Player-death time ↔ MC median
TTD agree within the documented tolerance. The consumable economy and the growth
feedback are this model's extensions BEYOND MC's domain (validated by the
conservation/boundary unit tests, not by MC).

Reuse (gADR-0011): the damage arithmetic is the parity-pinned ``rules`` seam
(``compute_damage``), the data comes from the ``game_config`` adapter as generic
``model`` dataclasses — no game-code import, no second rule copy, no second JSON
parser. The 1D mean-field aggregation (approach/travel latency, discrete kill
ordering, per-shot accuracy/dodge variance, and the Boss Warp micro-timing are
all averaged out) is why the cross-validation band is coarser than the MC-level
validate tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import rules
from .integrate import State, rk4_step
from .model import CombatParams, EnemyKind, GameData, GrowthEconomy, PlayerModel

# The state-vector layout (see the module docstring). Bare indices keep the
# vector a plain float tuple for the generic RK4 integrator.
Q, HP, EXP, GOLD, BUN, WINE = range(6)
_N = 6


@dataclass(frozen=True)
class SdParams:
    """The SD model's controls and design levers (per-game configuration).

    ``growth_gain`` is the reinforcing-growth lever (0.0 = Phase-1 readout-only
    fidelity). ``heal_threshold_frac`` and ``bun_consume_rate`` shape the
    balancing consumable loop (the fraction of max HP below which the Player eats
    a Bun, and how fast — Buns/sec — while healing; 0.0 disables the loop, the
    cross-validation overlap setting). ``dt`` / ``max_wave_time`` are the fixed
    RK4 step and the per-Wave time cap.
    """

    dt: float
    max_wave_time: float
    growth_gain: float = 0.0
    heal_threshold_frac: float = 0.5
    bun_consume_rate: float = 0.0

    def overlap(self) -> SdParams:
        """The reduced params for the MC cross-validation overlap: growth
        feedback OFF and the consumable loop OFF — the bare laser-brawl the MC
        engine also models."""
        return replace(self, growth_gain=0.0, bun_consume_rate=0.0)


@dataclass(frozen=True)
class WaveDynamics:
    """One Wave's SD coefficients, projected from the JSON authority once (a thin
    SD-specific data shape over ``GameData`` + ``GrowthEconomy``, not a second
    parse). ``player_dps`` is the base (Level-1) effective damage rate; the
    growth lever scales it at run time. ``difficulty`` is the per-Wave HP-cost
    index — the fraction of full HP the bare brawl costs to clear (> 1.0 = lethal
    without counterplay), the exogenous ramp the report charts."""

    index: int
    wave_hp: float
    player_dps: float
    enemy_dps: float
    exp_reward: float
    gold_reward: float
    bun_drops: float
    wine_drops: float

    @property
    def base_clear_time(self) -> float:
        """Base (Level-1) time to clear this Wave's HP at full player DPS."""
        return self.wave_hp / self.player_dps if self.player_dps > 0 else float("inf")

    def difficulty(self, player_max_hp: float) -> float:
        """The HP-cost difficulty index: the fraction of full HP the bare brawl
        costs to clear this Wave (ignoring survival) — the ramp scalar."""
        return self.enemy_dps * self.base_clear_time / player_max_hp


def _player_dps(
    player: PlayerModel, combat: CombatParams, enemy_defense: float
) -> float:
    """The Player's steady effective DPS against one enemy defense: the
    parity-pinned damage per shot (``rules.compute_damage``) times the effective
    hit rate (fire cadence discounted by aim)."""
    hit_rate = player.accuracy / player.fire_interval
    per_shot = rules.compute_damage(
        player.stats.attack,
        enemy_defense,
        combat.attack_scale,
        combat.defense_scale,
        combat.min_damage,
    )
    return hit_rate * per_shot


def _wave_enemy_dps(
    player: PlayerModel, combat: CombatParams, kinds: list[EnemyKind]
) -> float:
    """The Wave's aggregate incoming DPS on the Player (mean-field): every
    enemy's per-attack damage (``rules.compute_damage`` against the composed
    defender) over its cooldown, i-frame-capped (at most the largest single hit
    per i-frame window) and discounted by the dodge rate."""
    defender_defense = player.defender_stats.defense
    raw = 0.0
    max_hit = 0.0
    for k in kinds:
        dmg = rules.compute_damage(
            k.stats.attack,
            defender_defense,
            combat.attack_scale,
            combat.defense_scale,
            combat.min_damage,
        )
        raw += dmg / k.attack_cooldown
        max_hit = max(max_hit, dmg)
    cap = max_hit / combat.iframe_duration if combat.iframe_duration > 0 else raw
    return min(raw, cap) * (1.0 - player.dodge_chance)


def build_wave_dynamics(
    game: GameData, econ: GrowthEconomy, player: PlayerModel
) -> tuple[WaveDynamics, ...]:
    """Project each Wave into its SD coefficients (reward/HP/DPS aggregates).

    A thin, per-Wave reduction over the generic ``model`` data: the Player's
    sequential clear effort (Σ per-enemy HP / per-enemy DPS) gives the effective
    ``player_dps``; the Tier reward table gives the EXP/Gold/Drop inflows; the
    aggregate incoming DPS gives ``enemy_dps``. Gold inflow is the guaranteed Kill
    reward PLUS the expected gold Pickup drops (gADR-0006 — both accrue to the
    Player's Gold), the same both-sources sum a kill yields in-game. Reads only
    already-parsed ``GameData`` / ``GrowthEconomy`` — no JSON, no game code
    (gADR-0011).
    """
    out: list[WaveDynamics] = []
    for wave in game.waves:
        kinds = [game.kinds[s.kind] for s in wave.spawns]
        wave_hp = sum(k.stats.max_hp for k in kinds)
        effort = sum(
            k.stats.max_hp / _player_dps(player, game.combat, k.stats.defense)
            for k in kinds
        )
        rewards = [econ.tier_rewards[k.tier] for k in kinds]
        out.append(
            WaveDynamics(
                index=wave.index,
                wave_hp=wave_hp,
                player_dps=wave_hp / effort if effort > 0 else 0.0,
                enemy_dps=_wave_enemy_dps(player, game.combat, kinds),
                exp_reward=sum(r.exp_reward for r in rewards),
                gold_reward=sum(r.gold_reward + r.expected_drop("gold") for r in rewards),
                bun_drops=sum(r.expected_drop("bun") for r in rewards),
                wine_drops=sum(r.expected_drop("wine") for r in rewards),
            )
        )
    return tuple(out)


def _deriv(wd: WaveDynamics, params: SdParams, econ: GrowthEconomy):
    """Build the RHS closure ``f(t, y) -> dy`` for one Wave (the flows above)."""
    inv_hp = 1.0 / wd.wave_hp if wd.wave_hp > 0 else 0.0
    heal_per_bun = econ.bun_hp_restore
    threshold = params.heal_threshold_frac * econ.player_max_hp

    def f(_t: float, y: State) -> tuple[float, ...]:
        q, hp, exp, _gold, bun, _wine = y
        combat = 1.0 if (q > 0.0 and hp > 0.0) else 0.0
        level = econ.level_for(exp)
        growth = 1.0 + params.growth_gain * (level - 1)
        p = wd.player_dps * growth * combat  # effective kill rate
        # Balancing consumable loop: state-switched, saturating, and supply-LIMITED
        # within the step. Capping the consume rate at bun/dt bounds one step's
        # Bun spend to the Bun on hand, so a sliver of inventory buys only a sliver
        # of healing (never a full step of it) — the boundary conservation the
        # unit tests pin. dt is params.dt (the step is never larger), so the cap
        # is conservative on the shorter final step.
        if hp > 0.0 and hp < threshold and bun > 0.0:
            max_consume = bun / params.dt if params.dt > 0.0 else params.bun_consume_rate
            healing = min(params.bun_consume_rate, max_consume)
        else:
            healing = 0.0
        heal_flow = healing * heal_per_bun
        d_hp = -wd.enemy_dps * combat + heal_flow
        if hp >= econ.player_max_hp and d_hp > 0.0:
            d_hp = 0.0  # cap saturation: no overfill past max HP
        return (
            -p,
            d_hp,
            wd.exp_reward * inv_hp * p,
            wd.gold_reward * inv_hp * p,
            wd.bun_drops * inv_hp * p - healing,
            wd.wine_drops * inv_hp * p,
        )

    return f


def _clamp_bounds(y: State, econ: GrowthEconomy) -> State:
    """Project the bounded stocks back into range after a step: HP into
    ``[0, max]`` (the survival stock's saturation) and BUN into ``[0, ∞)`` (a
    count never goes negative). EXP/Gold/Wine are inflow-only and unclamped."""
    v = list(y)
    v[HP] = min(max(v[HP], 0.0), econ.player_max_hp)
    v[BUN] = max(v[BUN], 0.0)
    return tuple(v)


def _lerp(a: State, b: State, f: float) -> State:
    """Linear interpolation between two states at fraction ``f`` — the crossing
    state when an event (Q→0 or HP→0) fires inside a step."""
    return tuple(ai + f * (bi - ai) for ai, bi in zip(a, b))


@dataclass(frozen=True)
class WaveOutcome:
    """One Wave's SD result: whether/when it cleared or the Player died, the HP
    trajectory bounds, the accrued stocks, and the difficulty index."""

    index: int
    cleared: bool
    died: bool
    clear_time: float | None
    death_time: float | None
    hp_start: float
    hp_end: float
    hp_min: float
    exp_start: float
    exp_end: float
    level_end: int
    gold_end: float
    bun_start: float
    bun_end: float
    wine_end: float
    wave_hp: float
    player_dps: float
    enemy_dps: float
    difficulty: float

    @property
    def exp_gained(self) -> float:
        return self.exp_end - self.exp_start

    @property
    def hp_lost(self) -> float:
        return self.hp_start - self.hp_end


def _run_one_wave(
    wd: WaveDynamics,
    params: SdParams,
    econ: GrowthEconomy,
    y0: State,
) -> tuple[WaveOutcome, State]:
    """Integrate ONE Wave from initial stocks ``y0`` (with ``y0[Q]`` reset to the
    Wave's HP) to a clear (Q→0), a Player death (HP→0), or the per-Wave time cap,
    with a linear crossing refinement so a cleared Wave's reward integrates to its
    exact total (conservation). Returns the outcome and the carry-out stocks."""
    f = _deriv(wd, params, econ)
    y = tuple(y0)
    y = tuple(wd.wave_hp if i == Q else y[i] for i in range(_N))
    t = 0.0
    hp_start, exp_start, bun_start = y[HP], y[EXP], y[BUN]
    gold_start, wine_start = y[GOLD], y[WINE]
    hp_min = y[HP]
    cleared = died = False
    clear_time = death_time = None
    while t < params.max_wave_time:
        step = min(params.dt, params.max_wave_time - t)
        y_next = _clamp_bounds(rk4_step(f, t, y, step), econ)
        # Player-death event: HP crosses 0 within the step.
        if y_next[HP] <= 0.0 < y[HP]:
            frac = y[HP] / (y[HP] - y_next[HP])
            death_time = t + frac * step
            y = _lerp(y, y_next, frac)
            y = tuple(0.0 if i == HP else y[i] for i in range(_N))
            died = True
            hp_min = 0.0
            break
        # Wave-clear event: remaining enemy HP crosses 0 within the step.
        if y_next[Q] <= 0.0 < y[Q]:
            frac = y[Q] / (y[Q] - y_next[Q])
            clear_time = t + frac * step
            y = _lerp(y, y_next, frac)
            y = tuple(0.0 if i == Q else y[i] for i in range(_N))
            cleared = True
            hp_min = min(hp_min, y[HP])
            break
        y = y_next
        t += step
        hp_min = min(hp_min, y[HP])
    # Coflow snap: EXP/Gold/Wine are pure coflows of the kill flow — their exact
    # first integral is total_reward × killed_fraction (killed_fraction = 1 on a
    # clear). Snapping to it at the Wave boundary removes the RK4 drift that would
    # otherwise flip a Level read at an exact threshold; the analytic integral is
    # known, so this is exact accounting, not a fudge. (Bun keeps its integrated
    # value — its HP-driven consumption is genuinely path-dependent, not a coflow.)
    killed_fraction = (wd.wave_hp - max(y[Q], 0.0)) / wd.wave_hp if wd.wave_hp else 0.0
    y = tuple(
        {
            EXP: exp_start + wd.exp_reward * killed_fraction,
            GOLD: gold_start + wd.gold_reward * killed_fraction,
            WINE: wine_start + wd.wine_drops * killed_fraction,
        }.get(i, y[i])
        for i in range(_N)
    )
    outcome = WaveOutcome(
        index=wd.index,
        cleared=cleared,
        died=died,
        clear_time=clear_time,
        death_time=death_time,
        hp_start=hp_start,
        hp_end=y[HP],
        hp_min=hp_min,
        exp_start=exp_start,
        exp_end=y[EXP],
        level_end=econ.level_for(y[EXP]),
        gold_end=y[GOLD],
        bun_start=bun_start,
        bun_end=y[BUN],
        wine_end=y[WINE],
        wave_hp=wd.wave_hp,
        player_dps=wd.player_dps,
        enemy_dps=wd.enemy_dps,
        difficulty=wd.difficulty(econ.player_max_hp),
    )
    return outcome, y


@dataclass(frozen=True)
class RunOutcome:
    """The whole-run SD trajectory: per-Wave outcomes plus the run-level verdict
    (did the Player clear the schedule, or die at which Wave) and end stocks."""

    waves: tuple[WaveOutcome, ...]
    cleared_schedule: bool
    died_at_wave: int | None
    final_hp: float
    final_exp: float
    final_level: int
    final_gold: float
    final_bun: float
    final_wine: float


def run_scenario(
    dynamics: tuple[WaveDynamics, ...],
    params: SdParams,
    econ: GrowthEconomy,
    start_hp: float | None = None,
) -> RunOutcome:
    """Integrate the whole Wave schedule as one chained run (the long-term
    prediction): HP and the economy stocks CARRY across Waves (persistent, like
    the game — only Consumables restore HP), each Wave resets ``Q`` to its enemy
    HP, and the run stops at the first Player death. Start at full HP by default.
    """
    hp0 = econ.player_max_hp if start_hp is None else start_hp
    y: State = (0.0, hp0, 0.0, 0.0, 0.0, 0.0)
    outcomes: list[WaveOutcome] = []
    died_at: int | None = None
    for wd in dynamics:
        outcome, y = _run_one_wave(wd, params, econ, y)
        outcomes.append(outcome)
        if outcome.died:
            died_at = wd.index
            break
    cleared_schedule = died_at is None and all(o.cleared for o in outcomes)
    return RunOutcome(
        waves=tuple(outcomes),
        cleared_schedule=cleared_schedule,
        died_at_wave=died_at,
        final_hp=y[HP],
        final_exp=y[EXP],
        final_level=econ.level_for(y[EXP]),
        final_gold=y[GOLD],
        final_bun=y[BUN],
        final_wine=y[WINE],
    )


def run_wave_overlap(
    wd: WaveDynamics, params: SdParams, econ: GrowthEconomy
) -> WaveOutcome:
    """Integrate ONE Wave from FULL HP with the overlap params (growth + healing
    off) — the bare laser-brawl the MC engine also simulates, for cross-validation
    (each MC Wave is an independent full-HP encounter, so this matches its shape).
    """
    overlap = params.overlap()
    y0: State = (wd.wave_hp, econ.player_max_hp, 0.0, 0.0, 0.0, 0.0)
    outcome, _ = _run_one_wave(wd, overlap, econ, y0)
    return outcome
