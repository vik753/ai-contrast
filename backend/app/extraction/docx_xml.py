"""Safe streaming XML for DOCX parts (S3-T2 AC3, AC4; threat model T4).

Every part is parsed with ``defusedxml`` and ``forbid_dtd=True`` (and the defaults
``forbid_entities=True``, ``forbid_external=True``): any DTD, entity declaration or
external reference fails with ``suspicious_package``, before an entity can be
expanded. Malformed XML is ``suspicious_package`` too: Word does not open it as is.

Parsing is streaming (``iterparse`` over the checked part stream of
``docx_zip``). Each element is cleared and detached from its parent after the
consumer has seen its ``end`` event, so memory does not grow with the part. Depth
and element caps are shared by all parts of one document (``XmlBudget``); a cap
fails closed with ``suspicious_package``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final, cast
from xml.etree.ElementTree import Element, ParseError

import defusedxml
import defusedxml.ElementTree

from app.extraction.docx_zip import PartStream
from app.extraction.model import SUSPICIOUS_PACKAGE, ExtractionError

START: Final = "start"
END: Final = "end"
START_NS: Final = "start-ns"
_EVENTS: Final = (START, END, START_NS)


def suspicious() -> ExtractionError:
    return ExtractionError(SUSPICIOUS_PACKAGE)


class XmlBudget:
    """The depth cap per part and the element cap over all parts of one document."""

    def __init__(self, *, max_depth: int, max_elements: int) -> None:
        self.max_depth = max_depth
        self.max_elements = max_elements
        self.elements = 0


def iter_xml(stream: PartStream, budget: XmlBudget) -> Iterator[tuple[str, Any]]:
    """Events ``(START, element)``, ``(END, element)`` and ``(START_NS, (prefix, uri))``.

    An ``END`` element is cleared when the consumer asks for the next event; do not
    keep references to elements.
    """
    stack: list[Element] = []
    max_depth = budget.max_depth
    try:
        events = cast(
            "Iterator[tuple[str, Any]]",
            defusedxml.ElementTree.iterparse(stream, events=_EVENTS, forbid_dtd=True),
        )
        for event, item in events:
            if event == START:
                budget.elements += 1
                if budget.elements > budget.max_elements or len(stack) >= max_depth:
                    raise suspicious()
                stack.append(item)
                yield event, item
            elif event == END:
                yield event, item
                stack.pop()
                item.clear()
                # The element is the last child of its parent: detach it.
                if stack:
                    parent = stack[-1]
                    if len(parent) and parent[-1] is item:
                        del parent[-1]
            else:
                yield event, item
    except (defusedxml.DefusedXmlException, ParseError):
        raise suspicious() from None
    stream.drain()
