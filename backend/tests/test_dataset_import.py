import pytest

from scripts.import_zenodo_example import CASE, reference_labels


def test_reference_extraction_excludes_ai_outputs():
    row = {"Step": 4, "Benchmark": "Error", "Class": "Error", "Skill": "SpatialResolution", "AI Response": "No Error"}
    result = reference_labels([{"eval_set": CASE, "df_errors": [row], "lab_notes": "Generated text"}])
    assert result['labels'] == [{k: row[k] for k in ('Step', 'Benchmark', 'Class', 'Skill')}]
    assert 'Generated text' not in str(result)
    assert 'AI Response' not in str(result)


def test_inconsistent_reference_runs_are_rejected():
    a = {"Step": 1, "Benchmark": "Error", "Class": "Error", "Skill": "Fast"}
    b = {**a, "Benchmark": "No Error"}
    with pytest.raises(ValueError, match="differ"):
        reference_labels([{"eval_set": CASE, "df_errors": [a]}, {"eval_set": CASE, "df_errors": [b]}])
