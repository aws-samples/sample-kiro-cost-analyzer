"""Regression tests for whole-execution RecordStatus manifest aggregation."""

from pathlib import Path

import yaml


class _CfnLoader(yaml.SafeLoader):
    """Safe loader that preserves CloudFormation intrinsic tags as values."""


def _construct_cfn(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    key = tag_suffix if tag_suffix in ("Ref", "Condition") else f"Fn::{tag_suffix}"
    return {key: value}


_CfnLoader.add_multi_constructor("!", _construct_cfn)


def _etl_states() -> tuple[dict, str]:
    template_path = Path(__file__).resolve().parent.parent / "template.yaml"
    with template_path.open(encoding="utf-8") as stream:
        loader = _CfnLoader(stream)
        try:
            template = loader.get_single_data()
        finally:
            loader.dispose()
    definition = template["Resources"]["EtlStateMachine"]["Properties"]["Definition"]
    return definition["States"], definition["StartAt"]


def test_state_machine_initializes_manifest_accumulator():
    states, start_at = _etl_states()

    assert start_at == "InitializeMapResultManifests"
    assert states["InitializeMapResultManifests"] == {
        "Type": "Pass",
        "Result": [],
        "ResultPath": "$.mapResultManifests",
        "Next": "ListNewFiles",
    }


def test_every_process_files_batch_is_accumulated_before_looping():
    states, _ = _etl_states()

    assert states["ProcessFiles"]["Next"] == "AccumulateMapResultManifest"
    assert states["AccumulateMapResultManifest"] == {
        "Type": "Pass",
        "Parameters": {
            "previous.$": "$.mapResultManifests",
            "bucket.$": "$.mapResults.ResultWriterDetails.Bucket",
            "key.$": "$.mapResults.ResultWriterDetails.Key",
        },
        "ResultPath": "$.mapResultManifests",
        "Next": "CheckHasMore",
    }


def test_record_status_receives_all_manifests_not_only_last_batch():
    states, _ = _etl_states()
    parameters = states["RecordStatus"]["Parameters"]

    assert parameters["mapResultManifests.$"] == "$.mapResultManifests"
    assert "mapResultsBucket.$" not in parameters
    assert "mapResultsKey.$" not in parameters
    assert states["RecordStatus"]["Next"] == "CheckEtlErrors"


def test_no_files_path_still_skips_record_status_lambda():
    states, _ = _etl_states()

    assert states["CheckNewFiles"]["Default"] == "RecordStatusNoFiles"
    assert states["RecordStatusNoFiles"]["Next"] == "ListUncategorizedPrompts"
