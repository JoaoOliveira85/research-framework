from research_framework.pipeline.scaffold_models import OpKind


def test_op_kind_has_exactly_three_members():
    assert {k.value for k in OpKind} == {"create", "overwrite", "leave_alone"}
