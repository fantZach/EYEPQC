"""Validation helpers for ELF-owned DDR buffers used by JTAG tools."""


def require_disjoint_ranges(named_ranges, label="owned DDR buffers"):
    """Reject overlapping half-open ranges supplied as (name, start, size)."""
    ranges = []
    for name, start, size in named_ranges:
        if start < 0 or size <= 0:
            raise ValueError("invalid " + label + " range: " + name)
        ranges.append((start, start + size, name))
    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            raise ValueError("overlapping " + label + ": " + previous[2] + "/" + current[2])
