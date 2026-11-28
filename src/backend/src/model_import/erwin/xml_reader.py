"""Streaming reader for erwin Data Modeler XML exports.

Turns an erwin XML file (*Save As → XML*: "XML Standard", "XML Standard with
Min Info" or "XML Repository Format") into a flat list of ``RawObject``s. It
knows the erwin layout but nothing about entity or attribute semantics.
``builder.py`` turns the raw objects into the IR.

erwin XML layout (EMX schema, ``EMX.xsd`` / ``EMXProps.xsd`` / ``UDP.xsd``)::

    <erwin Format="..." FormatVersion="...">
      <EMX:Model id="{GUID}+00000000" name="...">
        <EMX:ModelProps> <EMX:Name>…</EMX:Name> … </EMX:ModelProps>
        <EMX:Entity_Groups>
          <EMX:Entity id="…" name="…">
            <EMX:EntityProps> … <UDP:Entity.Logical.Owner>…</UDP:…> </EMX:EntityProps>
            <EMX:Attribute_Groups> <EMX:Attribute id="…"> <EMX:AttributeProps>…

An *object* is an element with an ``id`` attribute whose parent is a
``*_Groups`` container (or the ``Model`` itself). Its properties are the
children of its ``<Type>Props`` element. Repeated properties (``index="n"``)
become lists. Matching is on XML local names, so the ``EMX:`` prefix and a
default namespace both work.

Security: parsing goes through ``defusedxml`` with DTDs forbidden, so entity
expansion (billion laughs), external entities (XXE) and network fetches are
rejected before any content is processed. The file is read as a stream and
each object's element is cleared once it has been read, so memory grows with
the number of objects, not the file size.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import IO, Dict, List, Optional, Union

import defusedxml.ElementTree as SafeET
from defusedxml import DefusedXmlException

from src.common.logging import get_logger

logger = get_logger(__name__)


class ErwinParseError(ValueError):
    """The file is not a readable erwin XML export."""


@dataclass
class RawObject:
    id: str
    type: str
    name: Optional[str]
    parent_id: Optional[str]
    # Property local name → values in document order. UDP values are keyed
    # ``UDP:<local name>``.
    props: Dict[str, List[str]] = field(default_factory=dict)

    def first(self, *names: str) -> Optional[str]:
        """The first non-empty value of the first listed property that has one."""
        for n in names:
            for v in self.props.get(n, ()):
                if v not in (None, ""):
                    return v
        return None

    def all(self, name: str) -> List[str]:
        return [v for v in self.props.get(name, ()) if v not in (None, "")]


@dataclass
class RawModel:
    root_attributes: Dict[str, str]
    objects: List[RawObject]


def _split(tag: str) -> tuple:
    """(namespace, local name) of an ElementTree tag."""
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    if ":" in tag:
        prefix, _, local = tag.partition(":")
        return prefix, local
    return "", tag


def _is_udp_namespace(ns: str) -> bool:
    return "udp" in ns.lower()


def read_erwin_xml(source: Union[str, IO[bytes]]) -> RawModel:
    """Stream an erwin XML export into raw objects.

    ``source`` is a path or a binary file object.
    """
    objects: List[RawObject] = []
    # One entry per open element: (local name, RawObject | None)
    stack: List[tuple] = []
    object_stack: List[RawObject] = []
    root_attributes: Dict[str, str] = {}
    root_seen = False

    try:
        for event, elem in SafeET.iterparse(
            source, events=("start", "end"), forbid_dtd=True,
            forbid_entities=True, forbid_external=True,
        ):
            ns, local = _split(elem.tag)
            if event == "start":
                if not root_seen:
                    root_seen = True
                    root_attributes = dict(elem.attrib)
                    if local.lower() != "erwin":
                        raise ErwinParseError(
                            f"Not an erwin XML export (root element is <{local}>, expected <erwin>)."
                        )
                parent_local = stack[-1][0] if stack else ""
                obj = None
                obj_id = elem.attrib.get("id")
                if obj_id and (parent_local.endswith("_Groups") or local == "Model"):
                    obj = RawObject(
                        id=obj_id,
                        type=local,
                        name=elem.attrib.get("name"),
                        parent_id=object_stack[-1].id if object_stack else None,
                    )
                    object_stack.append(obj)
                stack.append((local, obj))
                continue

            # end event
            local_name, obj = stack.pop()
            parent_local = stack[-1][0] if stack else ""
            if parent_local.endswith("Props") and object_stack:
                key = f"UDP:{local}" if _is_udp_namespace(ns) else local
                text = (elem.text or "").strip()
                object_stack[-1].props.setdefault(key, []).append(text)
                elem.clear()
            elif obj is not None:
                object_stack.pop()
                objects.append(obj)
                elem.clear()
    except ErwinParseError:
        raise
    except DefusedXmlException as e:
        raise ErwinParseError(
            f"Rejected: the file uses XML features that are not allowed ({type(e).__name__})."
        ) from e
    except SafeET.ParseError as e:
        raise ErwinParseError(f"Invalid XML: {e}") from e

    if not root_seen:
        raise ErwinParseError("Empty file.")
    if not any(o.type == "Model" for o in objects):
        raise ErwinParseError("No <Model> element found; is this an erwin model export?")
    return RawModel(root_attributes=root_attributes, objects=objects)
