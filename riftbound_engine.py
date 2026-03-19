"""
Riftbound TCG Game Engine
Full simulation of the game from card database up.
Models: turn phases, rune economy, combat, abilities, scoring.
"""

import json
import random
from collections import defaultdict
from enum import Enum
from copy import deepcopy

# ============================================================
# CARD DATABASE
# ============================================================

with open('/home/claude/sfd_full.json') as f:
    sfd_raw = json.load(f)
with open('/home/claude/ogn_full.json') as f:
    ogn_raw = json.load(f)

RAW_CARDS = {}
for k,v in sfd_raw.items():
    RAW_CARDS[f'SFD-{int(k):03d}'] = v
for k,v in ogn_raw.items():
    RAW_CARDS[f'OGN-{int(k):03d}'] = v

def parse_abilities(ab_text):
    """Parse card ability text into structured flags."""
    ab = (ab_text or '').lower().replace('\r\n', ' ')
    return {
        'assault':      2 if 'assault 2' in ab else (3 if 'assault 3' in ab else (4 if 'assault 4' in ab else (1 if 'assault' in ab else 0))),
        'shield':       5 if 'shield 5' in ab else (3 if 'shield 3' in ab else (2 if 'shield 2' in ab else (1 if 'shield' in ab else 0))),
        'accelerate':   'accelerate' in ab,
        'ganking':      'ganking' in ab,
        'deflect':      2 if 'deflect 2' in ab else (1 if 'deflect' in ab else 0),
        'tank':         'tank' in ab,
        'hidden':       'hidden' in ab,
        'temporary':    'temporary' in ab,
        'vision':       'vision' in ab,
        'quick_draw':   'quick-draw' in ab or 'quick draw' in ab,
        'weaponmaster': 'weaponmaster' in ab,
        'legion':       'legion' in ab,
        'deathknell':   'deathknell' in ab,
        'draws_on_win': 'when i win' in ab and 'draw' in ab,
        'token_gen':    'sand soldier' in ab or 'recruit unit token' in ab or 'mech unit token' in ab or 'sprite' in ab,
        'passive_score': 'when i hold' in ab and 'score 1' in ab,
        'enters_ready': 'enter ready' in ab or 'enters ready' in ab,
        'draw_on_play': ('when you play me' in ab or 'when i enter' in ab) and 'draw 1' in ab,
        'channels_rune': 'channel 1 rune' in ab or 'add rune' in ab,
        'gold_on_win':  'when i win' in ab and 'gold' in ab,
        'raw': ab_text or '',
    }

class CardDef:
    """Immutable card definition from database."""
    def __init__(self, cid):
        self.cid = cid
        data = RAW_CARDS.get(cid, {})
        self.name = data.get('name', cid)
        self.cost = int(data.get('cost', 0) or 0)
        self.base_might = int(data.get('might', 0) or 0)
        self.card_type = data.get('type', '')
        self.domain = data.get('domain', '')
        self.rarity = data.get('rarity', '')
        self.ab = parse_abilities(data.get('ability', ''))
        self.raw_ability = data.get('ability', '')

    @property
    def is_unit(self):
        return 'Unit' in self.card_type or 'Champion' in self.card_type

    @property
    def is_spell(self):
        return 'Spell' in self.card_type or 'Signature' in self.card_type

    @property
    def is_gear(self):
        return 'Gear' in self.card_type

    @property
    def is_legend(self):
        return 'Legend' in self.card_type

    def __repr__(self):
        return f"{self.name}({self.cid})"

# Pre-build card definitions
CARD_DEFS = {cid: CardDef(cid) for cid in RAW_CARDS}

def get_card(cid):
    if cid not in CARD_DEFS:
        CARD_DEFS[cid] = CardDef(cid)
    return CARD_DEFS[cid]

# Token definitions
SAND_SOLDIER = CardDef.__new__(CardDef)
SAND_SOLDIER.cid = 'TOKEN_SOLDIER'
SAND_SOLDIER.name = 'Sand Soldier'
SAND_SOLDIER.cost = 0
SAND_SOLDIER.base_might = 2
SAND_SOLDIER.card_type = 'Unit'
SAND_SOLDIER.domain = 'Order;Calm'
SAND_SOLDIER.ab = parse_abilities('')
SAND_SOLDIER.raw_ability = ''
# is_unit etc are properties derived from card_type

GOLD_TOKEN = CardDef.__new__(CardDef)
GOLD_TOKEN.cid = 'TOKEN_GOLD'
GOLD_TOKEN.name = 'Gold Token'
GOLD_TOKEN.cost = 0
GOLD_TOKEN.base_might = 0
GOLD_TOKEN.card_type = 'Gear'
GOLD_TOKEN.domain = ''
GOLD_TOKEN.ab = parse_abilities('')
GOLD_TOKEN.raw_ability = ''
# GOLD_TOKEN properties derived from card_type

MECH_TOKEN_3 = CardDef.__new__(CardDef)
MECH_TOKEN_3.cid = 'TOKEN_MECH3'
MECH_TOKEN_3.name = 'Mech (3M)'
MECH_TOKEN_3.cost = 0
MECH_TOKEN_3.base_might = 3
MECH_TOKEN_3.card_type = 'Unit'
MECH_TOKEN_3.domain = ''
MECH_TOKEN_3.ab = parse_abilities('')
MECH_TOKEN_3.raw_ability = ''
# MECH_TOKEN_3 properties derived from card_type

RECRUIT_TOKEN = CardDef.__new__(CardDef)
RECRUIT_TOKEN.cid = 'TOKEN_RECRUIT'
RECRUIT_TOKEN.name = 'Recruit'
RECRUIT_TOKEN.cost = 0
RECRUIT_TOKEN.base_might = 1
RECRUIT_TOKEN.card_type = 'Unit'
RECRUIT_TOKEN.domain = ''
RECRUIT_TOKEN.ab = parse_abilities('')
RECRUIT_TOKEN.raw_ability = ''
# RECRUIT_TOKEN properties derived from card_type

# ============================================================
# GAME OBJECTS
# ============================================================

class Location(Enum):
    BASE = 'base'
    FIELD_0 = 'field_0'
    FIELD_1 = 'field_1'
    HAND = 'hand'
    DECK = 'deck'
    TRASH = 'trash'
    HIDDEN = 'hidden'
    CHAMPION_ZONE = 'champion_zone'

class UnitOnBoard:
    """A unit currently in play."""
    _id_counter = 0
    
    def __init__(self, card_def, owner_id, location=Location.BASE):
        UnitOnBoard._id_counter += 1
        self.uid = UnitOnBoard._id_counter
        self.card = card_def
        self.owner_id = owner_id
        self.location = location
        self.exhausted = not card_def.ab.get('accelerate') and not card_def.ab.get('enters_ready')
        self.equipped_gear = []  # list of CardDef gear
        self.buffs = 0  # +1 might buff count
        self.temporary = card_def.ab.get('temporary', False)
        self.has_ganking = card_def.ab.get('ganking', False)
        self.has_assault = card_def.ab.get('assault', 0)
        self.has_shield = card_def.ab.get('shield', 0)
        self.has_deflect = card_def.ab.get('deflect', 0)
        self.is_tank = card_def.ab.get('tank', False)
        self.passive_score = card_def.ab.get('passive_score', False)
        self.hidden_mode = False
    
    @property
    def base_might(self):
        m = self.card.base_might + self.buffs
        for g in self.equipped_gear:
            m += g.base_might  # gear adds its might
        return m
    
    @property
    def attack_might(self):
        return self.base_might + self.has_assault
    
    @property
    def defense_might(self):
        return self.base_might + self.has_shield
    
    @property
    def is_mighty(self):
        return self.base_might >= 5
    
    def ready(self):
        self.exhausted = False
    
    def exhaust(self):
        self.exhausted = True
    
    def __repr__(self):
        loc = self.location.value
        return f"{self.card.name}({self.base_might}M @{loc}{'E' if self.exhausted else ''})"

class Player:
    """A player in the game."""
    
    def __init__(self, pid, deck_list, legend_cid, champion_cid, deck_name=''):
        self.pid = pid
        self.deck_name = deck_name
        self.score = 0
        
        # Build main deck
        self.main_deck = []
        for cid, qty in deck_list.items():
            for _ in range(qty):
                self.main_deck.append(get_card(cid))
        random.shuffle(self.main_deck)
        
        # Rune deck: 12 cards
        self.rune_deck = list(range(12))  # simplified: 12 rune cards
        random.shuffle(self.rune_deck)
        
        # Hand
        self.hand = []
        self.draw_opening_hand(7)
        
        # Legend
        self.legend = get_card(legend_cid) if legend_cid else None
        self.legend_exhausted = False
        
        # Champion zone
        self.champion = UnitOnBoard(get_card(champion_cid), pid, Location.CHAMPION_ZONE) if champion_cid else None
        
        # Board state
        self.units = []  # all units in play (base + fields)
        
        # Energy tracking
        self.energy = 0
        self.gold_tokens = 0
        
        # Turn tracking
        self.cards_played_this_turn = 0
        self.equipment_played_this_turn = 0
        self.discarded_this_turn = False
        self.conquered_this_turn = False
        
        # Trash
        self.trash = []
    
    def draw_opening_hand(self, n):
        for _ in range(min(n, len(self.main_deck))):
            self.hand.append(self.main_deck.pop(0))
    
    def draw(self, n=1):
        drawn = []
        for _ in range(n):
            if self.main_deck:
                drawn.append(self.main_deck.pop(0))
        self.hand.extend(drawn)
        return drawn
    
    def channel_runes(self, n=2):
        """Channel n runes from rune deck. Rune deck cycles when empty."""
        channeled = 0
        for _ in range(n):
            if not self.rune_deck:
                self.rune_deck = list(range(12))  # reshuffle
                random.shuffle(self.rune_deck)
            self.rune_deck.pop()
            channeled += 1
        self.energy += channeled
        return channeled
    
    def units_at(self, location):
        return [u for u in self.units if u.location == location and not u.hidden_mode]
    
    def units_at_fields(self):
        return [u for u in self.units if u.location in (Location.FIELD_0, Location.FIELD_1)]
    
    def has_field_presence(self, field):
        return len(self.units_at(field)) > 0
    
    def field_might(self, field):
        """Total base might of units at a field."""
        return sum(u.base_might for u in self.units_at(field))
    
    def passive_score_at(self, field):
        """Additional points scored for holding this field."""
        return sum(1 for u in self.units_at(field) if u.passive_score)
    
    def ready_all(self):
        """Awaken phase: ready everything."""
        for u in self.units:
            u.ready()
        self.legend_exhausted = False
        if self.champion:
            self.champion.ready()
    
    def reset_turn_tracking(self):
        self.cards_played_this_turn = 0
        self.equipment_played_this_turn = 0
        self.discarded_this_turn = False
        self.conquered_this_turn = False
        self.energy = 0
        self._confront_active = False

# ============================================================
# COMBAT RESOLUTION
# ============================================================

class CombatResult:
    def __init__(self, attacker_wins, excess_damage=0, attacker_died=False, defender_died=False):
        self.attacker_wins = attacker_wins
        self.excess_damage = excess_damage
        self.attacker_died = attacker_died
        self.defender_died = defender_died

def resolve_combat(attacker, defender):
    """
    Single combat between attacker and defender unit.
    Returns CombatResult.
    """
    atk_m = attacker.attack_might
    def_m = defender.defense_might
    
    # TANK: if defender has tank, must take damage first (already handled by targeting)
    
    if atk_m > def_m:
        excess = atk_m - def_m
        return CombatResult(attacker_wins=True, excess_damage=excess, defender_died=True)
    elif def_m > atk_m:
        return CombatResult(attacker_wins=False, attacker_died=True)
    else:
        # Tie: attacker fails to conquer, neither dies
        # (In Riftbound, ties mean attacker doesn't conquer but combat ends)
        return CombatResult(attacker_wins=False)

def resolve_field_combat(attacking_units, defending_units):
    """
    Resolve combat at a field.
    Returns (attacker_won_field, deaths_atk, deaths_def, excess_damage)
    """
    if not defending_units:
        return True, [], [], 999  # no defenders = auto conquer with max excess
    
    dead_atk = []
    dead_def = []
    total_excess = 0
    
    # Sort: attacking TANK units are targeted first on defense side
    tanks = [u for u in defending_units if u.is_tank]
    non_tanks = [u for u in defending_units if not u.is_tank]
    ordered_def = tanks + non_tanks
    
    def_pool = list(ordered_def)
    atk_pool = list(attacking_units)
    
    # Each attacker fights the strongest available defender
    # (simplified: best available match)
    for attacker in atk_pool:
        if not def_pool:
            break  # all defenders dead, rest of attackers uncontested
        
        # Pick best defender (highest defense might, or tank if any)
        tanks_left = [d for d in def_pool if d.is_tank]
        if tanks_left:
            defender = max(tanks_left, key=lambda d: d.defense_might)
        else:
            defender = max(def_pool, key=lambda d: d.defense_might)
        
        result = resolve_combat(attacker, defender)
        total_excess += result.excess_damage
        
        if result.defender_died:
            dead_def.append(defender)
            def_pool.remove(defender)
        if result.attacker_died:
            dead_atk.append(attacker)
    
    attacker_won = len(def_pool) == 0 or (not defending_units)
    return attacker_won, dead_atk, dead_def, total_excess

# ============================================================
# AI DECISION MAKING
# ============================================================

class DeckAI:
    """
    Base AI for playing a deck.
    Subclassed for each deck archetype.
    """
    
    def __init__(self, player, archetype='generic'):
        self.p = player
        self.archetype = archetype
    
    def choose_cards_to_play(self, energy_available, opponent):
        """Return list of cards to play from hand this turn."""
        playable = [c for c in self.p.hand if c.cost <= energy_available and c.is_unit]
        # Sort by: enters_ready first, then highest attack might
        playable.sort(key=lambda c: (
            -(c.ab.get('assault',0) + c.base_might),
            not c.ab.get('accelerate'),
            c.cost
        ))
        chosen = []
        spent = 0
        for card in playable:
            if spent + card.cost <= energy_available:
                chosen.append(card)
                spent += card.cost
        return chosen
    
    def choose_field_to_attack(self, unit, opponent):
        """Which field should this unit attack?"""
        # Attack the field where we have advantage or opponent is empty
        f0_opp = opponent.field_might(Location.FIELD_0)
        f1_opp = opponent.field_might(Location.FIELD_1)
        f0_us = self.p.field_might(Location.FIELD_0)
        f1_us = self.p.field_might(Location.FIELD_1)
        
        # Prefer field where we're stronger
        if f0_opp == 0: return Location.FIELD_0
        if f1_opp == 0: return Location.FIELD_1
        
        # Attack where we have most advantage
        adv0 = unit.attack_might - f0_opp
        adv1 = unit.attack_might - f1_opp
        return Location.FIELD_0 if adv0 >= adv1 else Location.FIELD_1
    
    def choose_deployment_field(self, unit):
        """Where to send a newly played unit?"""
        f0 = self.p.field_might(Location.FIELD_0)
        f1 = self.p.field_might(Location.FIELD_1)
        # Balance fields
        return Location.FIELD_0 if f0 <= f1 else Location.FIELD_1

class AzirAI(DeckAI):
    """Azir: flood both fields with tokens, use equipment to trigger legend."""
    
    def choose_cards_to_play(self, energy, opponent):
        chosen = []
        spent = 0
        # Priority: equipment first (triggers legend), then units
        equip = [c for c in self.p.hand if c.is_gear and c.cost <= energy]
        units = [c for c in self.p.hand if c.is_unit and c.cost <= energy]
        spells = [c for c in self.p.hand if c.is_spell and c.cost <= energy]
        
        for card in equip + units + spells:
            if spent + card.cost <= energy:
                chosen.append(card)
                spent += card.cost
        return chosen
    
    def choose_deployment_field(self, unit):
        # Flood both fields equally
        f0 = len(self.p.units_at(Location.FIELD_0))
        f1 = len(self.p.units_at(Location.FIELD_1))
        return Location.FIELD_0 if f0 <= f1 else Location.FIELD_1

class VolibearAI(DeckAI):
    """Voli: ramp early, Firebrand+Stormbringer combo, then big units."""
    
    def get_dragon_discount(self):
        return getattr(self.p, '_dragon_discount', 0)
    
    def effective_cost(self, card):
        cost = card.cost
        # Dragon discount from Herald of Scales
        if card.base_might >= 5 and self.get_dragon_discount() > 0:
            cost = max(1, cost - self.get_dragon_discount())
        return cost
    
    def choose_cards_to_play(self, energy, opponent):
        chosen = []
        spent = 0
        
        # Priority 1: Ramp spells (Mobilize channels 1, Catalyst channels 2)
        ramp = [c for c in self.p.hand if c.is_spell and 
                ('channel' in (c.raw_ability or '').lower()) and 
                c.cost <= energy - spent]
        
        # Priority 2: Herald of Scales (reduces dragon costs)
        herald = [c for c in self.p.hand if 'herald' in c.name.lower() and 
                  self.effective_cost(c) <= energy - spent]
        
        # Priority 3: Firebrand + Stormbringer combo (7 total energy)
        firebrand = [c for c in self.p.hand if 'firebrand' in c.name.lower() and 
                     self.effective_cost(c) <= energy - spent]
        stormbringer = [c for c in self.p.hand if 'stormbringer' in c.name.lower() and 
                        'signature' not in c.card_type.lower()]
        
        # Priority 4: Big dragons (with discount)
        big = [c for c in self.p.hand if c.is_unit and c.base_might >= 5 and 
               self.effective_cost(c) <= energy - spent]
        big.sort(key=lambda c: -c.base_might)
        
        # Priority 5: Small units to hold fields
        small = [c for c in self.p.hand if c.is_unit and c.base_might < 5 and 
                 self.effective_cost(c) <= energy - spent]
        
        # Priority 6: Other spells
        other_spells = [c for c in self.p.hand if c.is_spell and c not in ramp and 
                        self.effective_cost(c) <= energy - spent]
        
        # Play in order
        for card in ramp + herald + firebrand + big + small + other_spells:
            if card in chosen: continue
            cost = self.effective_cost(card)
            
            # Special: if we have Firebrand, play Stormbringer after for 1 rune
            if 'firebrand' in card.name.lower() and spent + cost <= energy:
                chosen.append(card)
                spent += cost
                # Now Stormbringer costs 1
                for sb in stormbringer:
                    if sb not in chosen and spent + 1 <= energy:
                        chosen.append(sb)
                        spent += 1
                        self._log(f"Firebrand+Stormbringer COMBO!")
                continue
            
            if spent + cost <= energy:
                chosen.append(card)
                spent += cost
        
        return chosen
    
    def _log(self, msg):
        pass  # override if needed

class MFAI(DeckAI):
    """MF: get Trinity Force equipped, use GANKING, score passively."""
    
    def choose_cards_to_play(self, energy, opponent):
        chosen = []
        spent = 0
        # Priority: Trinity Force equip, then mobile units
        trinity = [c for c in self.p.hand if 'trinity' in c.name.lower() and c.cost <= energy]
        mobile = [c for c in self.p.hand if (c.ab.get('ganking') or c.ab.get('accelerate')) and c.is_unit and c.cost <= energy]
        other = [c for c in self.p.hand if c.is_unit and c not in mobile and c.cost <= energy]
        spells = [c for c in self.p.hand if c.is_spell and c.cost <= energy]
        
        for card in trinity + mobile + other + spells:
            if spent + card.cost <= energy and card not in chosen:
                chosen.append(card)
                spent += card.cost
        return chosen

class DravenAI(DeckAI):
    """Draven: ASSAULT units everywhere, hold pump spells for reactions."""
    
    def choose_cards_to_play(self, energy, opponent):
        chosen = []
        spent = 0
        # Priority: ASSAULT/ready units, then hold pump spells as reactions
        assault = [c for c in self.p.hand if (c.ab.get('assault') or c.ab.get('accelerate')) and c.is_unit and c.cost <= energy]
        normal = [c for c in self.p.hand if c.is_unit and c not in assault and c.cost <= energy]
        # Hold Blood Rush / Against the Odds as reactions — don't proactively play
        proactive_spells = [c for c in self.p.hand if c.is_spell and c.cost <= energy and 'reaction' not in c.raw_ability.lower()]
        
        for card in assault + normal + proactive_spells:
            if spent + card.cost <= energy and card not in chosen:
                chosen.append(card)
                spent += card.cost
        return chosen

# ============================================================
# GAME ENGINE
# ============================================================

class RiftboundGame:
    """
    Full Riftbound game simulation.
    """
    
    WIN_SCORE = 8
    
    def __init__(self, p1_config, p2_config, verbose=False):
        """
        p1_config = {
            'deck': {cid: qty, ...},
            'legend': cid,
            'champion': cid,
            'archetype': 'AZIR'|'VOLI'|'MF'|'DRAVEN'|'generic',
            'name': 'deck name'
        }
        """
        self.verbose = verbose
        self.turn = 0
        self.max_turns = 25
        
        self.p1 = Player(1, p1_config['deck'], p1_config.get('legend'),
                        p1_config.get('champion'), p1_config.get('name','P1'))
        self.p2 = Player(2, p2_config['deck'], p2_config.get('legend'),
                        p2_config.get('champion'), p2_config.get('name','P2'))
        
        # Set up AIs
        ai_map = {'AZIR': AzirAI, 'VOLI': VolibearAI, 'MF': MFAI, 'DRAVEN': DravenAI}
        ai1 = ai_map.get(p1_config.get('archetype',''), DeckAI)
        ai2 = ai_map.get(p2_config.get('archetype',''), DeckAI)
        self.ai1 = ai1(self.p1, p1_config.get('archetype',''))
        self.ai2 = ai2(self.p2, p2_config.get('archetype',''))
        
        self.winner = None
        self.log = []
    
    def _log(self, msg):
        if self.verbose:
            self.log.append(f"T{self.turn}: {msg}")
    
    def check_win(self):
        if self.p1.score >= self.WIN_SCORE:
            self.winner = 1
            return True
        if self.p2.score >= self.WIN_SCORE:
            self.winner = 2
            return True
        return False
    
    def phase_awaken(self, player):
        """A - Ready all units."""
        player.ready_all()
        player.reset_turn_tracking()
        self._log(f"P{player.pid} AWAKEN")
    
    def phase_beginning(self, player, opponent):
        """B - Score held fields, kill TEMPORARY units."""
        # Kill temporary units
        to_kill = [u for u in player.units if u.temporary and u.location != Location.BASE]
        for u in to_kill:
            player.units.remove(u)
            player.trash.append(u.card)
            self._log(f"TEMPORARY {u.card.name} dies")
        
        # Score fields
        for field in [Location.FIELD_0, Location.FIELD_1]:
            our_m = player.field_might(field)
            opp_m = opponent.field_might(field)
            
            if our_m > opp_m:
                pts = 1 + player.passive_score_at(field)
                player.score += pts
                self._log(f"P{player.pid} scores {pts} at {field.value} ({our_m}M vs {opp_m}M)")
    
    def phase_channel(self, player):
        """C - Channel 2 runes."""
        gained = player.channel_runes(2)
        player.energy += player.gold_tokens
        player.gold_tokens = 0
        self._log(f"P{player.pid} channels {gained} runes, energy={player.energy}")
    
    def phase_draw(self, player):
        """D - Draw 1 card."""
        drawn = player.draw(1)
        self._log(f"P{player.pid} draws {[c.name for c in drawn]}")
    
    def phase_main(self, player, opponent, ai):
        """E - Play cards, attack."""
        energy = player.energy
        
        # Play cards from hand
        cards_to_play = ai.choose_cards_to_play(energy, opponent)
        
        for card in cards_to_play:
            if card not in player.hand:
                continue
            if card.cost > player.energy:
                continue
            
            player.hand.remove(card)
            player.energy -= card.cost
            player.cards_played_this_turn += 1
            
            if card.is_gear:
                player.equipment_played_this_turn += 1
                player.gold_tokens += 1  # gold token if gold gear
                self._log(f"P{player.pid} plays gear {card.name}")
                
            elif card.is_unit:
                # Apply dragon discount
                dragon_discount = getattr(player, '_dragon_discount', 0)
                if dragon_discount > 0 and card.base_might >= 5:
                    actual_cost = max(1, card.cost - dragon_discount)
                    player.energy += (card.cost - actual_cost)  # refund discount
                
                # Discard synergy (Chemtech Enforcer)
                if card.ab.get('discard_out') or 'discard 1' in card.raw_ability.lower():
                    if player.hand:
                        discarded = player.hand.pop(0)
                        player.trash.append(discarded)
                        player.discarded_this_turn = True
                        self._log(f"P{player.pid} discards {discarded.name}")
                        
                        # Check for discard-activated units (Flame Chompers, Raging Soul)
                        if 'when you discard me' in discarded.raw_ability.lower():
                            # Play it for 1 rune
                            if player.energy >= 1:
                                player.energy -= 1
                                unit = UnitOnBoard(discarded, player.pid)
                                field = ai.choose_deployment_field(unit)
                                unit.location = field
                                if discarded.ab.get('accelerate') or discarded.ab.get('enters_ready'):
                                    unit.exhausted = False
                                player.units.append(unit)
                                self._log(f"P{player.pid} plays {discarded.name} from discard")
                        
                        # Raging Soul: if discarded this turn, gains ASSAULT+GANKING
                        for h in player.hand:
                            if 'raging soul' in h.name.lower() or 'if you.*discard' in h.raw_ability.lower():
                                pass  # tracked on unit creation
                
                # Create unit on board
                unit = UnitOnBoard(card, player.pid)
                
                # Confront: units enter ready this turn
                if getattr(player, '_confront_active', False):
                    unit.exhausted = False
                
                # Raging Soul activation
                if player.discarded_this_turn and 'if you' in card.raw_ability.lower() and 'discard' in card.raw_ability.lower():
                    unit.has_assault = max(unit.has_assault, 1)
                    unit.has_ganking = True
                
                # LEGION bonus
                if card.ab.get('legion') and player.cards_played_this_turn > 1:
                    # LEGION effects vary — simplified: cost was already reduced when chosen
                    pass
                
                # Deploy to field
                if card.ab.get('accelerate') or card.ab.get('enters_ready'):
                    unit.exhausted = False  # enters ready
                
                field = ai.choose_deployment_field(unit)
                
                # GANKING units can go to either field
                unit.location = field
                player.units.append(unit)
                
                # On-play effects
                self._apply_on_play(card, unit, player, opponent)
                
                self._log(f"P{player.pid} plays {card.name} ({unit.base_might}M) to {field.value}")
            
            elif card.is_spell:
                self._apply_spell(card, player, opponent)
                player.trash.append(card)
                self._log(f"P{player.pid} plays spell {card.name}")
        
        # LEGEND EFFECTS — Azir: if equipment played this turn, make Sand Soldier
        if not player.legend_exhausted and player.legend:
            if 'azir' in player.legend.name.lower():
                if player.equipment_played_this_turn > 0 and player.energy >= 1:
                    player.energy -= 1
                    player.legend_exhausted = True
                    soldier = UnitOnBoard(SAND_SOLDIER, player.pid, Location.BASE)
                    soldier.exhausted = True  # goes to base, moves next turn
                    player.units.append(soldier)
                    self._log(f"Azir legend: Sand Soldier created")
        
        # ATTACK PHASE
        self._attack_phase(player, opponent, ai)
        
        # DRAVEN: Champion attack (deals direct damage)
        if player.champion and not player.champion.exhausted:
            if 'draven' in (player.champion.card.name if player.champion else '').lower():
                # Draven Vanquisher attacks a field
                pass  # handled in attack phase
    
    def _apply_on_play(self, card, unit, player, opponent):
        """Apply on-play effects for a unit."""
        raw = card.raw_ability.lower()
        
        # Herald of Scales: dragons cost 2 less
        if 'herald' in card.name.lower() and "dragon" in raw and 'energy cost' in raw:
            player._dragon_discount = getattr(player, '_dragon_discount', 0) + 2
        
        # Sand Soldier generation
        if 'sand soldier' in raw and 'play' in raw:
            n = 2 if 'two' in raw else 1
            for _ in range(n):
                s = UnitOnBoard(SAND_SOLDIER, player.pid, Location.BASE)
                player.units.append(s)
        
        # Mech token generation (Ferrous Forerunner deathknell)
        # Draw on play
        if card.ab.get('draw_on_play'):
            player.draw(1)
        
        # Blitzcrank: pull enemy unit to this field
        if 'blitzcrank' in card.name.lower():
            opp_units = [u for u in opponent.units if u.location not in (Location.BASE, Location.CHAMPION_ZONE)]
            if opp_units:
                target = random.choice(opp_units)
                target.location = unit.location
        
        # Brynhir: opponents can't play cards this turn
        if 'brynhir' in card.name.lower():
            opponent.energy = 0  # effectively prevents plays (simplified)
        
        # Spectral Matron: play unit cost ≤3 from hand
        if 'spectral matron' in card.name.lower():
            cheap = [c for c in player.hand if c.is_unit and c.cost <= 3]
            if cheap:
                bonus = cheap[0]
                player.hand.remove(bonus)
                bonus_unit = UnitOnBoard(bonus, player.pid, unit.location)
                player.units.append(bonus_unit)
    
    def _apply_spell(self, card, player, opponent):
        """Apply spell effects."""
        raw = card.raw_ability.lower()
        
        # Mobilize: costs 2, channels 1 rune (adds 1 energy net -1)
        if 'mobilize' in card.name.lower() or ('channel 1 rune' in raw and 'cost' not in raw):
            player.energy += 1  # channels 1 rune = +1 energy this turn
        # Catalyst of Aeons: costs 4, channels 2 runes (net -2 but adds 2)
        elif 'catalyst' in card.name.lower() or 'channel 2 rune' in raw:
            player.energy += 2  # channels 2 runes = +2 energy this turn
        
        # Confront: units enter ready this turn (flag on player)
        if 'confront' in card.name.lower() or ('enter ready' in raw and 'this turn' in raw):
            player._confront_active = True
            
        # Draw from Confront
        if 'confront' in card.name.lower():
            player.draw(1)
        
        # Draw effects
        if 'draw 2' in raw:
            player.draw(2)
        elif 'draw 1' in raw:
            player.draw(1)
        
        # Removal
        if 'deal 4' in raw or 'deal 5' in raw or 'deal 6' in raw or 'deal 9' in raw:
            # Remove weakest opponent unit at any field
            opp_units = [u for u in opponent.units if u.location in (Location.FIELD_0, Location.FIELD_1)]
            if opp_units:
                target = min(opp_units, key=lambda u: u.base_might)
                opponent.units.remove(target)
                opponent.trash.append(target.card)
        
        # Bounce (Gust, Rebuke)
        if 'return a unit' in raw or 'return an' in raw:
            opp_units = [u for u in opponent.units if u.location in (Location.FIELD_0, Location.FIELD_1)]
            small = [u for u in opp_units if u.base_might <= 3]
            if small:
                target = min(small, key=lambda u: u.base_might)
                opponent.units.remove(target)
                # Unit goes to opponent's hand as card
                opponent.hand.append(target.card)
        
        # Blood Rush: give a unit ASSAULT 2
        if 'blood rush' in card.name.lower() or ('assault 2' in raw and 'give' in raw):
            friendly = [u for u in player.units if u.location in (Location.FIELD_0, Location.FIELD_1)]
            if friendly:
                best = max(friendly, key=lambda u: u.base_might)
                best.has_assault = max(best.has_assault, 2)
        
        # Dangerous Duo: +2M to a unit
        if 'dangerous duo' in card.name.lower() or ('+2 might' in raw and 'legion' in raw):
            friendly = [u for u in player.units if u.location in (Location.FIELD_0, Location.FIELD_1)]
            if friendly:
                best = max(friendly, key=lambda u: u.base_might)
                best.buffs += 2
        
        # Fading Memories: give unit TEMPORARY
        if 'fading memories' in card.name.lower() or ('temporary' in raw and 'give' in raw):
            opp_units = [u for u in opponent.units if u.location in (Location.FIELD_0, Location.FIELD_1)]
            if opp_units:
                target = max(opp_units, key=lambda u: u.base_might)
                target.temporary = True
        
        # Grand Strategem: +5M all friendly units this turn
        if 'grand strategem' in card.name.lower() or ('+5 might' in raw and 'friendly units' in raw):
            for u in player.units:
                u.buffs += 5
        
        # Sky Splitter: deal 5 to a unit (costs 8 minus biggest unit M)
        if 'sky splitter' in card.name.lower():
            opp_units = [u for u in opponent.units if u.location in (Location.FIELD_0, Location.FIELD_1)]
            if opp_units:
                target = max(opp_units, key=lambda u: u.base_might)
                opponent.units.remove(target)
                opponent.trash.append(target.card)
        
        # Stormbringer: teleport Kadregrin, deal 9 to field
        if 'stormbringer' in card.name.lower():
            opp_field_0 = [u for u in opponent.units if u.location == Location.FIELD_0]
            if opp_field_0:
                for u in opp_field_0:
                    opponent.units.remove(u)
                    opponent.trash.append(u.card)
    
    def _attack_phase(self, player, opponent, ai):
        """Handle all attacks for the active player."""
        # Units that can attack: at a field, not exhausted
        attackers_f0 = [u for u in player.units if u.location == Location.FIELD_0 and not u.exhausted]
        attackers_f1 = [u for u in player.units if u.location == Location.FIELD_1 and not u.exhausted]
        
        # GANKING units can attack from base too
        gankers = [u for u in player.units if u.has_ganking and not u.exhausted and u.location == Location.BASE]
        
        for field, attackers in [(Location.FIELD_0, attackers_f0), (Location.FIELD_1, attackers_f1)]:
            if not attackers:
                continue
            
            defenders = [u for u in opponent.units if u.location == field]
            
            won, dead_atk, dead_def, excess = resolve_field_combat(attackers, defenders)
            
            # Apply deaths
            for u in dead_atk:
                if u in player.units:
                    player.units.remove(u)
                    player.trash.append(u.card)
                    self._trigger_deathknell(u, player, opponent)
            
            for u in dead_def:
                if u in opponent.units:
                    opponent.units.remove(u)
                    opponent.trash.append(u.card)
                    self._trigger_deathknell(u, opponent, player)
            
            # Exhaust attackers
            for u in attackers:
                if u in player.units:
                    u.exhaust()
            
            # Conquest
            if won:
                player.conquered_this_turn = True
                self._log(f"P{player.pid} conquers {field.value} with {excess} excess damage")
                
                # Draven legend: draw on win
                if player.legend and 'draven' in player.legend.name.lower() and not player.legend_exhausted:
                    player.draw(1)
                    player.gold_tokens += 1
                    self._log(f"Draven legend: draw 1 + gold")
                
                # Tryndamere: 5+ excess = score 1 bonus point
                for u in attackers:
                    if 'tryndamere' in u.card.name.lower() and excess >= 5:
                        player.score += 1
                        self._log(f"Tryndamere bonus point!")
                
                # Volibear legend: if mighty unit won, channel rune
                if player.legend and 'volibear' in player.legend.name.lower():
                    mighty_atk = [u for u in attackers if u.is_mighty]
                    if mighty_atk and not player.legend_exhausted:
                        player.energy += 1
                        player.legend_exhausted = True
                
                # Move attackers to conquered field (they already are there, just confirm)
                for u in attackers:
                    if u in player.units:
                        u.location = field
    
    def _trigger_deathknell(self, unit, owner, opponent):
        """Trigger deathknell effects when a unit dies."""
        raw = unit.card.raw_ability.lower()
        
        if 'deathknell' not in raw:
            return
        
        # Draw
        if 'draw 1' in raw:
            owner.draw(1)
        elif 'draw 2' in raw:
            owner.draw(2)
        
        # Channel rune
        if 'channel 1 rune' in raw:
            owner.energy += 1
        
        # Make tokens
        if 'mech unit token' in raw and '3 might' in raw:
            for _ in range(2):
                t = UnitOnBoard(MECH_TOKEN_3, owner.pid, Location.BASE)
                owner.units.append(t)
        
        # Gold token
        if 'gold gear token' in raw:
            owner.gold_tokens += 1
        
        # Kog'Maw: deal 4 to all units at field
        if "kog'maw" in unit.card.name.lower() or ("deal 4" in raw and "all units" in raw):
            for loc in [Location.FIELD_0, Location.FIELD_1]:
                to_kill = [u for u in opponent.units if u.location == loc and u.base_might <= 4]
                for u in to_kill:
                    opponent.units.remove(u)
                    opponent.trash.append(u.card)
        
        # Undercover Agent: discard 2 draw 2
        if 'undercover' in unit.card.name.lower():
            if len(owner.hand) >= 2:
                for _ in range(2):
                    if owner.hand:
                        discarded = owner.hand.pop(0)
                        owner.trash.append(discarded)
                owner.draw(2)
    
    def play_game(self):
        """Run the full game. Returns winner (1 or 2)."""
        players = [(self.p1, self.p2, self.ai1), (self.p2, self.p1, self.ai2)]
        
        for turn in range(self.max_turns):
            self.turn = turn
            
            for active, passive, ai in players:
                # A - Awaken
                self.phase_awaken(active)
                
                # B - Beginning (score)
                self.phase_beginning(active, passive)
                if self.check_win(): return self.winner
                
                # C - Channel
                self.phase_channel(active)
                
                # D - Draw
                self.phase_draw(active)
                
                # E - Main Phase (play + attack)
                self.phase_main(active, passive, ai)
                if self.check_win(): return self.winner
        
        # Time limit: whoever has more score wins
        if self.p1.score > self.p2.score:
            return 1
        elif self.p2.score > self.p1.score:
            return 2
        else:
            return random.choice([1, 2])  # draw

# ============================================================
# SIMULATION RUNNER
# ============================================================

def run_simulation(config1, config2, n_games=1000, seed=42):
    """Run n_games between two deck configs. Returns win rate for deck 1."""
    random.seed(seed)
    wins = 0
    for i in range(n_games):
        random.seed(seed + i)
        game = RiftboundGame(config1, config2)
        winner = game.play_game()
        if winner == 1:
            wins += 1
    return wins / n_games * 100

# Quick smoke test
print("Engine loaded. Running smoke test (10 games)...")

AZIR_M={'SFD-153':3,'SFD-161':3,'SFD-033':3,'SFD-042':3,'SFD-051':1,'SFD-172':1,
    'SFD-031':3,'SFD-154':3,'SFD-198':1,'SFD-039':3,'SFD-038':3,'SFD-043':3,
    'SFD-034':1,'OGN-209':2,'OGN-213':2,'SFD-163':2,'OGN-058':3}
DRAVEN_M={'OGN-003':3,'OGN-006':3,'OGN-008':2,'OGN-012':2,'OGN-015':1,
    'OGN-016':3,'OGN-019':3,'OGN-026':1,'OGN-034':1,
    'SFD-001':3,'SFD-002':3,'SFD-003':3,'SFD-006':3,
    'SFD-011':1,'SFD-012':3,'SFD-013':2,'SFD-014':3}

azir_cfg = {'deck':AZIR_M,'legend':'SFD-197','champion':'SFD-177','archetype':'AZIR','name':'Azir'}
draven_cfg = {'deck':DRAVEN_M,'legend':'SFD-185','champion':'SFD-020','archetype':'DRAVEN','name':'Draven'}

for i in range(3):
    random.seed(i*100)
    g = RiftboundGame(azir_cfg, draven_cfg, verbose=True)
    w = g.play_game()
    print(f"Game {i+1}: P{w} wins (Azir={g.p1.score} Draven={g.p2.score})")
    for line in g.log[-5:]:
        print(f"  {line}")

print("\nEngine working.")
