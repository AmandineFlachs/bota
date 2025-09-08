-- When the game begins some PlayerIDs are skipped, i.e. only a subset of all the expected Think() calls are actually done,
-- when host_timescale is set too high (> 8.0).
-- Once all the PlayerIDs have been seen they are never missing any longer.
-- All bots seem to be present at GameTime() > 7.6, and controllable at 9.0.

local config_print = false

local last_game_time = -100.0 -- In seconds.
local last_real_time = -100.0 -- In seconds.
local last_action_target_game_time = -100.0 -- In seconds.
local last_action_game_time = -100.0 -- In seconds.
local num_skipped_ticks = 0

local action_pending = false
local action_target_game_time = -1 -- In seconds.

function is_valid_tick(player_id, game_time)
	return game_time > 9.5
end

local function AgentThink()
	local bot = GetBot()
	local player_id = bot:GetPlayerID()
	local team_id = GetTeam()
	local game_time = GameTime()
	local real_time = RealTime()

	-- Do nothing if it's too early, either because the game just started and all the bots are not calling Think() or
	-- because the last call is too early.
	if not is_valid_tick(player_id, game_time) then
		num_skipped_ticks = num_skipped_ticks + 1
		return
	else
		-- print(string.format("Tick: %f %f %d", game_time, (game_time - last_game_time) * 1000.0, num_skipped_ticks))
		num_skipped_ticks = 0
	end

	-- The server uses sockets to receive the 2 CMsgBotWorldState that the game sends, and writes 1 file for each team,
	-- which are going to be read by each player of the team here.
	if not action_pending then
		local filename = "bots/action_" .. team_id
		local load_actions = loadfile(filename)
		if load_actions ~= nil then
			load_actions()
			action_target_game_time = get_action_target_game_time()
			if last_action_target_game_time < action_target_game_time then -- Action has not been already executed.
				action_pending = true
			end
		else
			print(string.format("ERROR: CANNOT LOAD FILE: %s", filename))
		end
	end

	if action_pending and game_time >= action_target_game_time then
		if config_print then
			print(string.format("PlayerID %d at game time %f received action for game time %f (diff recv/targ: %.1fms; diff last: %.1fms).", player_id, game_time, action_target_game_time, (game_time - action_target_game_time) * 1000.0, (game_time - last_action_game_time) * 1000.0))
			-- print(string.format("PlayerID %d at game time %f received action for game time %f (diff: %.1fms).", player_id, game_time, action_target_game_time, (game_time - action_target_game_time) * 1000.0))
			-- print(string.format("Between 2 actions: %f %f (diff: %.1fms)", game_time, last_action_game_time, (game_time - last_action_game_time) * 1000.0))
			-- print(string.format("Action: %f %f", game_time, (real_time - last_real_time) * 1000.0))
		end

		act(bot, player_id)

		action_pending = false
		last_action_target_game_time = action_target_game_time
		last_action_game_time = game_time
	end

	-- Update time since last non-skipped Think() call, for this PlayerID.
	last_game_time = game_time
	last_real_time = real_time
end

-- -- Bots configuration -- --

-- The game calls this code once for each bot, then starts calling Think().

local config = require('bots/config')
config_print = config.print

local function DoNotThink() end

local team_id = GetTeam()
local player_ids = GetTeamPlayers(team_id)
local bot = GetBot()
local player_id = bot:GetPlayerID()
local unit_name = bot:GetUnitName()

if team_id == TEAM_RADIANT then
	heroes = config.radiant.heroes
	control = config.radiant.control
	offset = 0
else
	heroes = config.dire.heroes
	control = config.dire.control
	offset = 5
end

if control[player_id - offset + 1] == config.constants.player_type.AGENT then
	if config_print then
		print(string.format("BOT_GENERIC: agent, team_id %d, player_id %d, hero %s.", team_id, player_id, unit_name))
	end
	Think = AgentThink
elseif control[player_id - offset + 1] == config.constants.player_type.BOT then
	if config_print then
		difficulty_list = { "passive", "easy", "medium", "hard", "unfair" }
		print(string.format("BOT_GENERIC: bot (%s), team_id %d, player_id %d, hero %s.", difficulty_list[bot:GetDifficulty()+1], team_id, player_id, unit_name))
	end
	Think = Think
else
	if config_print then
		print(string.format("BOT_GENERIC: empty, team_id %d, player_id %d, hero %s.", team_id, player_id, unit_name))
	end
	Think = DoNotThink
end
