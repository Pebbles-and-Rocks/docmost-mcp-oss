"""Live test: edit the BODY of an already-created page (via Yjs WebSocket).

Requires the extras: ``uv sync --extra yjs``.

Flow that is verified:

1. Creates a page with content (``/pages/import``).
2. Converts new Markdown into Tiptap structure using Docmost itself
   (``blocks_from_markdown``).
3. **Replaces the body of the existing page** over the Yjs WebSocket.
4. Waits for persistence (10 s debounce) and checks via REST.
5. Deletes the test page.

Usage::

    uv run --extra yjs python tests/smoke_yjs_live.py
    uv run --extra yjs python tests/smoke_yjs_live.py --keep
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docmost_mcp_oss.client import DocmostClient  # noqa: E402
from docmost_mcp_oss.collab import (  # noqa: E402
    CollabClient,
    blocks_from_markdown,
    blocks_to_markdown,
)

CREDS = Path(__file__).resolve().parents[1] / ".docmost-creds.json"

INICIAL = "# Test page\n\nThis is the **original** content.\n"
NUEVO = """# Edited content

This paragraph was written **over the Yjs WebSocket**, not the REST API.

## With formatting

- Item with `code`
- Item in **bold**

| Column A | Column B |
| --- | --- |
| one | two |

```python
print("code block")
```
"""


async def main(keep: bool) -> int:
    creds = json.loads(CREDS.read_text())
    client = DocmostClient(
        creds["url"],
        api_key=creds.get("api_key"),
        email=creds.get("email") or creds.get("username"),
        password=creds.get("password"),
    )
    await client.authenticate()
    spaces = await client.list_spaces(limit=10)
    space = spaces[0]
    print(f"· instance: {client.base_url} | space: {space['name']!r}")

    # 1) page with initial content
    created = await client.create_page(space["id"], title="YJS smoke", content=INICIAL)
    page_id = created.get("slugId") or created.get("id")
    print(f"\n1) page created: {page_id}")
    antes = (await client.export_page(page_id, format="markdown"))["content"]
    print(f"   before: {antes!r}")

    # 2) convert the new Markdown into Tiptap structure
    blocks = await blocks_from_markdown(client, space["id"], NUEVO)
    print(f"\n2) markdown converted: {len(blocks)} block(s) -> {[b.tag for b in blocks]}")
    print("   preview:")
    for line in blocks_to_markdown(blocks).splitlines()[:8]:
        print(f"     | {line}")

    # 3) replace the body of the EXISTING page
    async with CollabClient(client.base_url, await client.get_collab_token()) as collab:
        await collab.open(await client.resolve_page_id(page_id))
        actuales = await collab.read_blocks()
        print(f"\n3) document opened: {len(actuales)} current block(s)")
        sent = await collab.replace_blocks(blocks)
        print(f"   delta sent: {sent} bytes")
        await collab.wait_for_persistence()

    # 4) verify via REST
    despues = (await client.export_page(page_id, format="markdown"))["content"]
    print(f"\n4) after (REST):\n{despues}")

    checks = [
        ("the title is preserved", "# YJS smoke" in despues or "# Test page" in despues),
        ("the old content is gone", "original" not in despues),
        ("the new paragraph is present", "Yjs WebSocket" in despues),
        (
            "the bold text is preserved",
            "**over the Yjs WebSocket**" in despues or "**bold**" in despues,
        ),
        ("the inline code is present", "`code`" in despues),
        ("the code block is present", "print(" in despues),
        ("the table is present", "Column A" in despues),
    ]
    print("5) checks:")
    fallos = 0
    for name, condition in checks:
        print(f"   {'✓' if condition else '✗'} {name}")
        fallos += 0 if condition else 1

    # 5) cleanup
    if keep:
        print(f"\n· page kept: {page_id}")
    else:
        await client.delete_page(page_id)
        print(f"\n· page deleted: {page_id}")
    await client.aclose()

    print(f"\n{'✅ Body edit verified' if not fallos else f'❌ {fallos} failure(s)'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", action="store_true", help="do not delete the test page")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.keep)))
