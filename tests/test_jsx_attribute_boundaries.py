"""Valid attribute identifiers and rejected candidates must preserve live CSS."""

import time

import pytest
from click.testing import CliRunner

from deadcode.cli import cli
from deadcode.scanner import DeadCodeScanner, _jsx_class_attributes


@pytest.mark.parametrize("extension", ["tsx", "jsx"])
@pytest.mark.parametrize("attributes", [r'extends="C:\"', r'extends data-path="C:\"'])
def test_extends_attributes_preserve_module_rules(tmp_path, monkeypatch, extension, attributes):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    (tmp_path / "Card.module.css").write_text(".live {}\n.unused {}\n", encoding="utf-8")
    (tmp_path / f"consumer.{extension}").write_text(
        "import styles from './Card.module.css';\n"
        f"const view = <Component {attributes} className={{styles.live}} />;\n",
        encoding="utf-8",
    )
    assert {finding.name for finding in DeadCodeScanner(tmp_path).scan().orphaned_css} == {"unused"}
    result = CliRunner().invoke(cli, ["-p", str(tmp_path), "remove", "-c", "orphaned_css"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Card.module.css").read_text() == ".live {}\n"


@pytest.mark.parametrize("attribute", ["é", "e\u0301", "λ", "字段", "$value"])
def test_unicode_attribute_names_do_not_expose_quoted_tag_delimiters(tmp_path, attribute):
    (tmp_path / "styles.css").write_text(".live {}\n.unused {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(
        f'const view = <div {attribute}=">" className="live" />;\n', encoding="utf-8"
    )
    assert {finding.name for finding in DeadCodeScanner(tmp_path).scan().orphaned_css} == {"unused"}


def test_rejected_tag_candidates_have_linear_character_work():
    class CountedText(str):
        reads = 0

        def __getitem__(self, key):
            self.reads += 1
            return super().__getitem__(key)

    content = CountedText(('const lesser=a<b;\nconst text="<name attr";\n') * 500)
    assert list(_jsx_class_attributes(content)) == []
    assert content.reads < 30 * len(content)


@pytest.mark.parametrize(
    "attributes", ["enabled " * 1500, 'title="' + "x" * 9000 + '" ', "value={" + " " * 9000 + "null} "]
)
def test_oversized_header_keeps_global_class_use_uncertain(tmp_path, attributes):
    (tmp_path / "styles.css").write_text(".live {}\n.unused {}\n", encoding="utf-8")
    (tmp_path / "consumer.tsx").write_text(
        "const view = <div " + attributes + 'className="live" />;\n', encoding="utf-8"
    )
    findings = DeadCodeScanner(tmp_path).scan().orphaned_css
    assert findings and all(not finding.removable for finding in findings)
