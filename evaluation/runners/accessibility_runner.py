"""
Static accessibility audit of the Next.js frontend (Phase 7 §161–§162).

A source-level audit only. It does not replace a manual screen-reader /
keyboard / contrast review on real devices, which is recorded as a
limitation (docs/phase7-limitations.md).
"""

import os
import re
from typing import Any, Dict, List

from evaluation import PROJECT_ROOT
from evaluation.metrics import summarize_checks
from evaluation.runners.common import check

SRC = os.path.join(PROJECT_ROOT, "frontend", "src")


def _read(rel: str) -> str:
    with open(os.path.join(SRC, rel), encoding="utf-8") as f:
        return f.read()


def _tags(text: str, tag: str) -> List[str]:
    """Opening JSX tags, ignoring '>' inside {...} expressions (e.g. arrow functions)."""
    out = []
    for m in re.finditer(rf"<{tag}\b", text):
        depth, i = 0, m.end()
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            i += 1
        out.append(text[m.start(): i + 1])
    return out


def run(_corpus_db=None) -> Dict[str, Any]:
    files = {}
    for dp, _, fs in os.walk(SRC):
        for f in fs:
            if f.endswith(".tsx"):
                rel = os.path.relpath(os.path.join(dp, f), SRC)
                files[rel] = _read(rel)
    all_src = "\n".join(files.values())
    checks = []

    unlabeled_buttons = []
    for rel, txt in files.items():
        for t in _tags(txt, "button"):
            if "aria-label" not in t:
                inner = txt[txt.find(t) + len(t): txt.find("</button>", txt.find(t))]
                has_dynamic_text = "{" in re.sub(r"<[A-Z]\w*[^>]*/>", "", inner)
                if not has_dynamic_text and not re.search(r"[A-Za-z]{3,}", re.sub(r"<[^>]+>", "", inner)):
                    unlabeled_buttons.append(rel)
    checks.append(check("BUTTONS_HAVE_ACCESSIBLE_NAME", not unlabeled_buttons, unlabeled=unlabeled_buttons))

    unlabeled_inputs = [rel for rel, txt in files.items() for t in _tags(txt, "input")
                        if "aria-label" not in t and "id=" not in t]
    checks.append(check("INPUTS_LABELLED", not unlabeled_inputs, unlabeled=unlabeled_inputs))

    imgs = [rel for rel, txt in files.items() for t in _tags(txt, "img") if "alt=" not in t]
    checks.append(check("IMAGES_HAVE_ALT", not imgs, missing=imgs))

    checks.append(check("HTML_LANG_SET", 'lang="' in files.get(os.path.join("app", "layout.tsx"), "")))
    checks.append(check("HTML_LANG_FOLLOWS_SELECTED_LANGUAGE",
                        "documentElement.lang" in all_src,
                        note="screen readers need <html lang> to match the chosen language"))

    missing_ids = []
    for ref in re.findall(r'aria-labelledby="([^"]+)"', all_src):
        if f'id="{ref}"' not in all_src and f"id={{'{ref}'}}" not in all_src:
            missing_ids.append(ref)
    checks.append(check("ARIA_LABELLEDBY_TARGETS_EXIST", not missing_ids, missing=missing_ids))

    checks.append(check("LIVE_REGION_FOR_ASYNC_STATUS", 'aria-live="polite"' in all_src))
    checks.append(check("ELIGIBILITY_STATUS_AS_TEXT",
                        "Eligibility: ${config.label}" in all_src or "config.label" in all_src))
    small = [rel for rel, txt in files.items() for t in _tags(txt, "button")
             if re.search(r"min-h-\[(\d+)px\]", t) and int(re.search(r"min-h-\[(\d+)px\]", t).group(1)) < 44]
    unsized = [rel for rel, txt in files.items() for t in _tags(txt, "button") if "min-h-[" not in t]
    checks.append(check("TOUCH_TARGETS_44PX", not small and not unsized, below_44px=small, unsized=unsized))
    checks.append(check("VISIBLE_FOCUS_STYLES", all_src.count("focus:") + all_src.count("focus-visible:") >= 3,
                        count=all_src.count("focus:") + all_src.count("focus-visible:")))
    checks.append(check("AUDIO_PLAYBACK_CAN_BE_STOPPED", ".pause()" in all_src,
                        note="TTS audio should be stoppable by the user"))
    checks.append(check("NO_UNSAFE_HTML", "dangerouslySetInnerHTML" not in all_src))
    checks.append(check("MIC_TRACKS_RELEASED", "getTracks().forEach" in all_src))
    return summarize_checks(checks)
