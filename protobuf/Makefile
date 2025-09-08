all: valveext botpy

valveext: valveextensions.proto
	protoc valveextensions.proto --python_out=.

botpy: dota_gcmessages_common_bot_script.proto
	protoc dota_gcmessages_common_bot_script.proto --python_out=.

