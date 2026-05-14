"""Shared helpers for GUI API route modules."""

import logging

from clawrium.core.hosts import HostsFileCorruptedError, get_agent_by_name

logger = logging.getLogger(__name__)


def resolve_agent(agent_key: str) -> tuple[dict, str, dict] | None:
    """Resolve an agent by instance key, agent_name, or legacy name.

    Returns (host_record, agent_type, agent_record), or None when the agent
    cannot be found or the hosts file is unreadable. Both callers (fleet
    lifecycle and agents memory/chat/logs) must use this so an alias works
    consistently across every action.

    OSError (e.g. permission denied on hosts.json) is logged but downgraded
    to "not found" — operators see the issue in the server log while clients
    receive a clean 404 instead of a stack trace with the file path.
    """
    try:
        return get_agent_by_name(agent_key)
    except HostsFileCorruptedError:
        logger.warning("hosts file is corrupted while resolving %r", agent_key)
        return None
    except ValueError:
        logger.info("ambiguous agent name %r", agent_key)
        return None
    except OSError as e:
        logger.error("failed to load hosts for agent %r: %s", agent_key, e)
        return None
