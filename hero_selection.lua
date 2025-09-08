local config = require('bots/config')
local timeout = 0. -- 30.

local done = false

function Think()
	if done then
		return
	end

	local team_id = GetTeam()
	local player_ids = GetTeamPlayers(team_id)

	if team_id == TEAM_RADIANT then
		heroes = config.radiant.heroes
		control = config.radiant.control
	else
		heroes = config.dire.heroes
		control = config.dire.control
	end

	if RealTime() > timeout then
		for i = 1, #player_ids do
			player_id = player_ids[i]
			if control[i] ~= config.constants.player_type.HUMAN and IsPlayerBot(player_id) and IsPlayerInHeroSelectionControl(player_id) then
				if config.print then
					print(string.format("HERO_SELECTION: %d, player_id %d, hero %s.", i-1, player_id, heroes[i]))
				end
				SelectHero(player_id, heroes[i])
			end
		end

		done = true
	end
end

function GetBotNames()
	if GetTeam() == TEAM_RADIANT then
		return { 'A', 'B', 'C', 'D', 'E' }
	elseif GetTeam() == TEAM_DIRE then
		return { 'F', 'G', 'H', 'I', 'J' }
	end
end

function UpdateLaneAssignments()
	return {
		[1] = LANE_MID,
		[2] = LANE_TOP,
		[3] = LANE_TOP,
		[4] = LANE_BOT,
		[5] = LANE_BOT,
		[6] = LANE_MID,
		[7] = LANE_TOP,
		[8] = LANE_TOP,
		[9] = LANE_BOT,
		[10] = LANE_BOT
	}
end
