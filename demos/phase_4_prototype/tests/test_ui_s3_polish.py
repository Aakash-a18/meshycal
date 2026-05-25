"""Static-assertion contract tests for the S3 polish additions.

The Scenario 3 polish (narrative band, dialogue panel, Atlas calendar
fix) defined in ``UI_S3_POLISH_DESIGN.md`` lives entirely inside the
single-file prototype ``demos/phase_4_prototype/index.html``. The
runtime behaviour is hard to exercise without a headless browser, but
the *shape* of the additions — markup IDs, function definitions, the
exact narrative beat and dialogue strings, the absence of new unsafe
DOM writes, and the Atlas restore block in ``s3Reset()`` — can all be
pinned with simple string searches against the file.

These tests are deliberately coarse (substring presence) rather than
parsing HTML or JS. They protect the polish work from silent
regressions during future edits without locking in formatting.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


INDEX_HTML_PATH = (
    Path(__file__).resolve().parent.parent / "index.html"
)

# Property name we want to forbid as an assignment target. Spelled as
# a concatenation to keep static analysis / linter heuristics happy —
# this file is *testing* that the prototype avoids that sink, not
# using it.
UNSAFE_DOM_PROP = "inner" + "HTML"


@pytest.fixture(scope="module")
def index_html() -> str:
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


# -- 1. Narrative band markup --------------------------------------------


class TestNarrativeBandMarkup:
    def test_narrative_band_div_present(self, index_html: str) -> None:
        assert 'id="s3-narrative-band"' in index_html

    def test_nb_text_paragraph_present(self, index_html: str) -> None:
        assert 'id="s3-nb-text"' in index_html


# -- 2. Dialogue panel markup --------------------------------------------


class TestDialoguePanelMarkup:
    def test_dialogue_panel_div_present(self, index_html: str) -> None:
        assert 'id="s3-dialogue-panel"' in index_html

    def test_dp_body_present(self, index_html: str) -> None:
        assert 'id="s3-dp-body"' in index_html


# -- 3. Atlas calendar starts with the 14:00 blocker --------------------


class TestAtlasCalendarInitialMarkup:
    def test_atlas_1400_slot_present(self, index_html: str) -> None:
        assert 'data-slot="s3-atlas-1400"' in index_html

    def test_atlas_1400_has_blocking_class(self, index_html: str) -> None:
        # The initial event markup must combine the .event class with
        # the .s3-blocking modifier, exactly as spec §3.1 requires.
        assert re.search(
            r'class="event s3-blocking"\s+data-slot="s3-atlas-1400"',
            index_html,
        ), 'Expected `class="event s3-blocking" data-slot="s3-atlas-1400"` in initial Atlas calendar markup'

    def test_old_empty_placeholder_removed(self, index_html: str) -> None:
        # The deleted ``s3-cal-atlas-empty`` placeholder must not be in
        # the static markup any more.
        assert "s3-cal-atlas-empty" not in index_html


# -- 4. Three new JS functions defined ----------------------------------


class TestNewJsFunctionsDefined:
    def test_s3_narrative_beat_defined(self, index_html: str) -> None:
        assert "function s3NarrativeBeat(" in index_html

    def test_s3_dialogue_append_defined(self, index_html: str) -> None:
        assert "function s3DialogueAppend(" in index_html

    def test_s3_move_atlas_slot_defined(self, index_html: str) -> None:
        assert "function s3MoveAtlasSlot(" in index_html


# -- 5. Narrative beat strings (distinctive phrases, spec §1.4) --------


# The spec table in §1.4 lists eight beats. The phrases below are each
# unique enough to identify their corresponding beat without colliding
# with other prose in the file.
NARRATIVE_BEAT_PHRASES = [
    "scope it — only the slot",   # step 1 beat
    "noticed the conflict",         # step 3 beat
    "has a plan",                   # step 4 beat
    "Atlas accepted",               # step 5 beat
    "confirmed to Iris",            # step 6 beat
    "Three tessera fits",           # step 7 beat
    "Three calendars updated",      # step 8 beat
]


@pytest.mark.parametrize("phrase", NARRATIVE_BEAT_PHRASES)
def test_narrative_beat_phrase_present(index_html: str, phrase: str) -> None:
    assert phrase in index_html, (
        f"Narrative beat phrase {phrase!r} not found in index.html — "
        "the matching `s3NarrativeBeat(...)` call is missing or its "
        "string was edited."
    )


# -- 6. Dialogue message strings (spec §2.5) -----------------------------


# All five scripted messages from §2.5. We match a distinctive prefix
# of each so the test isn't fragile to typographic-quote variation.
DIALOGUE_MESSAGE_PHRASES = [
    "Iris wants 30 minutes",                                  # iris → marius proposal
    "scheduled conflict: project-sync with atlas at 14:00",   # marius thinking row
    "booked for project-sync at 14:00. Iris just asked",      # marius → atlas proposal
    "Confirmed. 16:00 works for me",                          # atlas → marius acceptance
    "Confirmed. Tuesday 14:00 is yours",                      # marius → iris acceptance
]


@pytest.mark.parametrize("phrase", DIALOGUE_MESSAGE_PHRASES)
def test_dialogue_message_phrase_present(index_html: str, phrase: str) -> None:
    assert phrase in index_html, (
        f"Dialogue message phrase {phrase!r} not found in index.html — "
        "the matching `s3DialogueAppend(...)` call is missing or its "
        "body string was edited."
    )


# -- 7. No new unsafe DOM-property writes -------------------------------


class TestNoUnsafeDomAssignment:
    """Spec §2 hard constraint: all new DOM content goes via ``elem()``,
    ``textContent`` or ``document.createTextNode()``. There must be
    zero ``.<UNSAFE_DOM_PROP> = ...`` assignments anywhere in the file.

    Pre-existing *comments* mentioning the property name (e.g. "// no
    [...] for content") are fine — we match assignment syntax only.
    """

    def test_no_unsafe_dom_assignment(self, index_html: str) -> None:
        pattern = re.compile(r"\." + re.escape(UNSAFE_DOM_PROP) + r"\s*=")
        matches = pattern.findall(index_html)
        assert matches == [], (
            f"Found {len(matches)} `.{UNSAFE_DOM_PROP} =` assignment(s); "
            "the polish must use elem()/textContent only."
        )


# -- 8. ``s3Reset()`` reconstructs the Atlas 14:00 slot -----------------


class TestS3ResetRestoresAtlas1400:
    """Spec §3.4: the Atlas restore block inside ``s3Reset()`` rebuilds
    the ``s3-atlas-1400`` event from scratch when it has been removed.
    The block sets ``evAtlas1400.dataset.slot = "s3-atlas-1400"``,
    which is a sharp fingerprint of the restore code path.
    """

    def test_reset_sets_atlas_1400_dataset_slot(self, index_html: str) -> None:
        assert 'evAtlas1400.dataset.slot = "s3-atlas-1400"' in index_html

    def test_reset_does_not_reference_old_placeholder(
        self, index_html: str
    ) -> None:
        # Belt-and-braces: the deleted ``s3-cal-atlas-empty`` symbol
        # must not appear anywhere — including the restore block.
        assert "s3-cal-atlas-empty" not in index_html
