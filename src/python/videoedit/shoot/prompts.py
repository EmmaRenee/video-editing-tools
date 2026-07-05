"""
Prompt bank for CLIP zero-shot frame tagging.

Labels are grouped by what they signal downstream:
- aroll:      speech-driven, people-facing content
- action:     high-energy B-roll (racing, sport, crowds)
- atmosphere: establishing/scenic B-roll
- junk:       frames that should drag a clip's score down

Shoot-specific prompts from `shoots.config_json["extra_prompts"]`
(collected when Claude interviews the editor) are merged in at
runtime, so "look for the red #42 car" becomes a real signal.
"""
from typing import Dict, List, Tuple

PROMPT_BANK: Dict[str, List[str]] = {
    "aroll": [
        "a person talking to the camera",
        "an interview with a microphone",
        "a person being interviewed",
        "people having a conversation",
    ],
    "action": [
        "a race car on a track",
        "cars racing wheel to wheel",
        "a motorsport overtake",
        "a crowd cheering at an event",
        "a trophy or podium celebration",
        "a race start with many cars",
        "mechanics working in a pit lane",
        "fast motion sports action",
    ],
    "atmosphere": [
        "a scenic landscape or venue exterior",
        "an empty race track",
        "event signage or branding",
        "a sunset or golden hour scene",
        "spectators and atmosphere at an event",
        "close-up details of equipment",
    ],
    "junk": [
        "a blurry unusable frame",
        "a dark underexposed frame",
        "the ground, feet, or inside of a bag",
        "a lens cap or blocked lens",
        "a test frame or color bars",
    ],
}


def flatten_prompts(extra: List[str] = None) -> List[Tuple[str, str]]:
    """Return [(category, prompt), ...] including shoot-specific extras."""
    pairs = [(category, prompt)
             for category, prompts in PROMPT_BANK.items()
             for prompt in prompts]
    for prompt in (extra or []):
        pairs.append(("custom", prompt))
    return pairs
