# Per-demo helper script for the 20260618-quickstart-onboarding demo.
# Sets the per-demo variables, then sources the shared card/headline/progress
# functions from docs/demos/lib/cards.sh.

_SCENES=(
  "clawctl version"
  "Initialize clawrium service"
  "Register a host"
  "Install the hermes agent"
  "Configure the agent"
  "Check fleet status"
  "Chat with the agent"
)

_TITLE="Clawrium Quickstart"
_SUBTITLE="onboarding walkthrough — clawctl 26.6.4"
_OUTRO_LINE_1="Get started: ric03uec.github.io/clawrium"
_OUTRO_LINE_2="github.com/ric03uec/clawrium"

source "$(git rev-parse --show-toplevel)/docs/demos/lib/cards.sh"
