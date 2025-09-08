import os
from enum import Enum, auto

def get_path(key, config, escape_spaces=False):
	steam_library_path = os.path.expanduser(config["steam_library_path"])

	paths = {
		"sniper": "steamapps/common/SteamLinuxRuntime_sniper/run-in-sniper",
		"dota_sh": "steamapps/common/dota 2 beta/game/dota.sh",
		"dota_custom_sh": "steamapps/common/dota 2 beta/game/dota_custom.sh",
		"bots_folder": "steamapps/common/dota 2 beta/game/dota/scripts/vscripts/bots/",
	}

	if not key in paths.keys():
		print(f"utils.get_path: unknown key \'{key}\'.")
		return ""

	p = os.path.join(steam_library_path, paths[key])

	if escape_spaces:
		p = p.replace(" ", "\ ")
	
	return p

def generate_lua_config(config, print_lua, lua_filename):
	prefix = """local constants = {
	player_type = {
		HUMAN = 0,
		AGENT = 1,
		BOT = 2,
		EMPTY = 3
	}
}

local config = {
	constants = constants,
"""

	suffix = """
}

return config\n"""

	with open(lua_filename, 'w+') as lua_file:
		s = prefix
		s += '	print = ' + ('true' if print_lua else 'false') + ',\n'
		for team in ['radiant', 'dire']:
			s += '	' + team + ' = {\n'
			for field in ['control', 'heroes']:
				s += '		' + field + ' = {\n'
				for i in config[team][field]:
					if field == 'control':
						s += '			constants.player_type.' + i + ',\n'
					else:
						s += '			\"' + i + '\",\n'
				s += '		' + '},\n'
			s += '	},\n'
		s += suffix
		lua_file.write(s)

# Check existence and type of field under a given parent.
def check_field(config, field_name, field_type, parent_name=None):
	parent = config[parent_name] if parent_name else config
	parent_str = parent_name + "." if parent_name else ""

	if field_name not in parent:
		return False, "missing " + parent_str + field_name
	if field_type is not None and not isinstance(parent[field_name], field_type):
		try: # If type does not match directly, try to cast to type, for instance float('3e-4') is valid.
			casted_value = field_type(parent[field_name])
			return True, ""
		except:
			return False, "invalid " + parent_str + field_name
	return True, ""

def check_config(config):
	if "steam_library_path" not in config:
		return False, "Field 'steam_library_path' is missing from config"

	team_fields = [
		("address", str),
		("port", int),
		("control", list),
		("heroes", list),
	]

	for team in ["radiant", "dire"]:
		for field_name, field_type in team_fields:
			ok, msg = check_field(config, field_name, field_type, team)
			if not ok:
				return ok, msg

		if len(config[team]["control"]) != 5:
			return False, f"invalid list for {team}.control (should contain 5 items)"

		if len(config[team]["heroes"]) != 5:
			return False, f"invalid list for {team}.heroes (should contain 5 items)"

		for control in config[team]["control"]:
			if control not in ("AGENT', 'BOT", "EMPTY", "HUMAN"):
				return False, f"invalid control type: {control}. Valid options are: [AGENT, BOT, EMPTY, HUMAN]"

	return True, ""

def should_team_observe(controls, record_players=[]):
	# Conditions for a team to observe:
	# - At least one agent.
	# - At least one player type (control) present in player types we record (record_players).

	for control in controls:
		if control == 'AGENT' or control in record_players:
			return True
	return False

def should_team_act(controls):
	# Conditions for a team to act:
	# - At least one agent.

	for control in controls:
		if control == 'AGENT':
			return True
	return False

class END_OF_GAME(Enum):
	GAME_NOT_OVER = auto()
	RADIANT_WINS = auto()
	DIRE_WINS = auto()

def get_end_of_game(config):
	with open(os.path.join(get_path("bots_folder", config), "log.txt")) as f:
		string = f.read()

		radiant_wins = string.find("good guys win = 1") != -1 or string.find("Building: npc_dota_badguys_fort destroyed") != -1
		dire_wins = string.find("good guys win = 0") != -1 or string.find("Building: npc_dota_goodguys_fort destroyed") != -1

		if not radiant_wins and not dire_wins:
			return END_OF_GAME.GAME_NOT_OVER
		else:
			if radiant_wins:
				return END_OF_GAME.RADIANT_WINS
			else:
				return END_OF_GAME.DIRE_WINS
