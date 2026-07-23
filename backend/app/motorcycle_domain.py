from enum import Enum


class MotorcycleDataGroup(str, Enum):
    IDENTITY = "identity"
    MARKET_PRICE = "market_price"
    TECHNICAL_SPECS = "technical_specs"
    CONSUMPTION = "consumption"
    MAINTENANCE = "maintenance"
    RELIABILITY = "reliability"
    PARTS_AVAILABILITY = "parts_availability"
    SAFETY_EQUIPMENT = "safety_equipment"
    ERGONOMICS = "ergonomics"
    TAXES = "taxes"
    INSURANCE = "insurance"
    DERIVED_METRICS = "derived_metrics"


class MotorcycleDerivedMetricName(str, Enum):
    URBAN_SCORE = "urban_score"
    ROAD_SCORE = "road_score"
    PASSENGER_COMFORT_SCORE = "passenger_comfort_score"
    LUGGAGE_SCORE = "luggage_score"
    ERGONOMICS_SCORE = "ergonomics_score"
    BEGINNER_FRIENDLINESS_SCORE = "beginner_friendliness_score"
    SAFETY_SCORE = "safety_score"
    MAINTENANCE_SCORE = "maintenance_score"
    PARTS_AVAILABILITY_SCORE = "parts_availability_score"
    RELIABILITY_SCORE = "reliability_score"
    RECOMMENDED_EXPERIENCE = "recommended_experience"


class MotorcycleMetricStatus(str, Enum):
    UNCALCULATED = "uncalculated"
    DEMONSTRATION = "demonstration"
    UNVALIDATED = "unvalidated"
    CALCULATED = "calculated"
    DEPRECATED = "deprecated"


class MotorcycleEconomicEstimateName(str, Enum):
    ANNUAL_DEPRECIATION_RATE_PERCENT = "depreciation_rate_annual_percent"


class MotorcycleEconomicEstimateStatus(str, Enum):
    DEMONSTRATION = "demonstration"
    UNVALIDATED = "unvalidated"
    CALCULATED = "calculated"
    DEPRECATED = "deprecated"


REGISTRATION_REQUIRED_SOURCE_GROUPS = frozenset({MotorcycleDataGroup.IDENTITY.value})
PILOT_REQUIRED_SOURCE_GROUPS = frozenset(
    {
        MotorcycleDataGroup.IDENTITY.value,
        MotorcycleDataGroup.MARKET_PRICE.value,
        MotorcycleDataGroup.TECHNICAL_SPECS.value,
        MotorcycleDataGroup.CONSUMPTION.value,
    }
)
COMPLEMENTARY_SOURCE_GROUPS = frozenset(
    {
        MotorcycleDataGroup.MAINTENANCE.value,
        MotorcycleDataGroup.RELIABILITY.value,
        MotorcycleDataGroup.PARTS_AVAILABILITY.value,
        MotorcycleDataGroup.SAFETY_EQUIPMENT.value,
        MotorcycleDataGroup.ERGONOMICS.value,
        MotorcycleDataGroup.TAXES.value,
        MotorcycleDataGroup.INSURANCE.value,
        MotorcycleDataGroup.DERIVED_METRICS.value,
    }
)
# Compatibility names remain internal aliases; API responses expose the explicit
# pilot/complementary terminology introduced in schema 0.3.1.
ELIGIBILITY_REQUIRED_SOURCE_GROUPS = PILOT_REQUIRED_SOURCE_GROUPS
OPTIONAL_SOURCE_GROUPS = COMPLEMENTARY_SOURCE_GROUPS


class MotorcycleEligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    INCOMPLETE = "incomplete"
    INSUFFICIENT_CONFIDENCE = "insufficient_confidence"
    DEMONSTRATION_ONLY = "demonstration_only"
    EXCLUDED_BY_DOMAIN_RULE = "excluded_by_domain_rule"
    UNSUPPORTED_CATEGORY = "unsupported_category"
    OUTDATED_DATA = "outdated_data"


class MotorcycleFutureReadiness(str, Enum):
    STRUCTURALLY_READY = "structurally_ready"
    MISSING_ECONOMIC_DATA = "missing_economic_data"
    MISSING_METHODOLOGICAL_DATA = "missing_methodological_data"
    INSUFFICIENT_SOURCE_CONFIDENCE = "insufficient_source_confidence"
    DEMONSTRATION_ONLY = "demonstration_only"
    NOT_READY = "not_ready"


class MotorcycleMarketCondition(str, Enum):
    NEW = "new"
    USED = "used"


class MotorcycleFuelType(str, Enum):
    GASOLINE = "gasoline"
    FLEX = "flex"
    ELECTRIC = "electric"
    OTHER = "other"


class MotorcycleTransmissionType(str, Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    SEMI_AUTOMATIC = "semi_automatic"
    CVT = "cvt"
    ELECTRIC_DIRECT = "electric_direct"
    OTHER = "other"


class MotorcycleFinalDriveType(str, Enum):
    CHAIN = "chain"
    BELT = "belt"
    SHAFT = "shaft"
    DIRECT = "direct"
    OTHER = "other"
