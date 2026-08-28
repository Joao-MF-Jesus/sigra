from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from app.integrated_gold.simulation_repository import (
    VehicleCostSimulationRepository,
    VehicleCostSimulationStorageError,
)
from data_platform.integrated_vehicle_cost.simulation import (
    VehicleCostSimulationError,
    VehicleCostSimulationSelectionConflictError,
    simulate_vehicle_costs,
)
from data_platform.integrated_vehicle_cost.simulation_contracts import (
    VehicleCostSimulationBatch,
    VehicleCostSimulationScenario,
)


class VehicleCostSimulationUnavailableError(RuntimeError):
    pass


class VehicleCostSimulationConflictError(RuntimeError):
    pass


class VehicleCostSimulationReader(Protocol):
    def eligible_dataset(self): ...

    def evidence_rows(self, dataset_version, vehicle_sks): ...

    def published_exclusions(self, dataset_version, vehicle_sks): ...


class VehicleCostSimulationService:
    def __init__(self, repository: VehicleCostSimulationReader):
        self._repository = repository

    def simulate(
        self,
        scenario: VehicleCostSimulationScenario,
    ) -> VehicleCostSimulationBatch:
        try:
            dataset = self._repository.eligible_dataset()
            if dataset is None:
                raise VehicleCostSimulationUnavailableError(
                    "no active and eligible integrated Gold dataset"
                )
            dataset_version = str(dataset["dataset_version"])
            evidence = self._repository.evidence_rows(
                dataset_version,
                scenario.vehicle_sks,
            )
            exclusions = self._repository.published_exclusions(
                dataset_version,
                scenario.vehicle_sks,
            )
            result = simulate_vehicle_costs(scenario, evidence, exclusions)
        except VehicleCostSimulationUnavailableError:
            raise
        except VehicleCostSimulationSelectionConflictError as exc:
            raise VehicleCostSimulationConflictError(
                "simulation selection matches multiple eligible Gold evidences"
            ) from exc
        except (VehicleCostSimulationStorageError, VehicleCostSimulationError) as exc:
            raise VehicleCostSimulationUnavailableError(
                "eligible integrated Gold simulation evidence is unavailable"
            ) from exc
        if result.evaluated_vehicle_count == 0:
            raise VehicleCostSimulationUnavailableError(
                "active integrated Gold has no simulation evidence"
            )
        return result


def simulation_service_for_session(
    session: Session,
) -> VehicleCostSimulationService:
    return VehicleCostSimulationService(VehicleCostSimulationRepository(session))
