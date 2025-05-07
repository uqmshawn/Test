"""Utility functions for handling device data."""

from typing import List, TypedDict, Optional, Dict, Any
from dataclasses import dataclass, field


class DeviceMeasures(TypedDict, total=False):
    """TypedDict representing device measures data."""

    pwr: int
    tankPct: float
    tankRem: float
    bmsPct: float
    bmsRem: float
    flow: float
    outPsi: float
    outKpa: float
    task: str
    valve: str


@dataclass
class ComparisonResult:
    """Holds the result of a measure comparison with reasons for differences."""

    is_different: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class MeasurementValues:
    """Group measurement-related values."""

    tank_pct: float
    bms_pct: float
    flow: float
    out_psi: float
    out_kpa: float


@dataclass
class ComparisonValues:
    """Helper class to store measurement values for comparison."""

    measurements: MeasurementValues
    pwr: int
    task: str
    valve: str

    @classmethod
    def from_measures(cls, measures: DeviceMeasures) -> "ComparisonValues":
        """Create ComparisonValues from DeviceMeasures."""
        measurements = MeasurementValues(
            tank_pct=_get_measure_value(measures, "tankPct", 0),
            bms_pct=_get_measure_value(measures, "bmsPct", 0),
            flow=_get_measure_value(measures, "flow", 0),
            out_psi=_get_measure_value(measures, "outPsi", 0),
            out_kpa=_get_measure_value(measures, "outKpa", 0),
        )
        return cls(
            measurements=measurements,
            pwr=_get_measure_value(measures, "pwr", 0),
            task=_get_measure_value(measures, "task", ""),
            valve=_get_measure_value(measures, "valve", ""),
        )


def extract_measures(device_data: Dict[str, Any]) -> Optional[DeviceMeasures]:
    """Extract measures from device data payload."""
    if not device_data.get("device"):
        return None

    device = device_data["device"]
    task_states = device.get("task", {})
    valve_states = device.get("valve", {})

    # Convert task and valve dictionaries to strings of active states
    task_str = ",".join(sorted(k for k, v in task_states.items() if v))
    valve_str = ",".join(sorted(k for k, v in valve_states.items() if v))

    remaining_ah = float(device.get("bms", {}).get("remainingAh", 0) or 0)
    full_ah = float(device.get("bms", {}).get("fullAh", 1) or 1)
    bms_pct = (remaining_ah / full_ah) * 100 if full_ah else 0

    return DeviceMeasures(
        pwr=1 if device.get("system", {}).get("isOn") else 0,
        tankPct=float(device.get("tank", {}).get("percent", 0) or 0),
        tankRem=float(device.get("tank", {}).get("litresRemaining", 0) or 0),
        bmsPct=bms_pct,
        bmsRem=remaining_ah,
        flow=float(device.get("flowMeter", {}).get("flow", 0) or 0),
        outPsi=float(device.get("outletPSI", 0) or 0),
        outKpa=float(device.get("outletKPA", 0) or 0),
        task=task_str,
        valve=valve_str,
    )


def _get_measure_value(measures: DeviceMeasures, key: str, default: Any = 0) -> Any:
    """Safely get a value from measures dict with a default."""
    return measures.get(key, default)


def are_measures_different(
    m1: Optional[DeviceMeasures], m2: Optional[DeviceMeasures]
) -> ComparisonResult:
    """
    Compare two sets of device measures to determine if they are significantly different.

    Args:
        m1: First set of measures
        m2: Second set of measures

    Returns:
        ComparisonResult: Contains whether measures are different and why
    """
    result = ComparisonResult(is_different=False)

    # If one is None and the other isn't, they are different
    if (not m1 and m2) or (m1 and not m2):
        result.is_different = True
        result.reasons.append("One measure set is None while the other isn't")
        return result

    # If both are None, they are the same
    if not m1 and not m2:
        return result

    # We know both m1 and m2 are not None at this point
    assert m1 is not None and m2 is not None

    v1 = ComparisonValues.from_measures(m1)
    v2 = ComparisonValues.from_measures(m2)

    threshold = 1  # 1% difference threshold

    # Check each value and record the reason if different
    if abs(v1.measurements.tank_pct - v2.measurements.tank_pct) > threshold:
        result.reasons.append(
            f"Tank % changed by {v1.measurements.tank_pct - v2.measurements.tank_pct:.1f}%"
        )
        result.is_different = True

    if abs(v1.measurements.bms_pct - v2.measurements.bms_pct) > threshold:
        result.reasons.append(
            f"Battery % changed by {v1.measurements.bms_pct - v2.measurements.bms_pct:.1f}%"
        )
        result.is_different = True

    if abs(v1.measurements.flow - v2.measurements.flow) > 1:
        result.reasons.append(
            f"Flow changed by {v1.measurements.flow - v2.measurements.flow:.1f}"
        )
        result.is_different = True

    if abs(v1.measurements.out_psi - v2.measurements.out_psi) > 1:
        result.reasons.append(
            f"PSI changed by {v1.measurements.out_psi - v2.measurements.out_psi:.1f}"
        )
        result.is_different = True

    if abs(v1.measurements.out_kpa - v2.measurements.out_kpa) > 1:
        result.reasons.append(
            f"KPA changed by {v1.measurements.out_kpa - v2.measurements.out_kpa:.1f}"
        )
        result.is_different = True

    if v1.pwr != v2.pwr:
        result.reasons.append(f"Power changed from {v1.pwr} to {v2.pwr}")
        result.is_different = True

    if v1.task != v2.task:
        result.reasons.append(f"Task changed from '{v1.task}' to '{v2.task}'")
        result.is_different = True

    if v1.valve != v2.valve:
        result.reasons.append(f"Valve changed from '{v1.valve}' to '{v2.valve}'")
        result.is_different = True

    return result
