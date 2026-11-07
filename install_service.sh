#!/bin/zsh
# Installe HDD Hunter comme service macOS : démarre à l'ouverture de session,
# tourne en continu et redémarre tout seul s'il plante.
#   ./install_service.sh            installe / met à jour
#   ./install_service.sh --awake    idem, et empêche le Mac de se mettre en veille tout seul
set -e
DIR="${0:A:h}"
LABEL="local.$(id -un).hddhunter"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DATA="$HOME/Library/Application Support/HDDHunter"
mkdir -p "$DATA" "$HOME/Library/LaunchAgents"

if [[ ! -x "$DIR/.venv/bin/python" ]]; then
  echo "Création de l'environnement Python…"
  uv venv -q --python 3.12 "$DIR/.venv"
fi
uv pip install -q --python "$DIR/.venv/bin/python" -r "$DIR/requirements.txt"

PROG="<string>$DIR/.venv/bin/python</string><string>$DIR/run.py</string>"
[[ "$1" == "--awake" ]] && PROG="<string>/usr/bin/caffeinate</string><string>-i</string>$PROG"

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>$PROG</array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$DATA/service.log</string>
  <key>StandardErrorPath</key><string>$DATA/service.log</string>
</dict></plist>
PL

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
# attendre que l'ancienne instance soit bien arrêtée avant de relancer
for i in {1..20}; do launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break; sleep 0.5; done
for i in {1..5}; do launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null && break; sleep 1; done
launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || { echo "Échec du démarrage du service"; exit 1; }
echo "HDD Hunter tourne en tâche de fond → http://127.0.0.1:8777"
