import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from preview_hub.cli import descriptor
from preview_hub.contracts import CompositionSpec, EnvName
from preview_hub.lifecycle import CreateEnvironment

ROOT = Path(__file__).resolve().parents[1]


def validate_schema(name, document):
    schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def test_sample_qa_report_schema():
    report = json.loads((ROOT / "e2e/fixtures/sample-qa-report.json").read_text())
    validate_schema("qa-report", report)


def test_ready_descriptor_schema(ctx):
    env = CreateEnvironment(ctx).execute(CompositionSpec(EnvName("schema-test"), {}))
    document = descriptor(env, ctx.catalog.public_url_template)
    validate_schema("environment-descriptor", document)
    assert document["state"] == "READY"
    assert document["readiness"]["allHealthy"] is True
    assert document["services"][0]["commit"] == ctx.git.sha
    assert document["testAccounts"] == []


@pytest.mark.parametrize("field", ["startedAt", "finishedAt"])
def test_qa_report_rejects_invalid_date_time(field):
    report = json.loads((ROOT / "e2e/fixtures/sample-qa-report.json").read_text())
    validate_schema("qa-report", report)
    report[field] = "not-a-date"

    with pytest.raises(ValidationError) as exc:
        validate_schema("qa-report", report)

    assert exc.value.validator == "format"
    assert list(exc.value.path) == [field]


@pytest.mark.parametrize(
    "path", [("createdAt",), ("expiresAt",), ("readiness", "checkedAt")]
)
def test_descriptor_rejects_invalid_date_time(ctx, path):
    env = CreateEnvironment(ctx).execute(CompositionSpec(EnvName("schema-test"), {}))
    document = descriptor(env, ctx.catalog.public_url_template)
    validate_schema("environment-descriptor", document)
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "not-a-date"

    with pytest.raises(ValidationError) as exc:
        validate_schema("environment-descriptor", document)

    assert exc.value.validator == "format"
    assert list(exc.value.path) == list(path)
