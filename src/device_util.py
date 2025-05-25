"""Utility functions for handling device data."""

import logging
from typing import List, TypedDict, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone


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


class BMSMeasures(TypedDict, total=False):
    """TypedDict representing BMS measures data."""

    volts: float
    amps: float
    watts: float
    remainingAh: float
    fullAh: float
    charging: bool
    temp: float
    stateOfCharge: float
    stateOfHealth: float
    iRSOC: int


class MultiPlusMeasures(TypedDict, total=False):
    """TypedDict representing MultiPlus measures data."""

    voltsIn: float
    ampsIn: float
    wattsIn: float
    freqIn: float
    voltsOut: float
    ampsOut: float
    wattsOut: float
    freqOut: float


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


def extract_bms_measures(device_data: Dict[str, Any]) -> Optional[BMSMeasures]:
    """Extract BMS measures from device data payload."""
    if not device_data.get("device"):
        return None

    device = device_data["device"]
    bms = device.get("bms", {})
    if not bms:
        return None

    # Add additional field for battery percentage integer - map from iRSOC or stateOfCharge
    if "iRSOC" not in bms and "stateOfCharge" in bms:
        # If iRSOC isn't present, derive it from stateOfCharge
        bms["iRSOC"] = int(bms["stateOfCharge"])

    return BMSMeasures(
        volts=float(bms.get("volts", 0) or 0),
        amps=float(bms.get("amps", 0) or 0),
        watts=float(bms.get("watts", 0) or 0),
        remainingAh=float(bms.get("remainingAh", 0) or 0),
        fullAh=float(bms.get("fullAh", 0) or 0),
        charging=bool(bms.get("charging", False)),
        temp=float(bms.get("temp", 0) or 0),
        stateOfCharge=float(bms.get("stateOfCharge", 0) or 0),
        stateOfHealth=float(bms.get("stateOfHealth", 0) or 0),
        iRSOC=bms.get("iRSOC", 0),
    )


def extract_multiplus_measures(
    device_data: Dict[str, Any]
) -> Optional[MultiPlusMeasures]:
    """Extract MultiPlus measures from device data payload."""
    if not device_data.get("device"):
        return None

    device = device_data["device"]
    mp = device.get("multiPlus", {})
    if not mp:
        return None

    return MultiPlusMeasures(
        voltsIn=float(mp.get("voltsIn", 0) or 0),
        ampsIn=float(mp.get("ampsIn", 0) or 0),
        wattsIn=float(mp.get("wattsIn", 0) or 0),
        freqIn=float(mp.get("freqIn", 0) or 0),
        voltsOut=float(mp.get("voltsOut", 0) or 0),
        ampsOut=float(mp.get("ampsOut", 0) or 0),
        wattsOut=float(mp.get("wattsOut", 0) or 0),
        freqOut=float(mp.get("freqOut", 0) or 0),
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


def are_bms_measures_different(
    m1: Optional[BMSMeasures], m2: Optional[BMSMeasures]
) -> ComparisonResult:
    """
    Compare two sets of BMS measures to determine if they are significantly different.

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
        result.reasons.append("One BMS measure set is None while the other isn't")
        return result

    # If both are None, they are the same
    if not m1 and not m2:
        return result

    # We know both m1 and m2 are not None at this point
    assert m1 is not None and m2 is not None

    # Voltage threshold: 0.1V difference
    if abs(m1.get("volts", 0) - m2.get("volts", 0)) > 0.1:
        result.reasons.append(
            f"BMS voltage changed by {m1.get('volts', 0) - m2.get('volts', 0):.2f}V"
        )
        result.is_different = True

    # Current threshold: 0.5A difference
    if abs(m1.get("amps", 0) - m2.get("amps", 0)) > 0.5:
        result.reasons.append(
            f"BMS current changed by {m1.get('amps', 0) - m2.get('amps', 0):.2f}A"
        )
        result.is_different = True

    # Power threshold: 10W difference
    if abs(m1.get("watts", 0) - m2.get("watts", 0)) > 10:
        result.reasons.append(
            f"BMS power changed by {m1.get('watts', 0) - m2.get('watts', 0):.2f}W"
        )
        result.is_different = True

    # Remaining capacity threshold: 0.5Ah difference
    if abs(m1.get("remainingAh", 0) - m2.get("remainingAh", 0)) > 0.5:
        result.reasons.append(
            f"BMS remaining capacity changed by {m1.get('remainingAh', 0) - m2.get('remainingAh', 0):.2f}Ah"
        )
        result.is_different = True

    # State of charge threshold: 1% difference
    if abs(m1.get("stateOfCharge", 0) - m2.get("stateOfCharge", 0)) > 1:
        result.reasons.append(
            f"BMS SOC changed by {m1.get('stateOfCharge', 0) - m2.get('stateOfCharge', 0):.1f}%"
        )
        result.is_different = True

    # Temperature threshold: 1°C difference
    if abs(m1.get("temp", 0) - m2.get("temp", 0)) > 1:
        result.reasons.append(
            f"BMS temperature changed by {m1.get('temp', 0) - m2.get('temp', 0):.1f}°C"
        )
        result.is_different = True

    # Charging state change
    if m1.get("charging", False) != m2.get("charging", False):
        result.reasons.append(
            f"BMS charging state changed from {m1.get('charging', False)} to {m2.get('charging', False)}"
        )
        result.is_different = True

    # Integer state of charge threshold: 1% difference
    if abs(m1.get("iRSOC", 0) - m2.get("iRSOC", 0)) > 1:
        result.reasons.append(
            f"BMS iRSOC changed by {m1.get('iRSOC', 0) - m2.get('iRSOC', 0):.1f}%"
        )
        result.is_different = True

    return result


def are_multiplus_measures_different(
    m1: Optional[MultiPlusMeasures], m2: Optional[MultiPlusMeasures]
) -> ComparisonResult:
    """
    Compare two sets of MultiPlus measures to determine if they are significantly different.

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
        result.reasons.append("One MultiPlus measure set is None while the other isn't")
        return result

    # If both are None, they are the same
    if not m1 and not m2:
        return result

    # We know both m1 and m2 are not None at this point
    assert m1 is not None and m2 is not None

    # Voltage threshold: 0.5V difference
    if abs(m1.get("voltsIn", 0) - m2.get("voltsIn", 0)) > 0.5:
        result.reasons.append(
            f"MultiPlus input voltage changed by {m1.get('voltsIn', 0) - m2.get('voltsIn', 0):.2f}V"
        )
        result.is_different = True

    if abs(m1.get("voltsOut", 0) - m2.get("voltsOut", 0)) > 0.5:
        result.reasons.append(
            f"MultiPlus output voltage changed by {m1.get('voltsOut', 0) - m2.get('voltsOut', 0):.2f}V"
        )
        result.is_different = True

    # Current threshold: 1A difference
    if abs(m1.get("ampsIn", 0) - m2.get("ampsIn", 0)) > 1:
        result.reasons.append(
            f"MultiPlus input current changed by {m1.get('ampsIn', 0) - m2.get('ampsIn', 0):.2f}A"
        )
        result.is_different = True

    if abs(m1.get("ampsOut", 0) - m2.get("ampsOut", 0)) > 1:
        result.reasons.append(
            f"MultiPlus output current changed by {m1.get('ampsOut', 0) - m2.get('ampsOut', 0):.2f}A"
        )
        result.is_different = True

    # Power threshold: 20W difference
    if abs(m1.get("wattsIn", 0) - m2.get("wattsIn", 0)) > 20:
        result.reasons.append(
            f"MultiPlus input power changed by {m1.get('wattsIn', 0) - m2.get('wattsIn', 0):.2f}W"
        )
        result.is_different = True

    if abs(m1.get("wattsOut", 0) - m2.get("wattsOut", 0)) > 20:
        result.reasons.append(
            f"MultiPlus output power changed by {m1.get('wattsOut', 0) - m2.get('wattsOut', 0):.2f}W"
        )
        result.is_different = True

    # Frequency threshold: 0.1Hz difference
    if abs(m1.get("freqIn", 0) - m2.get("freqIn", 0)) > 0.1:
        result.reasons.append(
            f"MultiPlus input frequency changed by {m1.get('freqIn', 0) - m2.get('freqIn', 0):.2f}Hz"
        )
        result.is_different = True

    if abs(m1.get("freqOut", 0) - m2.get("freqOut", 0)) > 0.1:
        result.reasons.append(
            f"MultiPlus output frequency changed by {m1.get('freqOut', 0) - m2.get('freqOut', 0):.2f}Hz"
        )
        result.is_different = True

    return result
