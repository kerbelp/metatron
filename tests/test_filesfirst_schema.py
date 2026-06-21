from metatron.filesfirst import schema


def test_status_lifecycle_values():
    assert schema.STATUSES == ("candidate", "canonical", "superseded", "deprecated")


def test_field_ownership_is_disjoint():
    assert schema.HUMAN_FIELDS.isdisjoint(schema.MACHINE_FIELDS)


def test_required_fields_are_all_human_owned():
    assert set(schema.REQUIRED_FIELDS) <= schema.HUMAN_FIELDS
