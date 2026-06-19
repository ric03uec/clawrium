# GENERATED FROM scenes.yaml — DO NOT EDIT BY HAND.
#   Edit scenes.yaml then re-run docs/demos/lib/compile.py.

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

# Install a clawctl() shell-function override that intercepts each scene's
# real command and prints its cached output. Call this AFTER any live setup
# clawctl invocations (e.g. `agent delete`) so those still hit the real CLI.
_replay_install() {
  clawctl() {
    local args="$*"
    case "$args" in
    "--version") cat docs/demos/20260618-quickstart-onboarding/outputs/01-version.txt ;;
    "service init") cat docs/demos/20260618-quickstart-onboarding/outputs/02-service-init.txt ;;
    "host create wolf.tailf7742d.ts.net --user xclm --alias wolf-i") cat docs/demos/20260618-quickstart-onboarding/outputs/03-host-create.txt ;;
    "agent create quickstart-demo --type hermes --host wolf-i") head -n 15 docs/demos/20260618-quickstart-onboarding/outputs/04-agent-create.txt; echo '   …'; tail -n 10 docs/demos/20260618-quickstart-onboarding/outputs/04-agent-create.txt ;;
    "agent configure quickstart-demo --stage providers --provider clawrium-gtm-litellm") cat docs/demos/20260618-quickstart-onboarding/outputs/05-agent-configure.txt ;;
    "agent get") cat docs/demos/20260618-quickstart-onboarding/outputs/06-agent-get.txt ;;
    "agent chat quickstart-demo") cat docs/demos/20260618-quickstart-onboarding/outputs/07-agent-chat.txt ;;
      *) echo "[replay] no match for: clawctl $args" >&2; return 1 ;;
    esac
  }
}
