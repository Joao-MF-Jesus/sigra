from enum import Enum


class VehicleType(str, Enum):
    CAR = "car"
    MOTORCYCLE = "motorcycle"


class CarUseCase(str, Enum):
    CITY = "cidade"
    FAMILY = "familia"
    WORK = "trabalho"
    ROAD = "estrada"
    APP = "app"
    SUV = "suv"


class CarCategory(str, Enum):
    COMPACT = "compact"
    SUBCOMPACT = "subcompact"
    COMPACT_HATCH = "compact_hatch"
    COMPACT_SEDAN = "compact_sedan"
    COMPACT_MINIVAN = "compact_minivan"
    MINIVAN = "minivan"
    MIDSIZE_SEDAN = "midsize_sedan"
    COMPACT_SUV = "compact_suv"
    SUV = "suv"


class RecommendationStrategy(str, Enum):
    LOWEST_COST = "lowest_cost"
    BUDGET_ECONOMY = "budget_economy"
    COST_BENEFIT = "cost_benefit"
    BALANCED = "balanced"
    COMFORT_SPACE = "comfort_space"
    BEST_WITHIN_BUDGET = "best_within_budget"


class MotorcycleCategory(str, Enum):
    SCOOTER = "scooter"
    UNDERBONE = "underbone"
    STREET = "street"
    NAKED = "naked"
    TRAIL = "trail"
    ADVENTURE = "adventure"
    CUSTOM = "custom"
    SPORT = "sport"
    TOURING = "touring"


class RiderExperience(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    EXPERIENCED = "experienced"


class DataSource(str, Enum):
    DEMONSTRATION = "demonstration"
    ESTIMATED = "estimated"
    OFFICIAL = "official"
    USER_REPORTED = "user_reported"
