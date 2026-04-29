#!/usr/bin/env bash
set -euo pipefail

# Container post-create setup for OpenCode + oh-my-opencode.
# Called by devcontainer.json postCreateCommand via:
#   bash /opt/opencode-setup/devcontainer-template/setup-container.sh

# --- Color output helpers ---
info()  { printf '\033[0;34m[INFO]\033[0m %s\n' "$1"; }
warn()  { printf '\033[0;33m[WARN]\033[0m %s\n' "$1"; }
ok()    { printf '\033[0;32m[ OK ]\033[0m %s\n' "$1"; }
fail()  { printf '\033[0;31m[FAIL]\033[0m %s\n' "$1"; exit 1; }

# --- Step 1: Ensure PATH includes expected tool locations ---
export PATH="/usr/local/bin:$HOME/.local/bin:$HOME/.opencode/bin:$PATH"

# --- Step 2: Install additional dev tools ---
info "Installing additional development tools..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    ripgrep \
    jq \
    build-essential \
    tmux \
    fzf \
    fd-find
sudo rm -rf /var/lib/apt/lists/*

# Debian installs fd as "fdfind" due to a naming conflict
if command -v fdfind &>/dev/null && ! command -v fd &>/dev/null; then
    sudo ln -s "$(which fdfind)" /usr/local/bin/fd
fi
ok "Development tools installed (rg, jq, gcc/make, tmux, fzf, fd)"

# --- Step 3: Copy team config (pre-installer) ---
info "Copying team configuration..."
mkdir -p ~/.config/opencode ~/.local/share/opencode ~/.claude
cp /opt/opencode-auth.json ~/.local/share/opencode/auth.json
cp /opt/opencode-setup/opencode.json ~/.config/opencode/opencode.json
cp /opt/opencode-setup/config/oh-my-opencode.json ~/.config/opencode/oh-my-opencode.json
cp -r /opt/opencode-setup/config/skills ~/.config/opencode/skills
cp -r /opt/opencode-setup/config/commands ~/.config/opencode/commands
ln -sf /opt/opencode-setup/config/AGENTS.md ~/.config/opencode/AGENTS.md
ln -sf /opt/opencode-setup/config/AGENTS.md ~/.claude/CLAUDE.md
ok "Team config copied to ~/.config/opencode/ and ~/.claude/"

# --- Step 4: Install and run oh-my-opencode ---
info "Installing oh-my-opencode..."
OMO_VERSION="$(cat /opt/opencode-setup/.oh-my-opencode-version)"
npm install -g "oh-my-opencode@$OMO_VERSION"
oh-my-opencode install --no-tui --claude=no --gemini=no --copilot=yes
ok "oh-my-opencode installed"

# --- Step 4b: Install OpenSpec ---
info "Installing OpenSpec..."
OPENSPEC_VERSION="$(cat /opt/opencode-setup/.openspec-version)"
npm install -g "@fission-ai/openspec@$OPENSPEC_VERSION"
ok "OpenSpec $OPENSPEC_VERSION installed"

# --- Step 5: Re-copy team config (authoritative, overwrites installer defaults) ---
info "Restoring authoritative team config..."
cp /opt/opencode-setup/opencode.json ~/.config/opencode/opencode.json
cp /opt/opencode-setup/config/oh-my-opencode.json ~/.config/opencode/oh-my-opencode.json
ok "Team config restored"

# Override permissions to auto-allow — the sandbox container is the security boundary
jq '.permission = {"edit": "allow", "bash": "allow", "webfetch": "allow"}' \
    ~/.config/opencode/opencode.json > /tmp/opencode-config.json
cp /tmp/opencode-config.json ~/.config/opencode/opencode.json
rm -f /tmp/opencode-config.json
ok "Sandbox permissions set to auto-allow"

# --- Step 6: Configure git ---
info "Configuring git..."
git config --global safe.directory "*"
if [ -f "$HOME/.gitconfig.host" ]; then
    git config --global include.path "$HOME/.gitconfig.host"
    ok "Git includes host config (user.name, user.email, etc.)"
else
    warn "Host ~/.gitconfig not mounted — git user.name/email may need manual setup"
fi

# --- Step 6b: Configure Docker registry credentials ---
# When config.json is bind-mounted, Docker creates ~/.docker/ as root.
# Fix ownership so Docker can create buildx/, cli-plugins/, etc.
if [ -d "$HOME/.docker" ]; then
    sudo chown vscode:vscode "$HOME/.docker"
fi

if [ -f "$HOME/.docker/config.json" ]; then
    # Strip credential helpers that don't work inside containers
    if jq -e '.credsStore // .credHelpers' "$HOME/.docker/config.json" &>/dev/null; then
        info "Stripping credential helpers from Docker config (not available in container)..."
        jq 'del(.credsStore, .credHelpers)' "$HOME/.docker/config.json" > /tmp/docker-config.json
        cp /tmp/docker-config.json "$HOME/.docker/config.json"
        rm -f /tmp/docker-config.json
        ok "Docker config cleaned for container use"
    else
        ok "Docker registry credentials configured"
    fi
fi

# --- Step 7: Configure persistent shell history ---
info "Setting up persistent shell history..."
sudo chown vscode:vscode /commandhistory 2>/dev/null || true
touch /commandhistory/.bash_history

cat >> ~/.bashrc << 'HISTEOF'

# --- Persistent shell history (survives container rebuilds) ---
export HISTFILE=/commandhistory/.bash_history
export HISTSIZE=50000
export HISTFILESIZE=100000
export HISTCONTROL=ignoredups:erasedups
shopt -s histappend
PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND$'\n'}history -a; history -c; history -r"
HISTEOF
ok "Shell history configured (/commandhistory volume)"

# --- Step 8: Configure tmux ---
info "Configuring tmux..."
if [ ! -f "$HOME/.tmux.conf" ]; then
    cat > "$HOME/.tmux.conf" << 'TMUXEOF'
set -g history-limit 200000
set -g mouse on
set -g default-terminal "tmux-256color"
set -ga terminal-overrides ",xterm-256color:Tc"
TMUXEOF
    ok "tmux configured (200k scrollback, mouse enabled)"
else
    ok "tmux config already exists, skipping"
fi

# --- Done ---
echo ""
ok "Container setup complete!"
echo ""
echo "  Tools: opencode, openspec, docker, gh, rg, jq, gcc, tmux, fzf, fd"
echo "  Config: ~/.config/opencode/ (team settings from /opt/opencode-setup)"
echo "  Auth:   ~/.local/share/opencode/auth.json (copied from host)"
echo ""
