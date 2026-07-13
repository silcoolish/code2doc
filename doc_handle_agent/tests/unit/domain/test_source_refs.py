from app.domain.source_refs import is_function_source_ref


def test_function_source_ref_accepts_current_method_id_format():
    assert is_function_source_ref({"sourceId": "method_repo_src/system.c_System_Init"})


def test_function_source_ref_accepts_explicit_function_type():
    assert is_function_source_ref({"symbolType": "Function"})


def test_function_source_ref_rejects_non_function_reference():
    assert not is_function_source_ref({"sourceId": "class_repo_src/system.c_System"})
