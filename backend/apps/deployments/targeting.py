"""
Conditional targeting — lọc danh sách máy đích theo `Deployment.targeting_rule`
dựa trên inventory (InstalledSoftware).

Rule hỗ trợ hiện tại:
  {"exclude_if_software": "Google Chrome"}                 -> chỉ chạy trên máy CHƯA có
  {"exclude_if_software": "Google Chrome", "min_version": "120"}
       -> loại máy đã có phiên bản >= 120 (máy có bản cũ hơn vẫn chạy để nâng cấp)
"""


def _ver_tuple(v: str) -> tuple:
    parts = []
    for p in (v or "").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _ver_ge(a: str, b: str) -> bool:
    return _ver_tuple(a) >= _ver_tuple(b)


def resolve_targets(deployment):
    """Trả list[Machine] sẽ thực sự chạy sau khi áp targeting_rule."""
    base = deployment.target_machines.filter(enabled=True)
    rule = deployment.targeting_rule or {}
    name = rule.get("exclude_if_software")
    if not name:
        return list(base)

    min_version = rule.get("min_version")
    if not min_version:
        # Loại mọi máy đã có phần mềm khớp tên (bất kể phiên bản).
        has = base.filter(installed_software__name__icontains=name)
        return list(base.exclude(pk__in=has.values("pk")))

    # Có min_version: so phiên bản trong Python (không so được cross-DB bằng SQL).
    exclude_ids = []
    for m in base.prefetch_related("installed_software"):
        matched = [s for s in m.installed_software.all() if name.lower() in s.name.lower()]
        if any(_ver_ge(s.version, min_version) for s in matched):
            exclude_ids.append(m.pk)
    return list(base.exclude(pk__in=exclude_ids))
