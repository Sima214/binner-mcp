"""In-memory bidirectional part cache and identity resolution for Binner API."""

from typing import Any, Dict, List, Optional, Tuple


class PartCacheComp:
    """
    Component providing in-memory bidirectional caching (part_id <-> part_number)
    and part identity resolution.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._part_id_to_number: Dict[int, str] = {}
        self._part_number_to_id: Dict[str, int] = {}

    def _cache_part(self, part_id: Optional[int], part_number: Optional[str]) -> None:
        """Record a known part_id <-> part_number mapping in memory."""
        if part_id is not None and part_number:
            pid = int(part_id)
            pnum = str(part_number).strip()
            self._part_id_to_number[pid] = pnum
            self._part_number_to_id[pnum] = pid

    def _uncache_part(self, part_id: int) -> None:
        """Remove a deleted part from memory cache."""
        pid = int(part_id)
        if pid in self._part_id_to_number:
            pnum = self._part_id_to_number.pop(pid, None)
            if pnum and pnum in self._part_number_to_id:
                self._part_number_to_id.pop(pnum, None)

    def _cache_parts(self, parts: List[Any]) -> None:
        """Batch record parts into memory cache."""
        for p in parts:
            if hasattr(p, "part_id") and hasattr(p, "part_number"):
                self._cache_part(p.part_id, p.part_number)
            elif isinstance(p, dict):
                pid = p.get("partId") or p.get("part_id")
                pnum = p.get("partNumber") or p.get("part_number")
                self._cache_part(pid, pnum)

    def _resolve_part_identity(
        self,
        part_id: Optional[int],
        part_number: Optional[str],
    ) -> Tuple[Optional[int], Optional[str]]:
        """
        Ensure both part_id and part_number are populated when modifying quantities.

        Binner's backend queries require both when PartId > 0:
          WhereIf(request.PartId > 0, x => x.PartId == request.PartId)
          WhereIf(request.PartId > 0, x => x.PartNumber == request.PartNumber)

        Checks the in-memory cache first. On miss, searches exhaustively across all pages.
        """
        if part_id is not None and part_number is not None:
            self._cache_part(part_id, part_number)
            return part_id, part_number

        # 1. Fast in-memory cache lookup
        if part_id is not None and part_id in self._part_id_to_number:
            return part_id, self._part_id_to_number[part_id]

        if part_number is not None and part_number in self._part_number_to_id:
            return self._part_number_to_id[part_number], part_number

        # 2. Part number given without part ID -> lookup by number
        if part_number is not None and part_id is None:
            part = getattr(self, "get_part_by_number")(part_number)
            if part:
                self._cache_part(part.part_id, part.part_number)
                return part.part_id, part_number
            return part_id, part_number

        # 3. Part ID given without part number -> resolve via get_part_number_by_id
        if part_id is not None and not part_number:
            resolved_num = getattr(self, "get_part_number_by_id")(part_id)
            if resolved_num:
                return part_id, resolved_num

        return part_id, part_number
 