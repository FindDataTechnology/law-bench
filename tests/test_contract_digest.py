"""内容指纹：交付文件字节的 sha256（change lex-matter-spine 5.3）。

三条必须钉住的语义：
1. **文件优先**：有文件就对文件字节取哈希，绝不用正文哈希顶替——否则"签署
   锚定的就是这份文件"这句承诺退化成"我用同样参数又生成了一次"；
2. **回退要显式**：没有文件时才回退到正文，并且 `sha256_source` 必须写成
   `body_text`，让调用方知道自己验的不是文件；
3. **遗留行如实报未知**：本变更之前写入的 artifact 行没有指纹列，读出来是
   空 map/None，不是空字符串，更不能被当成"已校验"。

这些都不需要数据库，所以放在根 `tests/`（默认闸）而不是 MCP 子包里。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PKG_SRC = REPO / "fd-coding-law-bench-mcp" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from src.contracts.artifacts import _digest_fields  # noqa: E402
from src.contracts.digest import content_digest, sha256_file, sha256_text  # noqa: E402

BODY = "## 当事人\n\n甲方：{{甲方名称}}\n"


def test_file_bytes_beat_body_text(tmp_path):
    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake bytes")
    digest = content_digest(BODY, pdf_path=pdf)

    assert digest["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert digest["sha256_source"] == "pdf"
    # 正文哈希同时给出，便于"同正文不同渲染"的对账
    assert digest["sha256_body"] == sha256_text(BODY)
    assert digest["sha256"] != digest["sha256_body"]
    assert digest["sha256_by_format"] == {"pdf": digest["sha256"]}


def test_pdf_preferred_over_docx(tmp_path):
    pdf = tmp_path / "c.pdf"
    docx = tmp_path / "c.docx"
    pdf.write_bytes(b"pdf")
    docx.write_bytes(b"docx")

    digest = content_digest(BODY, pdf_path=pdf, docx_path=docx)
    assert digest["sha256_source"] == "pdf"
    assert set(digest["sha256_by_format"]) == {"pdf", "docx"}


def test_missing_file_falls_back_to_body_with_explicit_source(tmp_path):
    digest = content_digest(BODY, pdf_path=tmp_path / "nope.pdf", docx_path=None)
    assert digest["sha256"] == sha256_text(BODY)
    assert digest["sha256_source"] == "body_text"
    assert digest["sha256_by_format"] == {}


def test_empty_body_and_no_file_is_unknown_not_empty_string():
    digest = content_digest("", pdf_path=None)
    assert digest["sha256"] is None
    assert digest["sha256_source"] is None
    assert digest["sha256_body"] is None


def test_sha256_file_does_not_raise_on_unreadable(tmp_path):
    assert sha256_file(tmp_path / "missing.pdf") is None
    assert sha256_file(None) is None
    # 目录不是文件：同样返回 None 而不是抛 IsADirectoryError
    assert sha256_file(tmp_path) is None


def test_legacy_row_reports_unknown_not_verified():
    """本变更前写入的行没有指纹列——必须报未知，不能报"校验通过"。"""
    fields = _digest_fields({}, {}, BODY)
    assert fields["sha256_by_format"] == {}
    assert fields["sha256_source"] == "body_text"  # 有正文就如实说是正文
    assert fields["sha256"] == sha256_text(BODY)


def test_stored_columns_win_over_fresh_render():
    row = {"pdf_sha256": "a" * 64, "docx_sha256": "b" * 64}
    fields = _digest_fields(row, {"pdf": "c" * 64}, BODY)
    assert fields["sha256"] == "a" * 64  # 行上的那份字节才是已上传的
    assert fields["sha256_source"] == "pdf"
    assert fields["sha256_by_format"] == {"pdf": "a" * 64, "docx": "b" * 64}


@pytest.mark.asyncio
async def test_contract_generate_attaches_file_digest(monkeypatch, tmp_path):
    """工具层：所有分支（skeleton/assembled/current_tags）都要带指纹。"""
    import src.contracts as contracts_mod

    pdf = tmp_path / "sale.pdf"
    pdf.write_bytes(b"%PDF-1.7 sale")
    result = {
        "docx_path": None,
        "pdf_path": str(pdf),
        "body_text": BODY,
        "slots": ["甲方名称"],
        "instructions": [],
        "laws": [],
    }
    monkeypatch.setattr(contracts_mod, "generate_contract", lambda *a, **k: dict(result))

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    res = await contract_generate("sale")
    assert res["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert res["sha256_source"] == "pdf"
    assert res["sha256_body"] == sha256_text(BODY)


@pytest.mark.asyncio
async def test_contract_generate_digest_is_last_not_first(monkeypatch, tmp_path):
    """`current_tags` 分支也不能漏指纹——派生字段必须加在所有分支之后。"""
    import src.clauses.tags as tags_mod
    import src.contracts as contracts_mod

    pdf = tmp_path / "sale.pdf"
    pdf.write_bytes(b"%PDF-1.7 sale")
    monkeypatch.setattr(
        contracts_mod,
        "generate_contract",
        lambda *a, **k: {
            "docx_path": None,
            "pdf_path": str(pdf),
            "body_text": BODY,
            "slots": [],
            "instructions": [],
            "laws": [],
        },
    )
    monkeypatch.setattr(tags_mod, "load_vocab_from_db", lambda db=None: tags_mod.TAG_VOCAB)
    monkeypatch.setattr(tags_mod, "tag_vocab_for_type", lambda key=None: {"stance": ["pro_a"]})

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    res = await contract_generate("sale", include_current_tags=True)
    assert res["current_tags"] == {"stance": ["pro_a"]}
    assert res["sha256_source"] == "pdf"
    assert res["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
