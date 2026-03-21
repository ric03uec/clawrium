"""Random name generation and hostname utilities."""
import random
import re

# Adjectives for name generation
ADJECTIVES = [
    "clever", "swift", "bright", "calm", "bold", "eager", "gentle", "kind",
    "quick", "sharp", "steady", "vivid", "warm", "wise", "agile", "brave",
    "clear", "deft", "fair", "keen", "lively", "neat", "prime", "rapid",
    "smart", "sound", "strong", "true", "able"
]

# Scientist last names for name generation
SCIENTISTS = [
    "einstein", "curie", "newton", "darwin", "tesla", "lovelace", "turing",
    "hawking", "feynman", "bohr", "planck", "fermi", "dirac", "heisenberg",
    "schrodinger", "maxwell", "faraday", "galileo", "kepler", "copernicus",
    "euclid", "archimedes", "pythagoras", "aristotle", "hypatia", "noether",
    "meitner", "franklin", "hopper", "goodall", "carson", "sagan", "tyson",
    "lamarr", "wu", "rubin", "leavitt", "cannon", "payne", "burnell", "ride",
    "jemison", "elion", "yalow", "mcclintock", "blackwell", "hodgkin",
    "joliot", "germain", "chatelet"
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
    pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'

    if not re.match(pattern, value):
        return False

    # Additional validation: each octet should be 0-255
    try:
        octets = [int(x) for x in value.split('.')]
        return all(0 <= octet <= 255 for octet in octets)
    except ValueError:
        return False
