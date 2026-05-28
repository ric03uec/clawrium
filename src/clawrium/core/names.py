"""Random name generation and hostname utilities."""

import random
import re

# Adjectives for name generation
ADJECTIVES = [
    "clever",
    "swift",
    "bright",
    "calm",
    "bold",
    "eager",
    "gentle",
    "kind",
    "quick",
    "sharp",
    "steady",
    "vivid",
    "warm",
    "wise",
    "agile",
    "brave",
    "clear",
    "deft",
    "fair",
    "keen",
    "lively",
    "neat",
    "prime",
    "rapid",
    "smart",
    "sound",
    "strong",
    "true",
    "able",
]

# Scientist last names for name generation
SCIENTISTS = [
    "einstein",
    "curie",
    "newton",
    "darwin",
    "tesla",
    "lovelace",
    "turing",
    "hawking",
    "feynman",
    "bohr",
    "planck",
    "fermi",
    "dirac",
    "heisenberg",
    "schrodinger",
    "maxwell",
    "faraday",
    "galileo",
    "kepler",
    "copernicus",
    "euclid",
    "archimedes",
    "pythagoras",
    "aristotle",
    "hypatia",
    "noether",
    "meitner",
    "franklin",
    "hopper",
    "goodall",
    "carson",
    "sagan",
    "tyson",
    "lamarr",
    "wu",
    "rubin",
    "leavitt",
    "cannon",
    "payne",
    "burnell",
    "ride",
    "jemison",
    "elion",
    "yalow",
    "mcclintock",
    "blackwell",
    "hodgkin",
    "joliot",
    "germain",
    "chatelet",
    "rutherford",
    "hertz",
    "ohm",
    "ampere",
    "volta",
    "kelvin",
    "joule",
    "watt",
    "becquerel",
    "roentgen",
    "mendeleev",
    "pauling",
    "lavoisier",
    "dalton",
    "avogadro",
    "boyle",
    "priestley",
    "gauss",
    "euler",
    "riemann",
    "hilbert",
    "ramanujan",
    "erdos",
    "cauchy",
    "leibniz",
    "descartes",
    "pasteur",
    "lister",
    "jenner",
    "fleming",
    "watson",
    "crick",
    "mendel",
    "linnaeus",
    "knuth",
    "dijkstra",
    "shannon",
    "von_neumann",
    "babbage",
    "kaku",
    "penrose",
    "witten",
    "hinton",
    "lecun",
    "bengio",
    "nobel",
    "pascal",
    "bernoulli",
    "lagrange",
    "laplace",
]


def generate_random_name() -> str:
    """Generate a random Docker-style name in 'adjective-scientist' format.

    Returns:
        A random name like 'clever-einstein' or 'swift-curie'
    """
    adjective = random.choice(ADJECTIVES)
    scientist = random.choice(SCIENTISTS)
    return f"{adjective}-{scientist}"


def is_ip_address(value: str) -> bool:
    """Check if a string is a valid IPv4 address.

    Args:
        value: String to check

    Returns:
        True if value is a valid IPv4 address, False otherwise
    """
    # Simple regex pattern for IPv4: 4 groups of 1-3 digits separated by dots
    pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"

    if not re.match(pattern, value):
        return False

    # Additional validation: each octet should be 0-255
    try:
        octets = [int(x) for x in value.split(".")]
        return all(0 <= octet <= 255 for octet in octets)
    except ValueError:
        return False


# Reserved Unix account names. The agent's name becomes a real account
# on the host (created via `useradd` on Linux and `dscl . -create
# /Users/<name>` on macOS, plus an `xclm` management-user collision on
# both). Allowing these names would silently overwrite or merge with a
# pre-existing system account — at best confusing, at worst a privilege
# escalation vector (mail/www-data/etc. typically have queue-write
# access or run privileged daemons).
#
# Coverage:
#   * Cross-Unix builtins (root, daemon, nobody, bin, sys, sync, games,
#     man, lp, mail, news, uucp, backup, list, irc, gnats, nogroup).
#   * Linux distro service accounts (www-data, syslog, postfix, sshd,
#     systemd-*, messagebus, _apt).
#   * macOS / Apple privileged groups (admin, wheel, staff, guest,
#     _appserver, _appstore).
#   * The management user clawrium itself creates (xclm).
RESERVED_UNIX_NAMES: frozenset[str] = frozenset(
    {
        # Universal POSIX accounts
        "root",
        "daemon",
        "nobody",
        "bin",
        "sys",
        "sync",
        "games",
        "man",
        "lp",
        "mail",
        "news",
        "uucp",
        "backup",
        "list",
        "irc",
        "gnats",
        "nogroup",
        # Linux service / distro accounts
        "www-data",
        "syslog",
        "postfix",
        "sshd",
        "messagebus",
        "_apt",
        # macOS / Apple privileged groups (acting as users)
        "admin",
        "wheel",
        "staff",
        "guest",
        # Clawrium management user
        "xclm",
    }
)


def validate_agent_name(name: str) -> tuple[bool, str]:
    """Validate an agent name for format, length, and reserved collisions.

    Names must be valid Unix usernames: start with a lowercase letter,
    followed by up to 31 lowercase letters, digits, hyphens, or
    underscores. Names listed in `RESERVED_UNIX_NAMES` are also
    rejected to prevent collisions with pre-existing system accounts.

    Args:
        name: Name to validate

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    if not name:
        return (False, "Name cannot be empty")

    if len(name) > 32:
        return (False, f"Name must be 32 characters or less (got {len(name)})")

    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", name):
        return (
            False,
            "Name must start with a lowercase letter and contain only lowercase letters, digits, hyphens, and underscores",
        )

    if name in RESERVED_UNIX_NAMES:
        return (
            False,
            f"Name '{name}' collides with a reserved Unix/Darwin account "
            f"({', '.join(sorted(RESERVED_UNIX_NAMES))}); choose a different name",
        )

    return (True, "")


def is_name_available_on_host(name: str, host: dict) -> bool:
    """Check if a name is available on a host (unique across all agents).

    Args:
        name: Name to check
        host: Host record with agents

    Returns:
        True if name is available, False if already in use
    """
    agents = host.get("agents", {})
    if name in agents:
        return False

    for agent_config in agents.values():
        if agent_config.get("agent_name") == name or agent_config.get("name") == name:
            return False
    return True
