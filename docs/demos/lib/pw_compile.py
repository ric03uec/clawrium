# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6", "jinja2>=3"]
# ///
"""Compile a scenes.yaml spec into a runnable Playwright driver + cards + timeline.

Usage:
    uv run docs/demos/lib/pw_compile.py docs/demos/<YYYYMMDD-slug>/

Inputs:
    <demo_dir>/scenes.yaml
    docs/demos/lib/pw_driver.py.j2
    docs/demos/lib/cards/title.html.j2
    docs/demos/lib/cards/outro.html.j2

Outputs:
    <demo_dir>/driver.py
    <demo_dir>/cards/title.html      (if intro.title_card present in YAML)
    <demo_dir>/cards/outro.html      (if outro_card present in YAML)
    <demo_dir>/compiled.json         (narration timeline with absolute timestamps)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


LIB_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("demo_dir", type=Path, help="Path to docs/demos/<YYYYMMDD-slug>/")
    args = parser.parse_args()

    demo_dir: Path = args.demo_dir.resolve()
    scenes_path = demo_dir / "scenes.yaml"
    if not scenes_path.is_file():
        print(f"ERROR: missing {scenes_path}", file=sys.stderr)
        return 1

    spec = yaml.safe_load(scenes_path.read_text())
    validate_spec(spec)

    tape = spec["tape"]
    base_url = tape["base_url"].rstrip("/")

    # ---- compile per-scene action lines into ready-to-emit Python statements ----
    for scene in spec["scenes"]:
        lines = []
        for action in scene.get("actions") or []:
            lines.append(render_action(action, base_url))
        scene["action_lines"] = lines

    # ---- render driver.py ----
    env = Environment(
        loader=FileSystemLoader(str(LIB_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.filters["repr"] = repr
    driver_tpl = env.get_template("pw_driver.py.j2")
    driver_src = driver_tpl.render(
        title=spec["title"],
        demo_dir=str(demo_dir),
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        tape=tape,
        scenes=spec["scenes"],
        intro=spec.get("intro") or {},
        outro_card=spec.get("outro_card"),
        has_title_card=bool((spec.get("intro") or {}).get("title_card")),
        has_outro_card=bool(spec.get("outro_card")),
    )
    (demo_dir / "driver.py").write_text(driver_src)

    # ---- render cards ----
    cards_dir = demo_dir / "cards"
    cards_dir.mkdir(exist_ok=True)
    title_card_cfg = (spec.get("intro") or {}).get("title_card")
    if title_card_cfg:
        title_tpl = env.get_template("cards/title.html.j2")
        (cards_dir / "title.html").write_text(
            title_tpl.render(title=spec["title"], subtitle=spec.get("subtitle", ""))
        )
    outro_card_cfg = spec.get("outro_card")
    if outro_card_cfg:
        outro_tpl = env.get_template("cards/outro.html.j2")
        (cards_dir / "outro.html").write_text(
            outro_tpl.render(title=spec["title"], outro=spec.get("outro") or {})
        )

    # ---- build compiled.json timeline (absolute timestamps) ----
    compiled = build_timeline(spec)
    (demo_dir / "compiled.json").write_text(json.dumps(compiled, indent=2) + "\n")

    # ---- summary ----
    print(f"Compiled: {demo_dir.name}")
    print(f"  driver.py        ({len(driver_src.splitlines())} lines)")
    if title_card_cfg:
        print(f"  cards/title.html")
    if outro_card_cfg:
        print(f"  cards/outro.html")
    print(f"  compiled.json    ({len(compiled['narration'])} narration beats)")
    print(f"  total duration   {compiled['duration_seconds']:.1f}s")
    print()
    print("Timeline:")
    for beat in compiled["narration"]:
        print(f"  t={beat['absolute_seconds']:6.2f}s  [{beat['kind']:11s}]  {beat['text'][:70]}")
    return 0


def validate_spec(spec: dict) -> None:
    required_top = ("title", "tape", "scenes")
    for key in required_top:
        if key not in spec:
            raise SystemExit(f"scenes.yaml: missing top-level key '{key}'")
    if not isinstance(spec["scenes"], list) or not spec["scenes"]:
        raise SystemExit("scenes.yaml: 'scenes' must be a non-empty list")
    for key in ("base_url", "width", "height"):
        if key not in spec["tape"]:
            raise SystemExit(f"scenes.yaml: tape.{key} is required")
    spec["tape"].setdefault("color_scheme", "light")
    spec["tape"].setdefault("reduced_motion", "reduce")
    spec["tape"].setdefault("framerate", 30)
    spec["tape"].setdefault("device_scale", 1)
    for scene in spec["scenes"]:
        for key in ("n", "title", "screen_seconds"):
            if key not in scene:
                raise SystemExit(f"scenes.yaml: scene missing '{key}': {scene}")


def render_action(action: dict, base_url: str) -> str:
    """Convert one scenes.yaml action dict into a single Python statement."""
    if "goto" in action:
        target = action["goto"]
        if target.startswith("/"):
            target_expr = f'BASE_URL.rstrip("/") + {target!r}'
        else:
            target_expr = repr(target)
        return f'page.goto({target_expr}, wait_until="domcontentloaded")'
    if "click" in action:
        return f"page.locator({action['click']!r}).first.click()"
    if "fill" in action:
        sel, text = _selector_text(action["fill"], "fill")
        return f"page.locator({sel!r}).first.fill({text!r})"
    if "press" in action:
        cfg = action["press"]
        sel, key = cfg["selector"], cfg["key"]
        return f"page.locator({sel!r}).first.press({key!r})"
    if "hover" in action:
        return f"page.locator({action['hover']!r}).first.hover()"
    if "wait_for" in action:
        return f"page.locator({action['wait_for']!r}).first.wait_for(timeout=10_000)"
    if "wait_for_url" in action:
        return f"page.wait_for_url({action['wait_for_url']!r}, timeout=10_000)"
    if "wait" in action:
        return f"page.wait_for_timeout({int(float(action['wait']) * 1000)})"
    if "highlight" in action:
        sel = action["highlight"]
        # Inject an outline + box-shadow ring on the target element.
        return (
            f'page.locator({sel!r}).first.evaluate('
            '"el => el.style.cssText += '
            "'outline:3px solid #6ee7b7;outline-offset:4px;"
            'border-radius:6px;transition:none;\'")'
        )
    if "scroll" in action:
        cfg = action["scroll"]
        if "selector" in cfg:
            return f"page.locator({cfg['selector']!r}).first.scroll_into_view_if_needed()"
        if "y" in cfg:
            return f"page.mouse.wheel(0, {int(cfg['y'])})"
        raise SystemExit(f"scroll action needs 'selector' or 'y': {cfg}")
    if "eval" in action:
        # Escape hatch: raw Python statement; trust the author.
        return action["eval"]
    raise SystemExit(f"unsupported action keys: {list(action.keys())}")


def _selector_text(cfg: Any, name: str) -> tuple[str, str]:
    if isinstance(cfg, dict):
        return cfg["selector"], cfg["text"]
    if isinstance(cfg, list) and len(cfg) == 2:
        return cfg[0], cfg[1]
    raise SystemExit(f"{name}: expected {{selector,text}} or [selector,text], got {cfg!r}")


def build_timeline(spec: dict) -> dict:
    """Walk the spec and emit narration beats with absolute timestamps.

    The output shape matches docs/demos/lib/narrate.py — each beat carries
    `scene_n`, `beat_n`, `absolute_seconds`, `text`. narrate.py keys its
    clip cache off (scene_n, beat_n), so the sentinel scene_n values
    (0=title card, 99=outro card) are stable across recompiles.

    The timeline mirrors what the driver actually plays:
      [title_card] -> [initial 0.5s settle] -> [scenes...] -> [outro_card]
    """
    narration: list[dict] = []
    t = 0.0

    def add(scene_n: int, beat_n: int, ts: float, text: str, *, kind: str, title: str = "") -> None:
        text = (text or "").strip()
        if not text:
            return
        narration.append({
            "scene_n": int(scene_n),
            "beat_n": int(beat_n),
            "absolute_seconds": round(ts, 3),
            "kind": kind,
            "title": title,
            "text": text,
        })

    intro = spec.get("intro") or {}
    title_card = intro.get("title_card")
    if title_card:
        add(0, 0, t, title_card.get("narration", ""), kind="title_card", title=spec.get("title", ""))
        t += float(title_card["hold_seconds"])

    # Match the 0.5s settle in the driver.
    t += 0.5

    for scene in spec["scenes"]:
        scene_start = t
        for i, beat in enumerate(scene.get("narration") or []):
            offset = float(beat.get("offset_seconds", 0))
            add(scene["n"], i, scene_start + offset, beat.get("text", ""),
                kind="scene", title=scene["title"])
        t = scene_start + float(scene["screen_seconds"])

    outro_card = spec.get("outro_card")
    if outro_card:
        add(99, 0, t, outro_card.get("narration", ""), kind="outro_card",
            title=spec.get("title", ""))
        t += float(outro_card["hold_seconds"])

    return {"duration_seconds": round(t, 3), "narration": narration}


if __name__ == "__main__":
    raise SystemExit(main())
