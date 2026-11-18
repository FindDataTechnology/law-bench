"""内容指纹：交付文件字节的 sha256（change lex-matter-spine 5.3）。

为什么必须是**文件字节**而不是入参或正文的哈希：
- 案卷侧要证明"签署锚定的就是这份文件"（`lex_esign_tasks.anchor_sha256 ==
  artifact.sha256`），拿入参哈希等于证明"我用同样的参数又生成了一次"，
  中间任何渲染器/字体/模板差异都验不出来；
- 下游下载后要能自证：算一遍文件 sha256，与返回的 `sha256` 相等才认。

约定（跨 contract_generate / contract_generate_stored / contract_download）：
- `sha256`：主交付文件的字节哈希；多个格式并存时优先 pdf（签署锚定的通常形态）；
- `sha256_source`：`"pdf"` / `"docx"` / `"body_text"`，指明上面那个哈希取自什么；
  没有文件时回退到 `body_text` 的 UTF-8 字节，此时会显式写 `body_text`——
  静默回退会让调用方以为自己在验文件；
- `sha256_body`：总是给出正文（Markdown，含 `{{slot}}` 占位）的哈希，
  与 `contract_artifacts.body_hash`(md5) 互补，用于"同正文不同渲染"的对账。
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path | None) -> str | None:
    """文件字节的 sha256；路径为空或不可读返回 ``None``（不抛，由调用方决定降级）。"""
    if not path:
        return None
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def sha256_text(text: str | None) -> str | None:
    """正文 UTF-8 字节的 sha256；空正文返回 ``None``（空串的哈希没有证明力）。"""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_digest(
    body_text: str | None,
    *,
    pdf_path: str | Path | None = None,
    docx_path: str | Path | None = None,
) -> dict:
    """生成结果的三件指纹（见模块 docstring 的约定）。"""
    body = sha256_text(body_text)
    pdf = sha256_file(pdf_path)
    docx = sha256_file(docx_path)

    if pdf:
        primary, source = pdf, "pdf"
    elif docx:
        primary, source = docx, "docx"
    elif body:
        primary, source = body, "body_text"
    else:
        primary, source = None, None

    return {
        "sha256": primary,
        "sha256_source": source,
        "sha256_body": body,
        "sha256_by_format": {
            key: value
            for key, value in (("pdf", pdf), ("docx", docx))
            if value
        },
    }
