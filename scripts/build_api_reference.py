"""Capture official documentation and mechanically render a local API reference.

Documentation GETs only. No account credentials, API calls, or trading code.
Requires PyYAML in the separate .docs-venv. Source cache is under ignored data/.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import re
import time
import textwrap
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HOST = "https://docs.kalshi.com"
CACHE = ROOT / "data" / "api-docs"
OUT = ROOT / "docs" / "KALSHI_API_REFERENCE.md"
METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
SPECS = {
    "openapi.yaml": "Predictions REST",
    "perps_openapi.yaml": "Perpetuals / margin REST",
    "perps_scm_openapi.yaml": "Clearing-member REST",
    "asyncapi.yaml": "Predictions WebSocket",
    "perps_asyncapi.yaml": "Perpetuals / margin WebSocket",
}


def fetch(url: str) -> dict:
    if not url.startswith(HOST + "/"):
        raise ValueError("Documentation host only")
    path = CACHE / url.removeprefix(HOST + "/")
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "Kalshi-local-documentation-reference/1.0"})
            with urllib.request.urlopen(request, timeout=40) as response:
                if not response.url.startswith(HOST + "/"):
                    raise ValueError("Unexpected documentation redirect")
                content = response.read()
                metadata = {
                    "url": url, "status": response.status,
                    "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                    "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                    "content_type": response.headers.get("Content-Type"),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "cache_path": path.relative_to(ROOT).as_posix(),
                }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return metadata
        except Exception as error:
            if attempt == 2:
                return {"url": url, "error": f"{type(error).__name__}: {error}"}
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def collect() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = [fetch(HOST + "/llms.txt"), fetch(HOST + "/sitemap.xml")]
    if any("error" in row for row in manifest):
        raise RuntimeError(manifest)
    index = (CACHE / "llms.txt").read_text(encoding="utf-8")
    urls = set(re.findall(
        r"^- \[[^\n]+?\]\((https://docs\.kalshi\.com/[^\s)]+)\)", index, re.M))
    sitemap = ET.fromstring((CACHE / "sitemap.xml").read_bytes())
    for loc in sitemap.findall(".//{*}loc"):
        url = (loc.text or "").rstrip("/")
        if url.startswith(HOST + "/"):
            urls.add(url if url.endswith(".md") else url + ".md")
    urls.update(HOST + "/" + name for name in SPECS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch, url): url for url in sorted(urls)}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = future.result()
            manifest.append(row)
            if "error" in row or i % 25 == 0 or i == len(urls):
                print(f"Fetched {i}/{len(urls)}; {row.get('error', 'OK')}", flush=True)
    (CACHE / "manifest.json").write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "sources": sorted(manifest, key=lambda row: row["url"]),
    }, indent=2), encoding="utf-8")


def blocks(text: str):
    """Extract complete fenced technical examples/specs without their prose."""
    pattern = re.compile(r"^[ \t]*(`{3,})([^\n]*)\n(.*?)^[ \t]*\1[ \t]*$", re.M | re.S)
    return [(match[2].strip(), textwrap.dedent(match[3]).rstrip()) for match in pattern.finditer(text)]


def technical_material(text: str, url: str):
    """Keep headings beside technical tables/examples, including MDX indentation."""
    token = re.compile(
        r"(?P<fence>^[ \t]*(?P<ticks>`{3,})(?P<lang>[^\n]*)\n(?P<body>.*?)^[ \t]*(?P=ticks)[ \t]*$)"
        r"|(?P<table>(?:^[ \t]*\|[^\n]*\n){2,})"
        r"|(?P<htmltable><table\b.*?</table>)"
        r"|(?P<heading>^#{2,6} [^\n]+)"
        r'|(?P<tab><Tab\s+title="[^"]+")'
        r"|(?P<host>^[ \t]*\*\*[^\n]*Host:\*\*[^\n]*)",
        re.M | re.S)
    result = []
    count = Counter()
    for match in token.finditer(text):
        if match["heading"]:
            result += ["**" + re.sub(r"^#+ ", "", match["heading"]) + "**", ""]
        elif match["tab"]:
            result += ["**" + re.search(r'title="([^"]+)"', match["tab"])[1] + "**", ""]
        elif match["host"]:
            result += [match["host"].strip(), ""]
        elif match["fence"]:
            body = textwrap.dedent(match["body"]).rstrip()
            fence = "`" * max(4, 1 + max((len(m[0]) for m in re.finditer(r"`+", body)), default=0))
            lang = match["lang"].strip().split(" ")[0]
            result += [fence + lang, body, fence, ""]
            count["code_blocks"] += 1
        elif match["table"]:
            table = textwrap.dedent(match["table"]).strip()
            table = re.sub(r"\]\((/[^)]+)\)", lambda m: "](" + HOST + m[1] + ")", table)
            table = re.sub(r"\]\((#[^)]+)\)", lambda m: "](" + url.removesuffix('.md') + m[1] + ")", table)
            result += [table, ""]
            count["tables"] += 1
        elif match["htmltable"]:
            rows = []
            for row in re.findall(r"<tr\b.*?</tr>", match["htmltable"], re.S):
                cells = re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", row, re.S)
                rows.append([re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", cell))).strip()
                             for cell in cells])
            if rows and rows[0]:
                result += ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
                result += ["| " + " | ".join(row) + " |" for row in rows[1:]]
                result.append("")
                count["tables"] += 1
    return result, dict(count)


def dump(value) -> str:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=100).rstrip()


def anchor(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def operations(spec):
    for path, item in spec.get("paths", {}).items():
        for method, operation in item.items():
            if method in METHODS:
                yield path, method, operation, item


def refs(value):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"]
        for child in value.values():
            yield from refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs(child)


def resolve(spec, pointer):
    if not pointer.startswith("#/"):
        return None
    value = spec
    for part in pointer[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def normalize_prose(value):
    if isinstance(value, dict):
        return {k: normalize_prose(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_prose(v) for v in value]
    return value.rstrip() if isinstance(value, str) else value


def render() -> dict:
    manifest = json.loads((CACHE / "manifest.json").read_text(encoding="utf-8"))
    available = {r["url"]: r for r in manifest["sources"] if "error" not in r}
    failures = [r for r in manifest["sources"] if "error" in r]
    specs = {name: yaml.safe_load((CACHE / name).read_text(encoding="utf-8"))
             for name in SPECS if HOST + "/" + name in available}
    pages = {}
    doc_operations = {}
    page_specs = []
    for url, row in available.items():
        if not url.endswith(".md"):
            continue
        text = (ROOT / row["cache_path"]).read_text(encoding="utf-8")
        title = re.search(r"^# (.+)$", text, re.M)
        pages[url] = {"title": title[1] if title else url, "text": text}
        for language, body in blocks(text):
            if "yaml" not in language:
                continue
            try:
                fragment = yaml.safe_load(body)
            except yaml.YAMLError:
                continue
            if not isinstance(fragment, dict) or "openapi" not in fragment:
                continue
            source = next((name for name in SPECS if "/" + name in language), None)
            if source is None:
                continue
            for path, method, operation, item in operations(fragment):
                doc_operations.setdefault((source, method, path), []).append(url)
                page_specs.append((source, method, path, operation, fragment, url))

    counts = {name: sum(1 for _ in operations(spec)) for name, spec in specs.items()
              if "openapi" in spec}
    missing_refs = []
    for name, spec in specs.items():
        for ref in sorted(set(refs(spec))):
            if resolve(spec, ref) is None:
                missing_refs.append({"spec": name, "reference": ref})
    root_keys = {(name, method, path) for name, spec in specs.items()
                 for path, method, _operation, _item in operations(spec)}
    page_only = [row for row in page_specs if row[:3] not in root_keys]
    undocumented = sorted(root_keys - set(doc_operations))
    differences = []
    component_differences = []
    for name, method, path, operation, fragment, url in page_specs:
        if (name, method, path) in root_keys:
            root = specs[name]["paths"][path][method]
            if root != operation:
                keys = sorted(k for k in root.keys() | operation.keys() if root.get(k) != operation.get(k))
                differences.append({"spec": name, "method": method, "path": path, "url": url,
                                    "different_keys": keys,
                                    "classification": "presentation extension" if keys == ["x-mint"] else "review required"})
            changed = []
            for kind, entries in fragment.get("components", {}).items():
                for key, value in entries.items():
                    if specs[name].get("components", {}).get(kind, {}).get(key) != value:
                        changed.append(kind + "/" + key)
            if changed:
                whitespace_only = all(
                    normalize_prose(specs[name]["components"][kind][key]) == normalize_prose(value)
                    for kind, entries in fragment.get("components", {}).items()
                    for key, value in entries.items())
                component_differences.append({
                    "spec": name, "url": url, "components": changed,
                    "classification": "trailing whitespace" if whitespace_only else "review required"})
    report = {
        "generated_utc": manifest["generated_utc"], "retrieved_pages": len(pages),
        "rest_operations": counts, "rest_total": sum(counts.values()),
        "websocket_channels": {name: len(spec.get("channels", {})) for name, spec in specs.items()
                               if "asyncapi" in spec},
        "websocket_operations": {name: len(spec.get("operations", {})) for name, spec in specs.items()
                                 if "asyncapi" in spec},
        "source_failures": failures, "unresolved_schema_references": missing_refs,
        "root_operations_without_page": undocumented,
        "page_only_operations": [(r[0], r[1], r[2], r[5]) for r in page_only],
        "operation_definition_differences": differences,
        "component_definition_differences": component_differences,
    }
    lines = ["# Kalshi API reference", "",
             f"Official documentation snapshot: **{manifest['generated_utc']}**.", "",
             "This is the local development reference for `kalshi-bot`. It documents API contracts; "
             "it does not authorize trading, transfers, or account changes. No account was accessed to build it.", "",
             "Scope: all operations in the official three OpenAPI files, both AsyncAPI files, "
             "and all pages discovered through `llms.txt` and `sitemap.xml`. Endpoint definitions and "
             "shared schemas are included without dropping optional fields, error responses, examples, "
             "deprecations, validation constraints, or specification extensions. FIX field tables and "
             "technical examples are included separately. Narrative guides are linked and their "
             "technical tables/examples extracted; this is not a verbatim copy of every guide.", "",
             "This is a dated snapshot, not a guarantee that the venue has not changed. "
             "Re-fetch the relevant official definition before implementing a write operation. "
             "Where a field or behavior is absent, it is unspecified; do not invent a default.", "",
             "## Contents", "",
             "- [Coverage and audit](#coverage-and-audit)",
             "- [Implementation notes](#implementation-notes)",
             "- [REST endpoint index](#rest-endpoint-index)",
             "- [Complete REST definitions](#complete-rest-definitions)",
             "- [WebSocket definitions](#websocket-definitions)",
             "- [FIX and guide technical material](#fix-and-guide-technical-material)",
             "- [All documentation pages](#all-documentation-pages)", "",
             "## Coverage and audit", "",
             f"Retrieved {len(pages)} documentation pages and {len(specs)}/{len(SPECS)} specification files.", "",
             "| API family | Version | Operations / channels | Source |", "|---|---|---:|---|"]
    for name, spec in specs.items():
        count = counts.get(name, len(spec.get("channels", {})))
        lines.append(f"| {SPECS[name]} | {spec['info'].get('version', 'unspecified')} | {count} | [{name}]({HOST}/{name}) |")
    lines += ["", f"REST operations: **{sum(counts.values())}**. "
              f"Failed sources: **{len(failures)}**. Unresolved schema references: **{len(missing_refs)}**.", "",
              "Source checksums, retrieval times, and file sizes are recorded in "
              "[API_REFERENCE_MANIFEST.json](API_REFERENCE_MANIFEST.json). "
              "Detailed coverage checks are in [API_REFERENCE_AUDIT.json](API_REFERENCE_AUDIT.json).", "",
              f"Spec operations without an individual indexed page: **{len(undocumented)}** "
              "(still included below). Page-only operations: "
              f"**{len(page_only)}**. Page/root operation-definition differences: **{len(differences)}**. "
              f"Pages with component-definition differences: **{len(component_differences)}**.", "",
              "The audit classifies the differences by type. `x-mint` is documentation-rendering "
              "metadata, and its embedded warning text remains in the root operation block. "
              "Trailing whitespace alone does not change a schema contract. Other differences require review.", "",
              "The CF Benchmarks wildcard REST passthrough is documented outside OpenAPI and is "
              "listed in the implementation notes and technical material; it is additional to the 191 spec operations.", ""]
    if failures or missing_refs:
        lines += ["### Retrieval/schema gaps", "", "```json", json.dumps(
            {"failed_sources": failures, "unresolved_references": missing_refs}, indent=2), "```", ""]
    notes = ROOT / "docs" / "API_REFERENCE_NOTES.md"
    lines += ["## Implementation notes", "", notes.read_text(encoding="utf-8") if notes.exists()
              else "Implementation notes pending review.", "", "## REST endpoint index", "",
              "Every REST operation is indexed by API family, method, path, and operation ID. "
              "A successful HTTP response is not proof of final order state; use the documented "
              "responses and reconciliation streams.", "",
              "| Family | Method | Path | Operation |", "|---|---|---|---|"]
    for name, spec in specs.items():
        for path, method, op, item in operations(spec):
            ident = anchor(name + "-" + method + "-" + path)
            lines.append(f"| {SPECS[name]} | {method.upper()} | `{path}` | "
                         f"[{op.get('operationId', op.get('summary', path))}](#{ident}) |")
    lines += ["", "## Complete REST definitions", "",
              "Each operation block preserves its path-level settings, operation definition, and "
              "effective security/servers. Resolve `$ref` using that API family's component appendix; "
              "schemas from different API families must not be mixed.", ""]
    for name, spec in specs.items():
        if "openapi" not in spec:
            continue
        lines += [f"### {SPECS[name]}", "", f"Source: [{name}]({HOST}/{name}).", "",
                  "#### Global specification settings", "", "```yaml",
                  dump({k: v for k, v in spec.items() if k not in {"paths", "components"}}), "```", ""]
        for path, method, op, item in operations(spec):
            ident = anchor(name + "-" + method + "-" + path)
            urls = doc_operations.get((name, method, path), [])
            lines += [f'<a id="{ident}"></a>', "", f"#### {method.upper()} `{path}`", "",
                      f"Operation: `{op.get('operationId', 'unspecified')}`. "
                      + ("Documentation: " + ", ".join(f"[page {i+1}]({url})" for i, url in enumerate(urls))
                         if urls else "No separate indexed page; defined in the official specification."), ""]
            inherited = {k: v for k, v in item.items() if k not in METHODS}
            operation_refs = sorted(set(refs(op)) | set(refs(inherited)))
            if operation_refs:
                lines += ["Referenced components: " + ", ".join(
                    f"[`{ref.split('/')[-1]}`](#{anchor(name + '-' + ref)})" for ref in operation_refs), ""]
            lines += ["```yaml", dump({
                "effective_servers": op.get("servers", item.get("servers", spec.get("servers", []))),
                "effective_security": op.get("security", spec.get("security", [])),
                "path": path, "method": method.upper(),
                "path_settings": inherited, "operation": op,
            }), "```", ""]
        lines += [f"#### {SPECS[name]} shared components", ""]
        for kind, entries in spec.get("components", {}).items():
            for key, value in entries.items():
                lines += [f'<a id="{anchor(name + "-#/components/" + kind + "/" + key)}"></a>', "",
                          f"##### `{kind}/{key}`", "", "```yaml", dump({key: value}), "```", ""]

    if page_only or differences or component_differences:
        lines += ["### Page-only operations and source differences", "",
                  "These definitions are retained separately rather than silently resolving a source conflict.", ""]
        diff_urls = {d["url"] for d in differences}
        diff_urls.update(d["url"] for d in component_differences)
        seen = set()
        for name, method, path, op, fragment, url in page_specs:
            if (name, method, path) in root_keys and url not in diff_urls:
                continue
            if url in seen:
                continue
            seen.add(url)
            lines += [f"#### {method.upper()} `{path}` — page definition", "", f"Source: {url}", "",
                      "```yaml", dump(fragment), "```", ""]

    lines += ["## WebSocket definitions", "",
              "The complete AsyncAPI definitions below include servers, handshake security, control commands, "
              "subscriptions, channels, operations, payload schemas, examples, and errors. "
              "Separate prediction and margin connections are documented separately.", ""]
    for name, spec in specs.items():
        if "asyncapi" not in spec:
            continue
        lines += [f"### {SPECS[name]}", "", f"Source: [{name}]({HOST}/{name}).", "",
                  "| Channel key | Address |", "|---|---|"]
        for channel, value in spec.get("channels", {}).items():
            lines.append(f"| `{channel}` | `{value.get('address', 'unspecified')}` |")
        lines += ["", "```yaml", dump(spec), "```", ""]

    lines += ["## FIX and guide technical material", "",
              "Exact protocol field tables and code/configuration examples from the indexed guides. "
              "Narrative behavior must be checked at the linked source, especially FIX session "
              "recovery and migration notices. Example credentials are placeholders from documentation.", ""]
    technical_counts = {}
    for url, page in sorted(pages.items()):
        if "/api-reference/" in url or "/margin-rest/" in url or "/websockets/" in url:
            continue
        text = page["text"]
        material, counts_for_page = technical_material(text, url)
        if not counts_for_page:
            continue
        technical_counts[url] = counts_for_page
        lines += [f"### {page['title']}", "", f"Source: [{page['title']}]({url})", ""]
        lines += material

    lines += ["## All documentation pages", "",
              "This inventory includes every fetched page from both official discovery sources. "
              "Endpoint schemas come from the specifications above; these links provide the "
              "remaining guide prose, migration explanations, and changelog context.", ""]
    for url, page in sorted(pages.items()):
        lines.append(f"- [{page['title']}]({url})")
    lines += ["", "## Updating this reference", "", "```powershell",
              ".\\.docs-venv\\Scripts\\python.exe scripts/build_api_reference.py --fetch", "```", "",
              "The generator only downloads public documentation. Raw retrievals are cached under "
              "ignored `data/api-docs/`. `--fetch` refreshes them; without it, generation uses the last "
              "manifest and cache. Review the audit after every refresh.", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    markdown = "\n".join(lines)
    OUT.write_text(markdown, encoding="utf-8")
    for name in SPECS:
        if name in specs:
            spec_copy = OUT.parent / "api-specs" / name
            spec_copy.parent.mkdir(exist_ok=True)
            spec_copy.write_bytes((CACHE / name).read_bytes())
    report["technical_extracts"] = technical_counts
    checks = {"operation_blocks_verified": 0, "component_blocks_verified": 0,
              "asyncapi_blocks_verified": 0, "source_hashes_verified": 0}
    for name, spec in specs.items():
        if "asyncapi" in spec:
            assert dump(spec) in markdown, name
            checks["asyncapi_blocks_verified"] += 1
            continue
        for path, method, op, item in operations(spec):
            expected = {"effective_servers": op.get("servers", item.get("servers", spec.get("servers", []))),
                        "effective_security": op.get("security", spec.get("security", [])),
                        "path": path, "method": method.upper(),
                        "path_settings": {k: v for k, v in item.items() if k not in METHODS},
                        "operation": op}
            assert dump(expected) in markdown, (name, method, path)
            assert yaml.safe_load(dump(expected)) == expected, (name, method, path, "roundtrip")
            checks["operation_blocks_verified"] += 1
        for entries in spec.get("components", {}).values():
            for key, value in entries.items():
                assert dump({key: value}) in markdown, (name, key)
                assert yaml.safe_load(dump({key: value})) == {key: value}, (name, key, "roundtrip")
                checks["component_blocks_verified"] += 1
    for row in available.values():
        assert hashlib.sha256((ROOT / row["cache_path"]).read_bytes()).hexdigest() == row["sha256"], row["url"]
        checks["source_hashes_verified"] += 1
    assert all(url in markdown for url in pages), "Missing page inventory entry"
    ids = re.findall(r'<a id="([^"]+)"></a>', markdown)
    assert len(ids) == len(set(ids)), "Duplicate explicit anchor"
    checks["unique_explicit_anchors"] = len(ids)
    checks["indexed_pages_verified"] = len(pages)
    report["verification"] = checks
    report["markdown_bytes"] = OUT.stat().st_size
    report["markdown_sha256"] = hashlib.sha256(OUT.read_bytes()).hexdigest()
    (OUT.parent / "API_REFERENCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUT.parent / "API_REFERENCE_AUDIT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "technical_extracts"}, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch:
        collect()
    result = render()
    if result["source_failures"] or result["unresolved_schema_references"]:
        raise SystemExit(2)
