#!/usr/bin/env python3
"""Convert the Kiwoom REST API PDF into searchable Markdown documents.

The converter intentionally keeps request/response tables close to the PDF's
extracted text. Column wrapping in the source PDF makes aggressive table
normalisation lossy, while plain text remains exact and easy to search.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

from pypdf import PdfReader


SECTION_TITLES = {
    "API 정보",
    "기본정보",
    "개요",
    "Request",
    "Response",
    "Request Example",
    "Response Example",
}


@dataclass
class ApiDocument:
    api_id: str
    name: str
    menu: str
    method: str
    production_domain: str
    mock_domain: str
    url: str
    description: str
    start_page: int
    end_page: int
    file: str


def clean_page(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "키움 REST API":
            continue
        if re.fullmatch(r"\d+ / \d+", stripped):
            continue
        cleaned.append(line.rstrip())
    return "\n".join(cleaned).strip()


def value_after(lines: list[str], label: str) -> str:
    prefix = f"{label} "
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
        if stripped == label and index + 1 < len(lines):
            return lines[index + 1].strip()
    return ""


def section(text: str, start: str, ends: set[str]) -> str:
    lines = text.splitlines()
    try:
        begin = next(i for i, line in enumerate(lines) if line.strip() == start) + 1
    except StopIteration:
        return ""
    result: list[str] = []
    for line in lines[begin:]:
        if line.strip() in ends:
            break
        result.append(line)
    return "\n".join(result).strip()


def render_body(text: str) -> str:
    """Turn known PDF headings into Markdown and preserve table layout."""
    lines = text.splitlines()
    output: list[str] = []
    buffer: list[str] = []
    current_heading = ""

    def flush() -> None:
        nonlocal buffer
        content = "\n".join(buffer).strip()
        buffer = []
        if not content:
            return
        if current_heading in {"", "API 정보", "기본정보"}:
            return
        if current_heading in {"Request Example", "Response Example"}:
            output.extend(["```json", content, "```", ""])
        elif current_heading in {"Request", "Response"}:
            output.extend(["```text", content, "```", ""])
        else:
            output.extend([content, ""])

    for line in lines:
        stripped = line.strip()
        if stripped in SECTION_TITLES:
            flush()
            current_heading = stripped
            if stripped != "API 정보":
                output.extend([f"## {stripped}", ""])
            continue
        buffer.append(line)
    flush()
    return "\n".join(output).strip()


def discover_starts(reader: PdfReader) -> list[tuple[int, str]]:
    starts: list[tuple[int, str]] = []
    for page_index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        lines = text.splitlines()
        api_id = value_after(lines, "API ID")
        if api_id:
            starts.append((page_index, api_id))
    return starts


def write_api(output_dir: Path, api: ApiDocument, text: str) -> None:
    page_label = str(api.start_page)
    if api.end_page != api.start_page:
        page_label += f"-{api.end_page}"
    header = [
        f"# {api.api_id} - {api.name}",
        "",
        "> 이 문서는 키움 REST API PDF에서 자동 변환되었습니다. 필드 표는 원문 줄바꿈을 보존합니다.",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| API ID | `{api.api_id}` |",
        f"| 메뉴 | {api.menu} |",
        f"| Method | `{api.method}` |",
        f"| 운영 도메인 | `{api.production_domain}` |",
        f"| 모의투자 도메인 | `{api.mock_domain}` |",
        f"| URL | `{api.url}` |",
        f"| 원문 페이지 | {page_label} |",
        "",
    ]
    (output_dir / api.file).write_text("\n".join(header) + render_body(text) + "\n", encoding="utf-8")


def write_readme(output_dir: Path, source_name: str, apis: list[ApiDocument]) -> None:
    groups: dict[str, list[ApiDocument]] = {}
    for api in apis:
        major = api.menu.split(" > ", 1)[0] if api.menu else "기타"
        groups.setdefault(major, []).append(api)
    lines = [
        "# 키움 REST API 문서",
        "",
        f"`{source_name}`를 검색과 AI 참조에 적합하도록 변환한 문서입니다.",
        "",
        f"- API 수: {len(apis)}개",
        "- 각 API 문서는 요청/응답 필드와 JSON 예제를 포함합니다.",
        "- `manifest.json`은 API ID, URL, 메뉴, 페이지 범위를 기계적으로 검색할 때 사용합니다.",
        "- PDF 표의 셀 줄바꿈은 정보 손실을 막기 위해 `text` 블록으로 보존했습니다.",
        "- 실제 연동 전에는 최신 키움 공식 문서와 변경 여부를 확인하세요.",
        "",
        "## 공통 호출 규칙",
        "",
        "```http",
        "POST {운영 또는 모의투자 도메인}{URL}",
        "api-id: {API ID}",
        "authorization: Bearer {access_token}",
        "Content-Type: application/json;charset=UTF-8",
        "cont-yn: N",
        "next-key:",
        "```",
        "",
        "연속조회 응답의 `cont-yn`이 `Y`이면 응답의 `cont-yn`과 `next-key`를 다음 요청 헤더에 전달합니다.",
        "",
        "## API 색인",
        "",
    ]
    for group, items in groups.items():
        lines.extend([f"### {group}", "", "| API ID | API 명 | Method | URL | PDF 페이지 |", "|---|---|---|---|---:|"])
        for api in items:
            pages = str(api.start_page) if api.start_page == api.end_page else f"{api.start_page}-{api.end_page}"
            lines.append(f"| [`{api.api_id}`]({api.file}) | {api.name} | `{api.method}` | `{api.url}` | {pages} |")
        lines.append("")
    lines.extend(["## 공통 오류코드", "", "[공통 오류코드 보기](errors.md)", ""])
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def convert(pdf_path: Path, output_dir: Path) -> None:
    reader = PdfReader(str(pdf_path))
    starts = discover_starts(reader)
    if not starts:
        raise RuntimeError("API ID를 찾지 못했습니다.")
    if len({api_id for _, api_id in starts}) != len(starts):
        raise RuntimeError("중복 API ID가 발견되었습니다.")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    (output_dir / "apis").mkdir()

    apis: list[ApiDocument] = []
    for position, (start_index, api_id) in enumerate(starts):
        next_index = starts[position + 1][0] if position + 1 < len(starts) else len(reader.pages) - 1
        end_index = next_index - 1
        pages = [clean_page(reader.pages[index].extract_text() or "") for index in range(start_index, end_index + 1)]
        text = "\n".join(pages)
        lines = text.splitlines()
        menu = value_after(lines, "메뉴 위치")
        name = value_after(lines, "API 명")
        api = ApiDocument(
            api_id=api_id,
            name=name,
            menu=menu,
            method=value_after(lines, "Method"),
            production_domain=value_after(lines, "운영 도메인"),
            mock_domain=value_after(lines, "모의투자 도메인"),
            url=value_after(lines, "URL"),
            description=section(text, "개요", {"Request", "Response"}),
            start_page=start_index + 1,
            end_page=end_index + 1,
            # The ordinal prevents case-only real-time IDs (for example 0G
            # and 0g) from colliding on Windows and macOS filesystems.
            file=f"apis/{position + 1:03d}-{api_id}.md",
        )
        apis.append(api)
        write_api(
            output_dir / "apis",
            ApiDocument(**{**asdict(api), "file": Path(api.file).name}),
            text,
        )

    error_text = clean_page(reader.pages[-1].extract_text() or "")
    (output_dir / "errors.md").write_text(
        "# 키움 REST API 공통 오류코드\n\n"
        f"> 원문 PDF {len(reader.pages)}페이지에서 자동 변환했습니다.\n\n"
        "```text\n" + error_text + "\n```\n",
        encoding="utf-8",
    )
    write_readme(output_dir, pdf_path.name, apis)
    manifest = {
        "source": pdf_path.name,
        "source_pages": len(reader.pages),
        "api_count": len(apis),
        "apis": [asdict(api) for api in apis],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, default=Path("docs/kiwoom-rest-api"))
    args = parser.parse_args()
    convert(args.pdf, args.output)


if __name__ == "__main__":
    main()
