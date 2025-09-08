import os
import re
import yaml
import struct
import asyncio
import warnings
import psutil

from time import time, sleep

# Com with game.
from google.protobuf import message
from dota_gcmessages_common_bot_script_pb2 import CMsgBotWorldState

from openai import AsyncOpenAI
from agents import Agent, Runner, ModelSettings, OpenAIResponsesModel

import utils
import dota_state

agent = Agent(
	name="Assistant",
	instructions="You only respond the action you decided to perform.",
	model=OpenAIResponsesModel(
		model="openai/gpt-oss-20b",
		openai_client=AsyncOpenAI(
			base_url="http://localhost:8000/v1",
			api_key="EMPTY",
		),
	),
	model_settings=ModelSettings(reasoning={ "effort": "low" }),
)

def is_valid_tick(worldstate):
	# NOTE: if timescale is set too high, last players are missing from teams, even though other players can still play.
	# We skip the first tick as the game doesn't need an action for it.
	return worldstate.game_time > 9.5 and len(worldstate.units) != 0

# One observation per team.
class Dota2TeamEnvWrapper:
	def __init__(self, team_id, player_ids, config):
		self.config = config
		self.team_id = team_id
		self.player_ids = player_ids

		self.is_first_tick = {player_id:True for player_id in player_ids}

		self.num_auto_ticks = 0
		self.prev_actions = {player_id:None for player_id in player_ids}

	def get_hero_status(self, player_id, player_unit):
		if player_unit is None or not player_unit.is_alive or player_unit.is_stunned:
			return "You cannot do anything."
		else:
			if player_unit.is_rooted:
				return "You cannot move."

			if player_unit.is_disarmed:
				return "You cannot attack."

			if player_unit.is_silenced:
				return "You cannot cast spells."

		return ""

	def generate_action(self, action_time, player_ids):
		actions_string = "function get_action_target_game_time() return " + str(action_time) + " end\n" \
			"function act(bot, player_id)\n" \
			"	local action_table = {\n"
		for player_id in player_ids:
			actions_string += "		[" + str(player_id) + "] = act_" + str(player_id) + ",\n"
		actions_string += "	}\n" \
			"	return action_table[player_id](bot)\n" \
			"end\n"
		return actions_string

	def write_action_code(self, team_id, actions):
		filename = os.path.join(utils.get_path("bots_folder", self.config), "action_" + str(team_id) + ".lua")
		f = open(filename, "w")
		f.write(actions)
		f.close()

	def are_first_actions_done(self, player_unit):
		return player_unit.ability_points == 0

	def generate_hardcoded_first_actions(self, player_id, player_unit):
		# NOTE: we use a condition in LUA to check that the state we have got in Python is still valid when the LUA code is executed, otherwise some actions can be repeated several times.

		if player_unit.name == "npc_dota_hero_queenofpain":
			ability = "queenofpain_shadow_strike"
		elif player_unit.name == "npc_dota_hero_furion":
			ability = "furion_sprout"
		else:
			ability = ""

		function_body = " if bot:GetAbilityPoints() ~= 0 then bot:ActionImmediate_LevelAbility(\'" + ability + "\') end " # We use a LUA condition to avoid repeating action several times in case latency between python write and lua read.

		item_name = "item_flask"
		function_body += " if bot:GetItemInSlot(0) == nil and GetItemCost(\'" + item_name + "\') <= bot:GetGold() then bot:ActionImmediate_PurchaseItem(\'" + item_name + "\') end"

		# DEBUG:
		# function_body = 'print(\"' + function_body + '\") ' + function_body
		return "function act_" + str(player_id) + "(bot) " + function_body + " end\n"

	async def run(self, observation, units_attacking_hero):
		# print(observation)
		alive_units = list(filter(lambda unit: unit.is_alive, observation.units))

		heroes_units = list(filter(dota_state.is_unit_hero, alive_units))
		creeps_units = list(filter(dota_state.is_unit_creep, alive_units))
		towers_units = list(filter(dota_state.is_unit_mid_tower1, alive_units))

		ally_heroes_units = list(filter(lambda unit: unit.team_id == self.team_id, heroes_units))
		ally_towers_units = list(filter(lambda unit: unit.team_id == self.team_id, towers_units))
		ally_creeps_units = list(filter(lambda unit: unit.team_id == self.team_id, creeps_units))

		enemy_heroes_units = list(filter(lambda unit: unit.team_id != self.team_id, heroes_units))
		enemy_towers_units = list(filter(lambda unit: unit.team_id != self.team_id, towers_units))
		enemy_creeps_units = list(filter(lambda unit: unit.team_id != self.team_id, creeps_units))

		enemy_handles = [u.handle for u in enemy_heroes_units] + [u.handle for u in enemy_towers_units] + [u.handle for u in enemy_creeps_units]

		units_attacking_hero = list(set([u.handle for u in units_attacking_hero]))

		# print(ally_heroes_units)

		rules = "The first team that kills 2 times the other team hero or destroys the other team tower wins. Your hero can attack by calling Action_AttackUnit(X) with X the handle (integer) of the enemy you want to attack if your enemy is in your attack range. You can move your hero by calling Action_MoveDirectly(Vector(X, Y, Z)) with (X, Y, Z) the absolute coordinates you want to move to. You can also call Action_AttackAbilityUnit(X) with X the handle of the enemy you want to attack with your ability, it uses mana but it's powerful. You can use a healing flask when your hero is low on health (less than 40%) by calling Action_UseFlask(). You only respond the action you decided to perform. Protect your ally creeps but do not let your hero die. If ally creeps are not present, wait for them under your tower. If the hero health is low (less than 40%), make it go under the ally tower or use a healing flask to recover some of its health. Kill enemy creeps, especially attack them when their health is very low (less than 10%) as the last hit gives a bonus. Don't stay in attack range of the enemy tower unless ally creeps are with your hero otherwise the enemy tower will attack your hero. Do not stay close to enemy units. Attack them from a distance (you can attack units within your attack range). If your hero is being attacked, move out of range of the units attacking your hero. Stay behind your ally creeps, let them attack enemy other units. Your priority is for your hero and tower to stay alive. Do not die. Do not hesitate to your Action_AttackAbilityUnit on enemies."
		prompt = "What is your next action?"

		def pretty_print_unit(u):
			return f"Handle {u.handle}: health {u.health}/{u.health_max}, attack range {u.attack_range}, mana {u.mana}/{u.mana_max} at location ({u.location.x}, {u.location.y}, {u.location.z})"

		state = ""
		state += f"Your towers are: {[pretty_print_unit(i) for i in ally_towers_units]}\n"
		state += f"The enemy towers are: {[pretty_print_unit(i) for i in enemy_towers_units]}\n"
		state += f"Your ally creeps are: {[pretty_print_unit(i) for i in ally_creeps_units]}\n"
		state += f"The enemy creeps are: {[pretty_print_unit(i) for i in enemy_creeps_units]}\n"
		state += f"Handles of units currently attacking your hero: {[u for u in units_attacking_hero]}\n"
		if ally_heroes_units:
			has_item_flask = any([i.slot == 0 for i in ally_heroes_units[0].items])
			state += f"Your hero is: {pretty_print_unit(ally_heroes_units[0])} and has {1 if has_item_flask else 0} healing flask\n"
		if enemy_heroes_units:
			state += f"The enemy hero is: {pretty_print_unit(enemy_heroes_units[0])}\n"
		print(state)

		prompt = rules + " " + state + " " + prompt

		# String action_strings is generated per team because of how the LUA mechanism works.
		# If an ally player is missing from the observation, we generate empty action for this specific player and set all of its attribs to 0.

		players, actions, action_strings = [], [], ''

		for index, player_id in enumerate(self.player_ids):
			player_unit = dota_state.extract_player_unit(observation, player_id)

			if player_unit is not None:
				# We generate first actions (level up ability + buy items) until we detect it is done, which means we are not too early in the game, not too late, and the intermediate file has been read correctly (the file is sometimes corrupt when we start and sometimes orders are omitted because of this).
				if self.is_first_tick[player_id]: # We emit the LUA code until the Python code receives a state corresponding to what we expect. Because of the LUA ifs in generate_hardcoded_first_actions(), we guarantee not applying the action several times.
					if not self.are_first_actions_done(player_unit):
						action_strings += self.generate_hardcoded_first_actions(player_id, player_unit)
					else:
						self.is_first_tick[player_id] = False
				else:
					players.append((player_id, player_unit, index))
			else:
				# Generate empty action for current player in case the code runs too early (occurs when too early in game just after a human chose a hero, or when timeout of 30 in hero_selection).
				print('PlayerID {} inference skipped. Not in observation.'.format(player_id))
				players.append((player_id, None, index))

		if players != []:
			prev_time = time()

			inference_player_ids = [player_id for player_id, _, _ in players]

			actions = []
			for player_id, player_unit, index in players:
				if player_id in inference_player_ids:
					conversation = [{"content": prompt, "role": "user"}]
					try:
						result = await Runner.run(agent, input=conversation)
						print(result.raw_responses[0].output[0].content)
						print(result.final_output)
						function_body = result.final_output

						is_valid = False

						if handle := re.findall(r'Action_AttackUnit\(([0-9]+)\)', function_body):
							handle = int(handle[0])
							is_valid = handle in enemy_handles
							function_body = f"bot:Action_AttackUnit(GetBotByHandle({handle}), true)"
						elif handle := re.findall(r'Action_AttackAbilityUnit\(([0-9]+)\)', function_body):
							handle = int(handle[0])
							is_valid = handle in enemy_handles
							function_body = f"bot:Action_UseAbilityOnEntity(bot:GetAbilityInSlot(0), GetBotByHandle({handle}))"
						elif coords := re.findall(r'Action_MoveDirectly\(Vector\((.*),(.*),(.*)\)\)', function_body):
							try:
								[float(c) for c in coords[0]]
								is_valid = True
								function_body = "bot:" + function_body
							except:
								pass
						elif function_body == "Action_UseFlask()":
							item_name = 'item_flask'
							function_body = 'if bot:FindItemSlot(\'' + item_name + '\') ~= nil then bot:Action_UseAbilityOnEntity(bot:GetItemInSlot(bot:FindItemSlot(\'' + item_name + '\')), bot) end'
							is_valid = True

						if is_valid:
							print(f"VALID: {function_body}")
							text = result.raw_responses[0].output[0].content[0].text.replace("\'", "\\'")
							function_body = f"bot:ActionImmediate_Chat(\'{text}\', true)" + " " + function_body
							action = 'function act_' + str(player_id) + '(bot) ' + function_body + ' end\n'
						else:
							action = 'function act_' + str(player_id) + '(bot) end\n'
					except Exception as e:
						print(e)
						action = 'function act_' + str(player_id) + '(bot) end\n'
				else: # Repeat previous action:
					action = self.prev_actions[player_id]

				#print(player_id, action)

				action_strings += action
				self.prev_actions[player_id] = action
				actions.append(action)

			current_time = time()

			print(f"Inference time: {(current_time - prev_time) * 1000.0:.1f}ms")

		return action_strings

async def connect_to_game(server_address):
	while True:
		try:
			reader, _ = await asyncio.open_connection(host=server_address[0], port=server_address[1])
		except ConnectionRefusedError:
			sleep(0.1)
		else:
			print("Connected to: {server_address}")
			return reader

async def read_worldstate(reader):
	size, = struct.unpack("@I", await reader.readexactly(4))
	data = await reader.readexactly(size)
	return data

async def worldstate_to_action(team_id, server_address, control, config):
	print("Connect to game...", flush=True)

	while True:
		try:
			reader, _ = await asyncio.open_connection(host=server_address[0], port=server_address[1])
		except ConnectionRefusedError:
			sleep(0.1)
		else:
			print(f"Connected to: {server_address}")
			break

	offset = 0 if team_id == dota_state.TEAM_RADIANT else 5
	player_ids = [i + offset for i, v in enumerate(control) if v == "AGENT"]

	print(f"Team {team_id}: player_ids: {player_ids}")

	should_team_act = utils.should_team_act(control)

	print("Create wrapper...", flush=True)
	team = Dota2TeamEnvWrapper(
		team_id=team_id,
		player_ids=player_ids,
		config=config,
	)

	prev_time = time()
	prev_game_time = -100.
	next_game_time = -1

	units_attacking_hero = []

	# Process current team's worldstate.
	while True:
		try:
			data = await read_worldstate(reader)
		except (struct.error, asyncio.IncompleteReadError):
			print(f"Lost connection to {server_address}.")
			break

		worldstate = CMsgBotWorldState()

		try:
			with warnings.catch_warnings():
				warnings.simplefilter("error", category=RuntimeWarning) # Converts runtime warnings to SystemError exceptions.
				worldstate.ParseFromString(data)
		except (message.DecodeError, SystemError) as inst:
			# RuntimeWarning: Unexpected end-group tag: Not all data was converted
			print('{}: Decode error. {}. Skipping...'.format(team_id, inst))
			continue

		assert team_id == worldstate.team_id, '{} != {}'.format(team_id, worldstate.team_id)

		print(f"Received world state for game time {worldstate.game_time:.6f} and team id {team_id} (player ids {player_ids})")
		# print(f"Num units: {len(worldstate.units)}")

		current_time = time()
		print(f"CMsgBotWorldState: {len(data) / 1024.:.1f}KB (diff real time: {(current_time - prev_time) * 1000.0:.1f}ms, diff game time: {(worldstate.game_time - prev_game_time) * 1000.0:.1f}ms).")
		#print(f"game_time: {worldstate.game_time}, dota_time: {worldstate.dota_time}"")

		# Update units_attacking_hero even when we skip worldstates.
		alive_units = list(filter(lambda unit: unit.is_alive, worldstate.units))
		heroes_units = list(filter(dota_state.is_unit_hero, alive_units))
		ally_heroes_units = list(filter(lambda unit: unit.team_id == team_id, heroes_units))
		if ally_heroes_units:
			units_attacking_hero.extend(list(filter(lambda unit: dota_state.is_unit1_attacking_unit2(unit, ally_heroes_units[0]), alive_units)))

		if is_valid_tick(worldstate) and worldstate.game_time >= next_game_time:
			# print(worldstate)

			if should_team_act:
				action = await team.run(observation=worldstate, units_attacking_hero=units_attacking_hero)
				action += team.generate_action(worldstate.game_time + 0.01, player_ids)
				team.write_action_code(worldstate.team_id, action)
				print(action)
				next_game_time = worldstate.game_time + time() - prev_time
				units_attacking_hero = []
		else:
			print("SKIP")

		prev_time = current_time
		prev_game_time = worldstate.game_time

	end_of_game = utils.get_end_of_game(config)

	if end_of_game == utils.END_OF_GAME.GAME_NOT_OVER:
		print("Game not over...")
	elif end_of_game == utils.END_OF_GAME.RADIANT_WINS:
		print("Radiant wins.")
	elif end_of_game == utils.END_OF_GAME.DIRE_WINS:
		print("Dire wins.")

	if end_of_game != utils.END_OF_GAME.GAME_NOT_OVER:
		if (team_id == 2 and end_of_game == utils.END_OF_GAME.RADIANT_WINS) or (team_id == 3 and end_of_game == utils.END_OF_GAME.DIRE_WINS):
			print("My team wins.")
		else:
			print("My team loses.")

async def no_worldstate_to_action():
	return

def run():
	with open("config.yaml", "r") as config_file:
		config = yaml.load(config_file, Loader=yaml.SafeLoader)

	should_team_observe = {team_name: utils.should_team_observe(config[team_name]["control"]) for team_name in ["radiant", "dire"]}
	print(f"Should team observe: {should_team_observe}")

	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)

	tasks = asyncio.gather(
		worldstate_to_action(
			dota_state.TEAM_RADIANT,
			(config["radiant"]["address"], config["radiant"]["port"]),
			config["radiant"]["control"],
			config) if should_team_observe["radiant"] else no_worldstate_to_action(),
		worldstate_to_action(
			dota_state.TEAM_DIRE,
			(config["dire"]["address"], config["dire"]["port"]),
			config["dire"]["control"],
			config) if should_team_observe["dire"] else no_worldstate_to_action())
	try:
		loop.run_until_complete(tasks)
	except ConnectionResetError:
		print("Connection reset.", flush=True)
	except Exception as e:
		print(f"Exception: {e}", flush=True)

if __name__ == "__main__":
	try:
		run()
	finally:
		parent = psutil.Process()
		for child in parent.children(recursive=True):
			print(f"Killing subprocess {child}...")
			try:
				child.kill()
			except psutil.NoSuchProcess:
				continue
