"""Part type (category) hierarchy resolver and ambiguity validator for Binner MCP."""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import requests

from binner_mcp.common.exceptions import BaseProxyError

logger = logging.getLogger("binner_mcp.mcp.categories")

DELIMITER_PATTERN = re.compile(r"::|#|>|/")


class CategoryResolver:
    """
    Maintains cached part type hierarchy and resolves category names, paths,
    and numeric IDs with strict ambiguity detection.
    """

    def __init__(self, delimiter: str = "::") -> None:
        self.delimiter: str = delimiter
        self.type_map: Dict[int, Any] = {}
        self.path_by_id: Dict[int, str] = {}
        self.ids_by_leaf_name: Dict[str, List[int]] = {}
        self.ids_by_full_path: Dict[str, List[int]] = {}

    def update(self, raw_types: List[Any]) -> None:
        """
        Rebuild internal category hierarchy cache and reverse multi-indices.

        Args:
            raw_types: List of PartType response models or dicts from Binner API.
        """
        self.type_map.clear()
        self.path_by_id.clear()
        self.ids_by_leaf_name.clear()
        self.ids_by_full_path.clear()

        for t in raw_types:
            tid = getattr(t, "part_type_id", None)
            if tid is None and isinstance(t, dict):
                tid = t.get("part_type_id") or t.get("partTypeId")
            if tid is not None:
                try:
                    self.type_map[int(tid)] = t
                except (ValueError, TypeError):
                    continue

        for tid, item in self.type_map.items():
            name = getattr(item, "name", None)
            if name is None and isinstance(item, dict):
                name = item.get("name")
            name = str(name).strip() if name else f"Type_{tid}"

            parts = [name]
            curr = item
            visited: Set[int] = {tid}

            while True:
                parent_id = getattr(curr, "parent_part_type_id", None)
                if parent_id is None and isinstance(curr, dict):
                    parent_id = curr.get("parent_part_type_id") or curr.get("parentPartTypeId")

                if parent_id is None:
                    break
                try:
                    parent_id_int = int(parent_id)
                except (ValueError, TypeError):
                    break

                if parent_id_int not in self.type_map or parent_id_int in visited:
                    break

                visited.add(parent_id_int)
                curr = self.type_map[parent_id_int]
                parent_name = getattr(curr, "name", None)
                if parent_name is None and isinstance(curr, dict):
                    parent_name = curr.get("name")
                parent_name = str(parent_name).strip() if parent_name else f"Type_{parent_id_int}"
                parts.insert(0, parent_name)

            full_path = self.delimiter.join(parts)
            self.path_by_id[tid] = full_path

            leaf_lower = name.lower()
            self.ids_by_leaf_name.setdefault(leaf_lower, []).append(tid)

            full_path_lower = full_path.lower()
            self.ids_by_full_path.setdefault(full_path_lower, []).append(tid)

    def warm_cache(
        self,
        proxy: Any,
        category_cache: Optional[Dict[int, str]] = None,
        category_name_to_id: Optional[Dict[str, int]] = None,
    ) -> bool:
        """
        Fetch all part categories from Binner proxy and build hierarchical category paths.

        Updates internal resolver state as well as any provided external cache dictionaries.
        """
        try:
            raw_types = proxy.get_part_types()
            self.update(raw_types)
            if category_cache is not None:
                category_cache.clear()
                category_cache.update(self.path_by_id)
            if category_name_to_id is not None:
                category_name_to_id.clear()
                for tid, path in self.path_by_id.items():
                    category_name_to_id[path.lower()] = tid
                    leaf_name = path.split(self.delimiter)[-1].strip().lower()
                    category_name_to_id[leaf_name] = tid
            return True
        except (requests.RequestException, BaseProxyError, ValueError, KeyError) as err:
            logger.debug("Category cache pre-warming failed: %s", err)
            return False

    _warm_category_cache = warm_cache
    warm_category_cache = warm_cache

    def get_path(self, part_type_id: int) -> Optional[str]:
        """Return the formatted hierarchy path for a numeric category ID."""
        return self.path_by_id.get(part_type_id)

    def find_matches(self, name_or_path: str) -> List[Tuple[int, str]]:
        """
        Find all existing category IDs and hierarchy paths matching a query string.

        Args:
            name_or_path: Category name, partial path, full path, or numeric ID string.

        Returns:
            List of (part_type_id, full_path) tuples.
        """
        q = str(name_or_path).strip()
        if not q:
            return []

        # 1. Numeric ID lookup
        if q.isdigit():
            pid = int(q)
            if pid in self.path_by_id:
                return [(pid, self.path_by_id[pid])]
            return []

        q_lower = q.lower()

        # 2. Exact full path match
        # Try both the verbatim string and delimiter-normalized string
        norm_q = self.delimiter.join(DELIMITER_PATTERN.split(q_lower))
        exact_ids = self.ids_by_full_path.get(q_lower) or self.ids_by_full_path.get(norm_q)
        if exact_ids:
            return [(pid, self.path_by_id[pid]) for pid in exact_ids]

        # 3. Exact leaf name match (only if input is a single segment without delimiters)
        has_delimiter = bool(DELIMITER_PATTERN.search(q))
        if not has_delimiter:
            leaf_ids = self.ids_by_leaf_name.get(q_lower)
            if leaf_ids:
                return [(pid, self.path_by_id[pid]) for pid in leaf_ids]

        # 4. Partial path / suffix matching
        segments = [s.strip().lower() for s in DELIMITER_PATTERN.split(q) if s.strip()]
        if segments:
            matched_ids: List[int] = []
            for tid, cand_path in self.path_by_id.items():
                cand_segments = [s.strip().lower() for s in cand_path.split(self.delimiter) if s.strip()]

                # Suffix match (e.g. "Resistors::SMD" matching "Passives::Resistors::SMD")
                if len(cand_segments) >= len(segments) and cand_segments[-len(segments):] == segments:
                    matched_ids.append(tid)
                    continue

                # Subsequence match with matching leaf (e.g. "Passives::SMD" matching "Passives::Resistors::SMD")
                if cand_segments and cand_segments[-1] == segments[-1]:
                    # Verify all query segments appear in order in cand_segments
                    it = iter(cand_segments)
                    if all(seg in it for seg in segments):
                        matched_ids.append(tid)

            if matched_ids:
                seen: Set[int] = set()
                unique_matched: List[Tuple[int, str]] = []
                for mid in matched_ids:
                    if mid not in seen:
                        seen.add(mid)
                        unique_matched.append((mid, self.path_by_id[mid]))
                return unique_matched

        return []

    def resolve(
        self,
        part_type: Optional[Union[str, int]],
    ) -> Tuple[Optional[int], Optional[str], Optional[str]]:
        """
        Resolve an overloaded part_type input (numeric ID, leaf name, or path string).

        Args:
            part_type: Category identifier (int ID, digit string, leaf name, or path string).

        Returns:
            Tuple of (resolved_part_type_id, resolved_path_or_name, error_message).
            If resolution succeeds, error_message is None.
            If input is ambiguous, non-existent, or invalid, error_message contains details.
        """
        if part_type is None:
            return None, None, None

        # 1. Integer ID
        if isinstance(part_type, int) and not isinstance(part_type, bool):
            if part_type in self.path_by_id:
                return part_type, self.path_by_id[part_type], None
            return None, None, f"Part type ID {part_type} does not exist in inventory."

        # 2. Type validation
        if not isinstance(part_type, (str, int)):
            return (
                None,
                None,
                f"Invalid part_type type: expected string or integer ID, got {type(part_type).__name__}.",
            )

        # 3. String validation
        s = str(part_type).strip()
        if not s:
            return None, None, "'part_type' cannot be blank or whitespace-only."

        # 4. Numeric string
        if s.isdigit():
            pid = int(s)
            if pid in self.path_by_id:
                return pid, self.path_by_id[pid], None
            return None, None, f"Part type ID {pid} does not exist in inventory."

        # 5. Search for existing matches
        matches = self.find_matches(s)
        if len(matches) > 1:
            candidates = ", ".join(f"ID {tid} '{path}'" for tid, path in matches)
            return (
                None,
                None,
                f"Ambiguous part type '{s}'. Matches {len(matches)} categories: [{candidates}]. "
                "Please specify the full category path or numeric ID.",
            )

        if len(matches) == 1:
            matched_id, matched_path = matches[0]
            return matched_id, matched_path, None

        # 6. No existing match found: treat as new category path
        # Check if parent segments are ambiguous
        segments = [seg.strip() for seg in DELIMITER_PATTERN.split(s) if seg.strip()]
        if len(segments) > 1:
            parent_part = self.delimiter.join(segments[:-1])
            parent_matches = self.find_matches(parent_part)
            if len(parent_matches) > 1:
                candidates = ", ".join(f"ID {tid} '{path}'" for tid, path in parent_matches)
                return (
                    None,
                    None,
                    f"Ambiguous parent category in path '{s}'. Parent '{parent_part}' matches "
                    f"{len(parent_matches)} categories: [{candidates}]. Please specify the full path.",
                )

        # Valid new category path
        return None, s, None
