# tests/test_continuation_classifier.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from task_state import TaskState, TaskStateStore, PendingInfo


def test_get_returns_none_for_unknown_context():
    store = TaskStateStore()
    assert store.get("unknown") is None


def test_get_or_create_returns_default_state():
    store = TaskStateStore()
    state = store.get_or_create("tab1")
    assert state.active_skills == []
    assert state.pending is None
    assert state.confidence == 0.0
    assert state.turns_since_last_update == 0


def test_update_sets_fields_and_resets_counter():
    store = TaskStateStore()
    store.get_or_create("tab1")
    store.update("tab1", active_skills=["email"], confidence=0.85)
    state = store.get("tab1")
    assert state.active_skills == ["email"]
    assert state.confidence == 0.85
    assert state.turns_since_last_update == 0


def test_decay_increments_counter():
    store = TaskStateStore()
    store.get_or_create("tab1")
    store.decay("tab1")
    assert store.get("tab1").turns_since_last_update == 1


def test_decay_clears_pending_after_3_turns():
    store = TaskStateStore()
    store.get_or_create("tab1")
    pending = PendingInfo(type="confirmation", expected_format=None,
                          purpose="test", asked_on_turn=1)
    store.update("tab1", pending=pending, confidence=0.85)
    for _ in range(3):
        store.decay("tab1")
    state = store.get("tab1")
    assert state.pending is None
    assert state.confidence < 0.85


def test_clear_removes_context():
    store = TaskStateStore()
    store.get_or_create("tab1")
    store.clear("tab1")
    assert store.get("tab1") is None


def test_update_raises_on_unknown_field():
    import pytest
    store = TaskStateStore()
    store.get_or_create("tab1")
    with pytest.raises(ValueError, match="no field"):
        store.update("tab1", acitve_skills=["email"])


from continuation_classifier import detect_pending


def test_detect_pending_email_address_question():
    text = "I can compose the email right away. What's your email address?"
    result = detect_pending(text, turn_index=3)
    assert result is not None
    assert result.type == "data_input"
    assert result.expected_format == "email"


def test_detect_pending_confirmation_shall_i():
    text = "I have all the data ready. Shall I send the email now?"
    result = detect_pending(text, turn_index=2)
    assert result is not None
    assert result.type == "confirmation"


def test_detect_pending_would_you_like():
    text = "The rows have been added. Would you like me to save the file?"
    result = detect_pending(text, turn_index=5)
    assert result is not None
    assert result.type == "confirmation"


def test_detect_pending_name_question():
    text = "I need a bit more info. What is their full name?"
    result = detect_pending(text, turn_index=1)
    assert result is not None
    assert result.type == "data_input"
    assert result.expected_format == "name"


def test_detect_pending_date_question():
    text = "Got it. What date should the meeting start?"
    result = detect_pending(text, turn_index=4)
    assert result is not None
    assert result.type == "data_input"
    assert result.expected_format == "date"


def test_detect_pending_no_question():
    text = "I have updated the spreadsheet with all three entries."
    result = detect_pending(text, turn_index=6)
    assert result is None


def test_detect_pending_generic_please_provide():
    text = "Please provide the details you'd like included."
    result = detect_pending(text, turn_index=2)
    assert result is not None
    assert result.type == "data_input"
    assert result.expected_format == "any"


from continuation_classifier import classify, ClassifierResult


def _state_with_pending_confirmation(skills=None):
    s = TaskState(active_skills=skills or ["email"], confidence=0.85)
    s.pending = PendingInfo(type="confirmation", expected_format=None,
                            purpose="action_confirm", asked_on_turn=2)
    return s


def _state_with_pending_email(skills=None):
    s = TaskState(active_skills=skills or ["email"], confidence=0.85)
    s.pending = PendingInfo(type="data_input", expected_format="email",
                            purpose="email_address", asked_on_turn=2)
    return s


def _state_confident(skills=None):
    return TaskState(active_skills=skills or ["excel"], confidence=0.80)


# No prior state
def test_classify_new_when_no_state():
    result = classify("yes", state=None)
    assert result.mode == "new"


def test_classify_new_when_no_active_skills():
    result = classify("yes", state=TaskState())
    assert result.mode == "new"


# Confirmation mode
def test_classify_confirmation_on_yes():
    result = classify("yes", state=_state_with_pending_confirmation())
    assert result.mode == "confirmation"


def test_classify_confirmation_on_looks_good():
    result = classify("Looks good. Add it.", state=_state_with_pending_confirmation())
    assert result.mode == "confirmation"


def test_classify_confirmation_on_go_ahead():
    result = classify("go ahead", state=_state_with_pending_confirmation())
    assert result.mode == "confirmation"


def test_classify_confirmation_resolves_pending():
    state = _state_with_pending_confirmation()
    result = classify("yes", state=state)
    assert result.resolved_pending is not None
    assert result.resolved_pending.type == "confirmation"


# Data input mode
def test_classify_data_input_on_email():
    result = classify("mayuresh.c.k@gmail.com", state=_state_with_pending_email())
    assert result.mode == "data_input"


def test_classify_data_input_resolves_pending():
    state = _state_with_pending_email()
    result = classify("user@example.com", state=state)
    assert result.resolved_pending is not None
    assert result.resolved_pending.expected_format == "email"


# Inherit mode
def test_classify_inherit_on_add_it():
    result = classify("add it", state=_state_confident())
    assert result.mode == "inherit"


def test_classify_inherit_on_try_again():
    result = classify("try again", state=_state_confident())
    assert result.mode == "inherit"


def test_classify_inherit_low_entropy_pronoun():
    result = classify("update that", state=_state_confident())
    assert result.mode == "inherit"


# New mode — falls through
def test_classify_new_on_unrelated_message():
    result = classify("Can you search Jira for open tickets?", state=_state_confident())
    assert result.mode == "new"


def test_classify_new_when_confidence_too_low():
    state = TaskState(active_skills=["excel"], confidence=0.5)
    result = classify("add it", state=state)
    assert result.mode == "new"
