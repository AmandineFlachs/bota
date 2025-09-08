import os
import yaml
import shutil
import subprocess

import utils

def run():
	print("Run...", flush=True)

	src_folder = os.getcwd()

	with open(os.path.join(src_folder, "config.yaml"), "r") as config_file:
		config = yaml.load(config_file, Loader=yaml.SafeLoader)

	dst_folder = utils.get_path("bots_folder", config)

	command_line = utils.get_path("sniper", config, escape_spaces=True) + " " + utils.get_path("dota_custom_sh", config, escape_spaces=True)

	print("Generating custom dota launch script...", flush=True)

	shutil.copy(utils.get_path("dota_sh", config), utils.get_path("dota_custom_sh", config))
	os.system(f"patch {utils.get_path('dota_custom_sh', config, escape_spaces=True)} < dota_sh.patch")

	print("Copying LUA files to Dota2 bot folder...", flush=True)

	# Remove content from bots folder (actually remove directory then recreate one):
	shutil.rmtree(dst_folder, ignore_errors=True)
	os.mkdir(dst_folder)

	# Copy LUA files:
	shutil.copy(os.path.join(src_folder, "hero_selection.lua"), dst_folder)
	shutil.copy(os.path.join(src_folder, "bot_generic.lua"), dst_folder)

	# Generate LUA config file from YAML:
	utils.generate_lua_config(config, False, os.path.join(dst_folder, "config.lua"))

	# Run game:
	subprocess.call(command_line, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

	print("Cleaning up LUA action files...", flush=True)

	# Remove temporary LUA files that have been created:
	action2_path = os.path.join(dst_folder, "action_2.lua")
	if os.path.isfile(action2_path):
		os.remove(os.path.join(action2_path))

	action3_path = os.path.join(dst_folder, "action_3.lua")
	if os.path.isfile(action3_path):
		os.remove(os.path.join(action3_path))

	# Print game outcome:
	end_of_game = utils.get_end_of_game(config)

	if end_of_game == utils.END_OF_GAME.GAME_NOT_OVER:
		print("Game not over...", flush=True)
	elif end_of_game == utils.END_OF_GAME.RADIANT_WINS:
		print("Radiant wins.", flush=True)
	elif end_of_game == utils.END_OF_GAME.DIRE_WINS:
		print("Dire wins.", flush=True)

if __name__ == "__main__":
	run()
