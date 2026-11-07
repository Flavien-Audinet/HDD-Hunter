#!/bin/zsh
# Arrête et retire le service (les données restent dans ~/Library/Application Support/HDDHunter).
LABEL="local.$(id -un).hddhunter"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Service arrêté." || echo "Le service ne tournait pas."
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
