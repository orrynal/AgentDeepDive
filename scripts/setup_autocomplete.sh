#!/bin/bash
# ⚠️ WARNING: scripts/setup_autocomplete.sh has been deprecated and is no longer maintained.
# Please configure Click autocompletion directly in your shell's profile.

echo "⚠️  WARNING: scripts/setup_autocomplete.sh has been deprecated."
echo "Please configure Click autocompletion directly in your shell profile."
echo ""
echo "For Bash:"
echo '  echo '\''eval "$(_AGENTDEEP_COMPLETE=bash_source agentdeep)"'\'' >> ~/.bashrc'
echo ""
echo "For Zsh:"
echo '  echo '\''eval "$(_AGENTDEEP_COMPLETE=zsh_source agentdeep)"'\'' >> ~/.zshrc'
echo ""
echo "For Fish:"
echo '  echo '\''_AGENTDEEP_COMPLETE=fish_source agentdeep | source'\'' >> ~/.config/fish/config.fish'
echo ""
exit 0
