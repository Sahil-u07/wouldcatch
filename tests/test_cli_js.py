import json
import shutil
import subprocess

import pytest

import wouldcatch.cli as cli
from wouldcatch.cli import js_test_cmd, main
from wouldcatch.diff import is_test_file

JS_OLD = "function discount(price, isMember) {\n  return price;\n}\nmodule.exports = { discount };\n"
JS_NEW = (
    "function discount(price, isMember) {\n"
    "  if (isMember && price >= 100) {\n"
    "    return price - 10;\n"
    "  }\n"
    "  return price;\n"
    "}\n"
    "module.exports = { discount };\n"
)
HEAD = "const test = require('node:test');\nconst assert = require('node:assert');\nconst { discount } = require('./shop.js');\n"
WEAK = HEAD + "test('member', () => assert.strictEqual(discount(200, true), 190));\n"
STRONG = WEAK + (
    "test('edges', () => {\n"
    "  assert.strictEqual(discount(100, true), 90);\n"
    "  assert.strictEqual(discount(99, true), 99);\n"
    "  assert.strictEqual(discount(200, false), 200);\n"
    "});\n"
)
PACKAGE = '{"scripts": {"test": "node --test"}}\n'

needs_js = pytest.mark.skipif(
    not cli.mutate_js.available() or shutil.which("node") is None or shutil.which("npm") is None,
    reason="needs wouldcatch[js], node and npm",
)


def sh(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def js_repo(tmp_path, monkeypatch):
    sh("git", "init", "-q", cwd=tmp_path)
    sh("git", "config", "user.email", "t@t", cwd=tmp_path)
    sh("git", "config", "user.name", "t", cwd=tmp_path)
    (tmp_path / "shop.js").write_text(JS_OLD)
    (tmp_path / "shop.test.js").write_text(HEAD + "test('x', () => assert.strictEqual(discount(5, false), 5));\n")
    (tmp_path / "package.json").write_text(PACKAGE)
    sh("git", "add", ".", cwd=tmp_path)
    sh("git", "commit", "-qm", "init", cwd=tmp_path)
    (tmp_path / "shop.js").write_text(JS_NEW)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *args):
    code = main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)


@needs_js
def test_weak_js_tests_miss_bugs_using_the_package_json_script(js_repo, capsys):
    (js_repo / "shop.test.js").write_text(WEAK)
    code, out = run(capsys)  # no --cmd: must find `npm test` by itself
    assert code == 1 and out["missed"] > 0
    assert {m["file"] for m in out["mutants"]} == {"shop.js"}  # the test file is never mutated
    assert {m["line"] for m in out["mutants"]} <= {2, 3}
    assert (js_repo / "shop.js").read_text() == JS_NEW


@needs_js
def test_strong_js_tests_catch_everything(js_repo, capsys):
    (js_repo / "shop.test.js").write_text(STRONG)
    code, out = run(capsys)
    assert out["missed"] == 0, [m for m in out["mutants"] if m["status"] == "missed"]
    assert code == 0 and out["caught"] == len(out["mutants"]) > 0


def test_js_files_are_skipped_with_a_hint_when_the_parser_is_missing(js_repo, capsys, monkeypatch):
    monkeypatch.setattr(cli.mutate_js, "available", lambda: False)
    assert main([]) == 0
    out = capsys.readouterr()
    assert "wouldcatch[js]" in out.err and "no mutable lines" in out.out


@needs_js
def test_no_package_json_asks_for_cmd(js_repo, capsys):
    (js_repo / "package.json").unlink()
    assert main([]) == 2
    assert "--cmd" in capsys.readouterr().err


def test_js_test_cmd_follows_the_lockfile(tmp_path):
    assert js_test_cmd(tmp_path) is None
    (tmp_path / "package.json").write_text("{}")
    assert js_test_cmd(tmp_path) == "npm test"
    (tmp_path / "yarn.lock").write_text("")
    assert js_test_cmd(tmp_path) == "yarn test"
    (tmp_path / "pnpm-lock.yaml").write_text("")
    assert js_test_cmd(tmp_path) == "pnpm test"


@pytest.mark.parametrize("path", [
    "src/a.test.ts", "src/a.spec.jsx", "src/__tests__/a.js", "vite.config.ts", "types/a.d.ts",
    "node_modules/x/index.js", "tests/helper.js",
])
def test_js_test_and_config_files_are_never_mutated(path):
    assert is_test_file(path)


@pytest.mark.parametrize("path", ["src/a.ts", "lib/spec.js", "src/latest.js", "app/config.ts"])
def test_js_source_files_are_mutated(path):
    assert not is_test_file(path)
