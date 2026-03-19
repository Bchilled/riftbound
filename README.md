# Riftbound TCG — Collection Tracker + Game Engine

## What's in here

### riftbound_collection.xlsx
Full collection tracker and simulation suite.
- **My Collection** — every card owned, which deck it belongs to
- **Missing Cards** — what you still need
- **All Cards** — full card database OGN + SFD
- **Deck - Azir Final** — Calm+Order, Go Wide, 40 cards + 8 SB + ABCDEFG guide
- **Deck - Volibear** — Fury+Body, Go Big, 40 cards + 8 SB + ABCDEFG guide
- **Deck - Miss Fortune** — Body+Chaos, Go Sneaky, 40 cards + 8 SB + ABCDEFG guide
- **Deck - Draven** — Fury+Chaos, Resource Domination, 40 cards + 8 SB + ABCDEFG guide
- **Sim - All Decks** — Live Excel formula simulation engine (adjustable inputs, auto-calculates win rates)
- **Sim - Engine Results** — Results from Python game engine (1000 games per matchup)

### riftbound_engine.py
Full Riftbound game simulation engine. Simulates real games with:
- Turn phases: Awaken → Beginning → Channel → Draw → Main
- Rune economy: 12-card cycling rune deck
- Combat: Might comparison, ASSAULT, SHIELD, TANK, DEFLECT
- Ability triggers: DEATHKNELL, GANKING, ACCELERATE, TEMPORARY, passive scoring
- Legend effects for all 4 decks
- Card-specific logic for key cards

**To run:**
```bash
python3 riftbound_engine.py
```

**To simulate a matchup:**
```python
from riftbound_engine import run_simulation

config1 = {
    'deck': {'OGN-003':3, ...},  # card IDs and quantities
    'legend': 'SFD-185',
    'champion': 'SFD-020',
    'archetype': 'DRAVEN',
    'name': 'Draven'
}
wr = run_simulation(config1, config2, n_games=1000)
print(f"Win rate: {wr:.1f}%")
```

## Engine Status

| Deck | AI Quality | Notes |
|---|---|---|
| Draven | ✓ Calibrated | 67.6% meta avg matches real 64.3% tournament data |
| Azir | ~ Partial | Token generation underutilized |
| Miss Fortune | ✗ Needs work | GANKING/movement logic incomplete |
| Volibear | ✗ Needs work | Multi-turn ramp planning not modeled |

## Real Meta (March 2026)
S-Tier: Draven (64.3% WR), Irelia, Ezreal
Tier 1: Kai'Sa, Master Yi, Viktor, Sivir, Annie
Source: 6 Regional Qualifiers, 1289 tournaments, riftdecks.com

## Card Data
- `ogn_full.json` — Origins set card database
- `sfd_full.json` — Spiritforged set card database

## Notes
- All 4 decks are legal with zero card conflicts
- Zero buys needed for Draven, Azir, Voli, MF (all cards owned)
- Each deck tab has ABCDEFG turn guide for teaching new players
