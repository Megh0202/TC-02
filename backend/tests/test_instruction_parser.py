from app.runtime.instruction_parser import parse_structured_task_steps


def test_structured_prompt_inserts_login_before_create_form_verify() -> None:
    task = """
1) Navigate to https://test.vitaone.io
2) Type "balasubramanian.r@teknotrait.com" into email field
3) Type "PasswordVitaone1@" into password field
4) Verify admin login success and verify "Create Form" button is visible
5) Click "Create Form"
6) In Form Name, type QA_Form_{{NOW_YYYYMMDD_HHMMSS}}
7) Drag "Short answer" field into the form canvas
8) In label input, type "First Name"
9) Check the "Required" checkbox
10) Click "Save"
"""
    steps = parse_structured_task_steps(task, max_steps=20)
    types = [step["type"] for step in steps]

    assert types[:5] == ["navigate", "type", "type", "click", "wait"]
    assert steps[3]["selector"] == "{{selector.login_button}}"
    assert any(step.get("selector") == "{{selector.create_form}}" for step in steps if step["type"] in {"click", "verify_text"})
    assert any(step.get("selector") == "{{selector.save_form}}" for step in steps if step["type"] == "click")

