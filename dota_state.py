from dota_gcmessages_common_bot_script_pb2 import CMsgBotWorldState

TEAM_RADIANT = 2
TEAM_DIRE = 3

UNIT_TYPE_HERO = CMsgBotWorldState.UnitType.Value("HERO")
UNIT_TYPE_TOWER = CMsgBotWorldState.UnitType.Value("TOWER")
UNIT_TYPE_CREEP_HERO = CMsgBotWorldState.UnitType.Value("CREEP_HERO")
UNIT_TYPE_LANE_CREEP = CMsgBotWorldState.UnitType.Value("LANE_CREEP")

def extract_player_unit(observation, player_id):
	try:
		return next(filter(lambda unit: is_unit_hero(unit) and unit.player_id == player_id, observation.units))
	except StopIteration:
		return None

def extract_tower_unit(observation):
	try:
		return next(filter(lambda unit: is_unit_mid_tower1(unit) and unit.team_id == observation.team_id, observation.units))
	except StopIteration:
		return None

def extract_enemy_tower_unit(observation):
	try:
		return next(filter(lambda unit: is_unit_mid_tower1(unit) and unit.team_id != observation.team_id, observation.units))
	except StopIteration:
		return None

def is_unit_hero(unit):
	return unit.unit_type == UNIT_TYPE_HERO

def is_unit_tower(unit):
	return unit.unit_type == UNIT_TYPE_TOWER

def is_unit_creep(unit):
	return unit.unit_type == UNIT_TYPE_CREEP_HERO or unit.unit_type == UNIT_TYPE_LANE_CREEP

def is_unit_mid_tower1(unit):
	return unit.unit_type == UNIT_TYPE_TOWER and (unit.name == "npc_dota_goodguys_tower1_mid" or unit.name == "npc_dota_badguys_tower1_mid")

def is_unit1_attacking_unit2(unit1, unit2):
	for projectile in unit2.incoming_tracking_projectiles:
		if projectile.caster_handle == unit1.handle and projectile.is_attack:
			return True

	return unit1.attack_target_handle == unit2.handle
