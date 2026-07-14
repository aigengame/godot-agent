"""The system-dynamics state model of a run's growth/economy — the macro engine.

A first-order nonlinear ODE system over the run's **stocks** (accumulating
state) and **flows** (their rates), integrated by the hand-rolled RK4
(``integrate``) across the wave schedule to predict the long-term growth/economy
trajectory. Where the Monte-Carlo engine (``encounter``) simulates ONE encounter
at micro fidelity, this model is the mean-field aggregate of the whole run —
deterministic, no RNG.

Stocks (the state vector): four fixed stocks, then one stock per tracked drop
item (``GrowthEconomy.item_keys``, deterministic sorted order):

- ``Q``        — the current wave's remaining aggregate enemy HP (depletes to clear).
- ``HP``       — the player's health, bounded ``[0, max]`` (the survival stock;
  carried across waves in the chained run, like a real playthrough).
- ``EXP``      — cumulative EXP (the growth stock; level is its readout via the
  leveling curve).
- ``CURRENCY`` — cumulative currency inflow: the guaranteed kill reward PLUS the
  expected drops of the economy's ``currency_item``. Inflow-only unless the game
  models a sink, so it is an accumulator.
- one stock per tracked item — economy in via expected drops; the configured
  ``heal_item`` also flows OUT via HP-restore use (the balancing loop), every
  other item is inflow-only (a game-side sink outside this model's scope is a
  scoping note for the targets file, not a modeling error).

Flows (the ODE right-hand side), per wave ``w`` with coefficients projected from
the adapter-mapped model data (``build_wave_dynamics``):

- ``dQ/dt        = -P``                    — the player's effective damage rate
  ``P = player_dps_w * growth(EXP)`` drains the wave's enemy HP.
- ``dHP/dt       = -enemy_dps_w + heal``   — incoming aggregate enemy DPS,
  offset by heal-item use (``heal``).
- ``dEXP/dt      = (exp_reward_w      / wave_hp_w) * P``  — reward accrues in
- ``dCURRENCY/dt = (currency_reward_w / wave_hp_w) * P``    proportion to the
- ``dITEM_k/dt   = (item_drops_w[k]   / wave_hp_w) * P``    fraction of the
  (minus consumption for the heal item)                     wave's HP destroyed,
  so integrating a fully cleared wave yields EXACTLY its total reward (the
  conservation the unit tests pin) — the continuous mean-field of the game's
  discrete per-kill rewards.

The nonlinearities that make this a genuine first-order NONLINEAR ODE system —
the two coupled system-dynamics feedback loops plus the difficulty driver:

- **Reinforcing growth loop** — ``growth(EXP) = 1 + growth_gain * (level(EXP) - 1)``
  feeds the growth stock back into the kill rate through the piecewise leveling
  curve (more kills → more EXP → higher level → faster kills). ``growth_gain``
  defaults to 0.0 (a readout-only level system), so it is an explicit,
  documented design lever; setting it > 0 predicts the INTENDED growth curve.
- **Balancing consumable loop** — heal-item use is a state-switched,
  supply-limited, saturating term: it engages only while ``HP <
  heal_threshold_frac * max`` AND the heal stock is positive, restores toward
  ``player_max_hp`` (the cap — a ``min`` saturation), and drains the heal stock.
  The threshold switch, the supply gate, and the cap are all nonlinear in the
  state.
- **Difficulty ramp** — the exogenous forcing: each wave's ``enemy_dps_w`` /
  ``wave_hp_w`` step up across the schedule (the driving function the loops
  respond to).

Cross-validation overlap with the MC engine (``prediction``): in the reduced
"bare brawl" scenario — ``growth_gain = 0`` and healing off — the system
collapses to the same constant-coefficient combat attrition the MC sim runs, so
per-wave clear time ↔ MC median TTK and player-death time ↔ MC median TTD agree
within the documented tolerance. The consumable economy and the growth feedback
are this model's extensions BEYOND MC's domain (validated by the
conservation/boundary unit tests, not by MC).

Reuse: the damage arithmetic is the shared ``rules`` ruleset
(``compute_damage``), the data comes from the per-game adapter as generic
``model`` dataclasses — no game-code import, no second rule copy, no second
config parser. The 1D mean-field aggregation (approach/travel latency, discrete
kill ordering, per-shot accuracy/dodge variance, and warp micro-timing are all
averaged out) is why the cross-validation band is coarser than the MC-level
validate tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import rules
from .integrate import State, rk4_step
from .model import CombatParams, EnemyKind, GameData, GrowthEconomy, PlayerModel

# The fixed head of the state vector (see the module docstring); the tracked
# item stocks follow, one per ``GrowthEconomy.item_keys`` entry, in that order.
# Bare indices keep the vector a plain float tuple for the generic integrator.
Q, HP, EXP, CUR = range(4)
_FIXED = 4


def state_size(econ: GrowthEconomy) -> int:
    """The state vector's length for this economy."""
    return _FIXED + len(econ.item_keys)


def item_index(econ: GrowthEconomy, item: str) -> int:
    """The state-vector index of ``item``'s stock (raises if untracked)."""
    return _FIXED + econ.item_keys.index(item)


def initial_state(econ: GrowthEconomy, hp: float | None = None) -> State:
    """A fresh run's stocks: zero everywhere except HP (full by default)."""
    hp0 = econ.player_max_hp if hp is None else hp
    return (0.0, hp0, 0.0, 0.0) + (0.0,) * len(econ.item_keys)


@dataclass(frozen=True)
class SdParams:
    """The SD model's controls and design levers (per-game configuration).

    ``growth_gain`` is the reinforcing-growth lever (0.0 = readout-only
    fidelity). ``heal_threshold_frac`` and ``heal_consume_rate`` shape the
    balancing consumable loop (the fraction of max HP below which the player
    uses the heal item, and how fast — items/sec — while healing; 0.0 disables
    the loop, the cross-validation overlap setting). ``dt`` / ``max_wave_time``
    are the fixed RK4 step and the per-wave time cap.
    """

    dt: float
    max_wave_time: float
    growth_gain: float = 0.0
    heal_threshold_frac: float = 0.5
    heal_consume_rate: float = 0.0

    def overlap(self) -> SdParams:
        """The reduced params for the MC cross-validation overlap: growth
        feedback OFF and the consumable loop OFF — the bare brawl the MC engine
        also models."""
        return replace(self, growth_gain=0.0, heal_consume_rate=0.0)


@dataclass(frozen=True)
class WaveDynamics:
    """One wave's SD coefficients, projected from the model data once (a thin
    SD-specific data shape over ``GameData`` + ``GrowthEconomy``, not a second
    parse). ``player_dps`` is the base (level-1) effective damage rate; the
    growth lever scales it at run time. ``item_drops`` is the wave's expected
    per-item drop inflow, keyed like ``GrowthEconomy.item_keys``.
    ``difficulty`` is the per-wave HP-cost index — the fraction of full HP the
    bare brawl costs to clear (> 1.0 = lethal without counterplay), the
    exogenous ramp the report charts."""

    index: int
    wave_hp: float
    player_dps: float
    enemy_dps: float
    exp_reward: float
    currency_reward: float
    item_drops: dict[str, float]

    @property
    def base_clear_time(self) -> float:
        """Base (level-1) time to clear this wave's HP at full player DPS."""
        return self.wave_hp / self.player_dps if self.player_dps > 0 else float("inf")

    def difficulty(self, player_max_hp: float) -> float:
        """The HP-cost difficulty index: the fraction of full HP the bare brawl
        costs to clear this wave (ignoring survival) — the ramp scalar."""
        return self.enemy_dps * self.base_clear_time / player_max_hp


def _player_dps(
    player: PlayerModel, combat: CombatParams, enemy_defense: float
) -> float:
    """The player's steady effective DPS against one enemy defense: the shared
    damage rule per shot (``rules.compute_damage``) times the effective hit
    rate (fire cadence discounted by aim)."""
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
    """The wave's aggregate incoming DPS on the player (mean-field): every
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
    """Project each wave into its SD coefficients (reward/HP/DPS aggregates).

    A thin, per-wave reduction over the generic ``model`` data: the player's
    sequential clear effort (Σ per-enemy HP / per-enemy DPS) gives the effective
    ``player_dps``; the tier reward table gives the EXP/currency/drop inflows;
    the aggregate incoming DPS gives ``enemy_dps``. Currency inflow is the
    guaranteed kill reward PLUS the expected drops of the economy's
    ``currency_item`` — both accrue to the player, the same both-sources sum a
    kill yields in-game. Reads only already-parsed ``GameData`` /
    ``GrowthEconomy`` — no config files, no game code.
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
        currency_drops = (
            sum(r.expected_drop(econ.currency_item) for r in rewards)
            if econ.currency_item is not None
            else 0.0
        )
        out.append(
            WaveDynamics(
                index=wave.index,
                wave_hp=wave_hp,
                player_dps=wave_hp / effort if effort > 0 else 0.0,
                enemy_dps=_wave_enemy_dps(player, game.combat, kinds),
                exp_reward=sum(r.exp_reward for r in rewards),
                currency_reward=sum(r.currency_reward for r in rewards)
                + currency_drops,
                item_drops={
                    item: sum(r.expected_drop(item) for r in rewards)
                    for item in econ.item_keys
                },
            )
        )
    return tuple(out)


def _deriv(wd: WaveDynamics, params: SdParams, econ: GrowthEconomy):
    """Build the RHS closure ``f(t, y) -> dy`` for one wave (the flows above)."""
    inv_hp = 1.0 / wd.wave_hp if wd.wave_hp > 0 else 0.0
    # The closure is the hot path (4 evaluations per RK4 step): precompute the
    # per-item drop rates and the heal stock's position once per wave.
    drop_rates = tuple(wd.item_drops.get(item, 0.0) * inv_hp for item in econ.item_keys)
    heal_index = item_index(econ, econ.heal_item) if econ.heal_item else -1
    heal_pos = heal_index - _FIXED
    heal_per_item = econ.heal_item_restore
    threshold = params.heal_threshold_frac * econ.player_max_hp

    def f(_t: float, y: State) -> tuple[float, ...]:
        q, hp = y[Q], y[HP]
        combat = 1.0 if (q > 0.0 and hp > 0.0) else 0.0
        level = econ.level_for(y[EXP])
        growth = 1.0 + params.growth_gain * (level - 1)
        p = wd.player_dps * growth * combat  # effective kill rate
        # Balancing consumable loop: state-switched, saturating, and supply-LIMITED
        # within the step. Capping the consume rate at stock/dt bounds one step's
        # spend to the items on hand, so a sliver of inventory buys only a sliver
        # of healing (never a full step of it) — the boundary conservation the
        # unit tests pin. dt is params.dt (the step is never larger), so the cap
        # is conservative on the shorter final step.
        if heal_index >= 0 and hp > 0.0 and hp < threshold and y[heal_index] > 0.0:
            max_consume = (
                y[heal_index] / params.dt
                if params.dt > 0.0
                else params.heal_consume_rate
            )
            healing = min(params.heal_consume_rate, max_consume)
        else:
            healing = 0.0
        heal_flow = healing * heal_per_item
        d_hp = -wd.enemy_dps * combat + heal_flow
        if hp >= econ.player_max_hp and d_hp > 0.0:
            d_hp = 0.0  # cap saturation: no overfill past max HP
        d_items = tuple(
            rate * p - (healing if i == heal_pos else 0.0)
            for i, rate in enumerate(drop_rates)
        )
        return (
            -p,
            d_hp,
            wd.exp_reward * inv_hp * p,
            wd.currency_reward * inv_hp * p,
        ) + d_items

    return f


def _clamp_bounds(y: State, econ: GrowthEconomy) -> State:
    """Project the bounded stocks back into range after a step: HP into
    ``[0, max]`` (the survival stock's saturation) and every item stock into
    ``[0, ∞)`` (a count never goes negative). EXP/currency are inflow-only and
    unclamped."""
    v = list(y)
    v[HP] = min(max(v[HP], 0.0), econ.player_max_hp)
    for i in range(_FIXED, len(v)):
        v[i] = max(v[i], 0.0)
    return tuple(v)


def _lerp(a: State, b: State, f: float) -> State:
    """Linear interpolation between two states at fraction ``f`` — the crossing
    state when an event (Q→0 or HP→0) fires inside a step."""
    return tuple(ai + f * (bi - ai) for ai, bi in zip(a, b))


@dataclass(frozen=True)
class WaveOutcome:
    """One wave's SD result: whether/when it cleared or the player died, the HP
    trajectory bounds, the accrued stocks (items keyed like
    ``GrowthEconomy.item_keys``), and the difficulty index."""

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
    currency_end: float
    items_start: dict[str, float]
    items_end: dict[str, float]
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
    """Integrate ONE wave from initial stocks ``y0`` (with ``y0[Q]`` reset to the
    wave's HP) to a clear (Q→0), a player death (HP→0), or the per-wave time cap,
    with a linear crossing refinement so a cleared wave's reward integrates to its
    exact total (conservation). Returns the outcome and the carry-out stocks."""
    f = _deriv(wd, params, econ)
    items = econ.item_keys
    size = _FIXED + len(items)
    index = {item: _FIXED + i for i, item in enumerate(items)}
    y = tuple(wd.wave_hp if i == Q else y0[i] for i in range(size))
    t = 0.0
    hp_start, exp_start = y[HP], y[EXP]
    currency_start = y[CUR]
    items_start = {item: y[index[item]] for item in items}
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
            y = tuple(0.0 if i == HP else y[i] for i in range(size))
            died = True
            hp_min = 0.0
            break
        # Wave-clear event: remaining enemy HP crosses 0 within the step.
        if y_next[Q] <= 0.0 < y[Q]:
            frac = y[Q] / (y[Q] - y_next[Q])
            clear_time = t + frac * step
            y = _lerp(y, y_next, frac)
            y = tuple(0.0 if i == Q else y[i] for i in range(size))
            cleared = True
            hp_min = min(hp_min, y[HP])
            break
        y = y_next
        t += step
        hp_min = min(hp_min, y[HP])
    # Coflow snap: EXP, currency, and every inflow-only item are pure coflows of
    # the kill flow — their exact first integral is total_reward × killed_fraction
    # (killed_fraction = 1 on a clear). Snapping to it at the wave boundary
    # removes the RK4 drift that would otherwise flip a level read at an exact
    # threshold; the analytic integral is known, so this is exact accounting, not
    # a fudge. (The heal item keeps its integrated value — its HP-driven
    # consumption is genuinely path-dependent, not a coflow.)
    killed_fraction = (wd.wave_hp - max(y[Q], 0.0)) / wd.wave_hp if wd.wave_hp else 0.0
    snapped = {
        EXP: exp_start + wd.exp_reward * killed_fraction,
        CUR: currency_start + wd.currency_reward * killed_fraction,
    }
    for item in items:
        if item != econ.heal_item:
            snapped[index[item]] = (
                items_start[item] + wd.item_drops.get(item, 0.0) * killed_fraction
            )
    y = tuple(snapped.get(i, y[i]) for i in range(size))
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
        currency_end=y[CUR],
        items_start=items_start,
        items_end={item: y[index[item]] for item in items},
        wave_hp=wd.wave_hp,
        player_dps=wd.player_dps,
        enemy_dps=wd.enemy_dps,
        difficulty=wd.difficulty(econ.player_max_hp),
    )
    return outcome, y


@dataclass(frozen=True)
class RunOutcome:
    """The whole-run SD trajectory: per-wave outcomes plus the run-level verdict
    (did the player clear the schedule, or die at which wave) and end stocks."""

    waves: tuple[WaveOutcome, ...]
    cleared_schedule: bool
    died_at_wave: int | None
    final_hp: float
    final_exp: float
    final_level: int
    final_currency: float
    final_items: dict[str, float]


def run_scenario(
    dynamics: tuple[WaveDynamics, ...],
    params: SdParams,
    econ: GrowthEconomy,
    start_hp: float | None = None,
) -> RunOutcome:
    """Integrate the whole wave schedule as one chained run (the long-term
    prediction): HP and the economy stocks CARRY across waves (persistent, like
    a real playthrough — only the heal item restores HP), each wave resets ``Q``
    to its enemy HP, and the run stops at the first player death. Start at full
    HP by default.
    """
    y: State = initial_state(econ, start_hp)
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
        final_currency=y[CUR],
        final_items={item: y[item_index(econ, item)] for item in econ.item_keys},
    )


def run_wave_overlap(
    wd: WaveDynamics, params: SdParams, econ: GrowthEconomy
) -> WaveOutcome:
    """Integrate ONE wave from FULL HP with the overlap params (growth + healing
    off) — the bare brawl the MC engine also simulates, for cross-validation
    (each MC wave is an independent full-HP encounter, so this matches its shape).
    """
    outcome, _ = _run_one_wave(wd, params.overlap(), econ, initial_state(econ))
    return outcome
